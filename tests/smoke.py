"""Run the real engines on a generated clip. All review decisions concern this fixture."""
import argparse
import asyncio
import json
import os
from pathlib import Path
import socket
import subprocess
import sys
import tempfile
import time
from urllib.error import HTTPError

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
parser=argparse.ArgumentParser()
parser.add_argument("--work",type=Path)
parser.add_argument("--resume-fixture",action="store_true")
args=parser.parse_args()
work=(args.work or Path(tempfile.mkdtemp(prefix="shotwork-test-"))).resolve()
work.mkdir(parents=True,exist_ok=True)
with socket.socket() as sock:
    sock.bind(("127.0.0.1",0))
    port=sock.getsockname()[1]
os.environ.update(SHOTWORK_PORT=str(port),SHOTWORK_DATA=str(work/"state"),PYTHONUTF8="1")
from runtime import URL, api
from media import ff, timeline
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client


async def session_test():
    params=StdioServerParameters(command=sys.executable,args=["-X","utf8",str(ROOT/"mcp_server.py")],
        env={**os.environ,"PYTHONIOENCODING":"utf-8"})
    async with stdio_client(params) as (read,write), ClientSession(read,write) as session:
        await session.initialize()
        tools=await session.list_tools()
        assert {t.name for t in tools.tools}=={"create_video_jobs","get_video_job","list_video_jobs"}
        reply=await session.call_tool("create_video_jobs",dict(sources=[str(work/"sample.mp4")],
            titles=["合成测试样片"],output_directory=str(work/"export")))
        assert not reply.isError,reply
        return json.loads(reply.content[0].text) if reply.structuredContent is None else reply.structuredContent["result"][0]


def wait(jid,state):
    for _ in range(1500):
        j=api("/api/jobs/"+jid)
        if j["state"]==state:return j
        if j["state"]=="failed":raise RuntimeError(j["error"])
        time.sleep(1)
    raise TimeoutError(state)


def submit(j,name,**extra):
    return api("/api/jobs/"+j["id"],dict(version=j["version"],action=name,**extra))


def exercise():
    inputs=[]
    for c in ("navy","orange","darkgreen"):
        inputs.extend(["-f","lavfi","-i",f"color=c={c}:s=320x240:r=24:d=1"])
    ff([*inputs,"-f","lavfi","-i","sine=frequency=440:sample_rate=44100:duration=3",
        "-filter_complex","[0:v][1:v][2:v]concat=n=3:v=1:a=0,drawtext=text='VIDEO REVIEW':fontsize=26:fontcolor=white:x=48:y=170[v]",
        "-map","[v]","-map","3:a","-c:v","libx264","-c:a","aac",work/"sample.mp4"])
    options=dict(areas=[[163,205,35,270]],mode="sttn-auto")
    if args.resume_fixture:
        row=next(r for r in api("/api/jobs") if Path(r["source"])==work/"sample.mp4" and r["state"]=="failed")
        jid=row["id"]
        submit(api("/api/jobs/"+jid),"retry")
    else:
        row=asyncio.run(session_test())
        if isinstance(row,list):row=row[0]
        jid=row["id"]
        j=wait(jid,"selection")
        assert len(j["shots"])==3,j
        try:submit(j,"finish")
        except HTTPError as e:assert e.code==400
        else:raise AssertionError("accepted early merge")
        submit(j,"select",shots=[dict(id="03",**options),dict(id="01",mode="sttn-det",areas=options["areas"])])
    j=wait(jid,"quality")
    print("Real VSR revisions produced.",flush=True)
    sn=lambda j,sid:next(s for s in j["shots"] if s["id"]==sid)
    j=submit(j,"approve",id="03",revision=1)
    submit(j,"redo",id="01",revision=1,note="测试第二修订",**options)
    j=wait(jid,"quality")
    assert sn(j,"03")["approved"] and not sn(j,"01")["approved"] and sn(j,"01")["revision"]==2
    try:submit(j,"approve",id="01",revision=1)
    except HTTPError as e:assert e.code==400
    else:raise AssertionError("accepted stale revision")
    j=submit(j,"approve",id="01",revision=2)
    existing=work/"export"/"原有文件.mp4";existing.parent.mkdir(exist_ok=True);existing.write_bytes(b"keep")
    submit(j,"finish")
    j=wait(jid,"done")
    assert existing.read_bytes()==b"keep" and len(j["files"])==3
    assert [Path(p).name.split("_")[-2] for p in j["files"][:2]]==["分镜03","分镜01"]
    assert set(p.name for p in existing.parent.iterdir())=={existing.name,*(Path(p).name for p in j["files"])}
    pts,_=timeline(j["files"][-1])
    assert len(pts)==49 and pts[-1]==2000000
    print("PASS",jid,j["files"][-1],flush=True)


if __name__=="__main__":
    with (work/"service.log").open("wb") as log:
        process=subprocess.Popen([sys.executable,"-X","utf8",str(ROOT/"service.py")],
                                 stdout=log,stderr=log,cwd=ROOT)
        try:
            for _ in range(100):
                try:api("/api/health");break
                except OSError:time.sleep(.25)
            print("QA",URL,work,flush=True)
            exercise()
        finally:
            process.terminate()
            process.wait(timeout=15)
