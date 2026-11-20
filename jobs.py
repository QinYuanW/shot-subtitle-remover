import json
import re
import sqlite3
import threading
import uuid
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path

import media
from runtime import DATA, DEFAULT_OUT, SETTINGS

BUSY = {"detecting", "cleaning", "assembling"}
ACTIVE = set()
LOCK = threading.RLock()
POOLS = {"detecting":ThreadPoolExecutor(3), "cleaning":ThreadPoolExecutor(1),
         "assembling":ThreadPoolExecutor(1)}
EXTENSIONS = {".mp4",".mov",".mkv",".m4v",".avi",".webm",".mts",".m2ts",".mpg",".mpeg",".ts",".flv",".wmv"}


@contextmanager
def database():
    DATA.mkdir(exist_ok=True,parents=True)
    conn=sqlite3.connect(DATA/"jobs.sqlite3",timeout=20)
    try:
        with conn:
            conn.execute("CREATE TABLE IF NOT EXISTS jobs (id TEXT PRIMARY KEY, document TEXT NOT NULL)")
            yield conn
    finally:
        conn.close()


def all_jobs():
    with database() as db:
        return [json.loads(r[0]) for r in db.execute("SELECT document FROM jobs ORDER BY rowid DESC")]


def get(jid):
    with database() as db:
        row=db.execute("SELECT document FROM jobs WHERE id=?", (jid,)).fetchone()
    if not row:
        raise KeyError("找不到这项任务")
    return json.loads(row[0])


def save(job):
    job["version"]+=1
    job["updated"]=datetime.now().astimezone().isoformat(timespec="seconds")
    with database() as db:
        db.execute("INSERT OR REPLACE INTO jobs VALUES (?,?)",(job["id"],json.dumps(job,ensure_ascii=False)))


def summary(job):
    return {k:job[k] for k in ("id","label","source","state","selected","error","files","updated","output")}


def output_path(value):
    out=Path(value or DEFAULT_OUT)
    if not out.is_absolute() or (out.exists() and not out.is_dir()):
        raise ValueError("请填写成品文件夹的绝对路径")
    return out.resolve()


def create(sources,output=None,titles=None):
    if not isinstance(sources,list) or not sources or len(sources)>100:
        raise ValueError("请提供 1 至 100 个本地视频路径")
    paths=[Path(str(p).strip().strip('"')) for p in sources]
    if any(not p.is_absolute() or not p.is_file() or p.suffix.lower() not in EXTENSIONS for p in paths):
        raise ValueError("某个素材路径无效，请填写已存在的视频绝对路径")
    if len({p.resolve() for p in paths})!=len(paths):
        raise ValueError("同一批里包含重复的素材路径")
    if titles and (len(titles)!=len(paths) or not all(isinstance(x,str) for x in titles)):
        raise ValueError("视频名称数量和素材数量不符")
    out=output_path(output)
    with LOCK:
        numbers=[int(j["label"].split("_",1)[0]) for j in all_jobs() if Path(j["output"])==out]
        if out.exists():
            numbers.extend(int(m[1]) for p in out.iterdir() if (m:=re.match(r"^(\d+)_",p.name)))
        start=max(numbers,default=0)+1
        jobs=[]
        for i,p in enumerate(paths):
            title=(titles[i] if titles else p.stem)
            title=re.sub(r'[<>:"/\\|?*\x00-\x1f]'," ",title).strip().strip(".")[:54] or "视频"
            jid=uuid.uuid4().hex
            job=dict(id=jid,label=f"{start+i:03d}_{title}",source=str(p.resolve()),output=str(out),
                state="detecting",version=0,selected=[],shots=[],files=[],error="",history=[])
            (DATA/"jobs"/jid).mkdir(parents=True)
            save(job)
            jobs.append(job)
        for job in jobs:
            schedule(job)
    return [summary(j) for j in jobs]


def options(shot,choice):
    mode=choice.get("mode",shot["mode"])
    areas=choice.get("areas",shot["areas"])
    if mode not in media.MODES or not isinstance(areas,list) or len(areas)>32:
        raise ValueError("修复模式或选区无效")
    w,h=shot["size"]
    for r in areas:
        if (not isinstance(r,list) or len(r)!=4 or any(type(n)!=int for n in r)
                or not (0<=r[0]<r[1]<=h and 0<=r[2]<r[3]<=w)):
            raise ValueError("选区超出了画面")
    if mode=="sttn-auto" and not areas:
        raise ValueError("整块修复模式需要先在画面上框选去字区域")
    shot.update(mode=mode,areas=areas,note=str(choice.get("note",""))[:1000])


def event(j,action,**details):
    j["history"].append(dict(time=datetime.now().astimezone().isoformat(timespec="seconds"),
                             action=action,**details))


def action(jid,body):
    with LOCK:
        j=get(jid)
        if body.get("version")!=j["version"]:
            raise ValueError("任务已更新，请刷新后查看当前版本")
        name=body.get("action")
        shots={s["id"]:s for s in j["shots"]}
        state=j["state"]
        if name=="select" and state=="selection":
            choices=body.get("shots",[])
            ids=[s["id"] for s in choices]
            if len(set(ids))!=len(ids) or any(i not in shots for i in ids):
                raise ValueError("所选镜头编号无效")
            for choice in choices:
                s=shots[choice["id"]]
                options(s,choice)
                s["revision"]=1
            j["selected"]=ids
            j["state"]="cleaning" if ids else "empty"
            event(j,"selection",ids=ids)
        elif name in ("approve","redo","redo_many") and state=="quality":
            changes=body.get("shots",[]) if name=="redo_many" else [body]
            if not changes or len({c["id"] for c in changes})!=len(changes):
                raise ValueError("请勾选需要返工的分镜")
            for change in changes:
                sid=change.get("id")
                if sid not in j["selected"]:
                    raise ValueError("分镜未入选")
                s=shots[sid]
                if s["revision"]!=change.get("revision") or not s["sha256"]:
                    raise ValueError("请审核当前修订版")
                if name=="approve":
                    s["approved"]=s["sha256"]
                else:
                    options(s,change)
                    s.update(revision=s["revision"]+1,approved=None,sha256=None)
                    j["state"]="cleaning"
                event(j,name,id=sid,revision=s["revision"],hash=s["approved"],note=s["note"])
        elif name=="finish" and state=="quality":
            if not j["selected"] or any(not shots[i]["approved"] or shots[i]["approved"]!=shots[i]["sha256"] for i in j["selected"]):
                raise ValueError("请先逐段通过所有当前修订版")
            j["state"]="assembling"
            event(j,"finish",ids=j["selected"])
        elif name=="retry" and state=="failed":
            j["state"]=j["failed_stage"]
            if j["state"]=="assembling" and body.get("output"):
                j["output"]=str(output_path(body["output"]))
            if j["state"]=="cleaning" and "mode" in body:
                pending=next(s for sid in j["selected"] for s in [shots[sid]] if not s["sha256"])
                options(pending,body)
            j["error"]=""
        else:
            raise ValueError("当前阶段不接受此操作")
        save(j)
        schedule(j)
        return j


def schedule(j):
    if j["state"] in BUSY and j["id"] not in ACTIVE:
        ACTIVE.add(j["id"])
        POOLS[j["state"]].submit(worker,j["id"])


def worker(jid):
    j=get(jid)
    stage=j["state"]
    folder=DATA/"jobs"/jid
    try:
        if stage=="detecting":
            j["shots"]=media.prepare(j,folder)
            j["state"]="selection"
        elif stage=="cleaning":
            shots={s["id"]:s for s in j["shots"]}
            for sid in j["selected"]:
                shot=shots[sid]
                if not shot["sha256"]:
                    shot["sha256"]=media.clean(folder,shot,SETTINGS)
                    save(j)
            j["state"]="quality"
        elif stage=="assembling":
            j["files"]=media.publish(media.assemble(j,folder),Path(j["output"]))
            j["state"]="done"
    except Exception as exc:
        j.update(state="failed",failed_stage=stage,error=str(exc))
    finally:
        with LOCK:
            save(j)
            ACTIVE.discard(jid)
