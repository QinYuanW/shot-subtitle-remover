"""Detect, cut and assemble on the source presentation timeline."""
import hashlib
import itertools
import json
import os
import shutil
import subprocess
import uuid
from fractions import Fraction
from pathlib import Path

import av
from scenedetect import AdaptiveDetector, detect
from runtime import SETTINGS

ROOT = Path(__file__).resolve().parent
TICK = Fraction(1, 1_000_000)
MODES = ("sttn-det", "sttn-auto", "lama", "propainter", "opencv")
FLAGS = getattr(subprocess, "CREATE_NO_WINDOW", 0)


def run(args, **kwargs):
    if args[0] in ("ffmpeg","ffprobe") and SETTINGS.get(args[0]):
        args=[SETTINGS[args[0]],*args[1:]]
    result = subprocess.run([str(x) for x in args], capture_output=True,
                            creationflags=FLAGS, **kwargs)
    if result.returncode:
        raise RuntimeError(result.stderr.decode("utf-8", "replace")[-2500:]
                           or f"{args[0]} exited {result.returncode}")
    return result.stdout


def ff(args):
    return run(["ffmpeg", "-hide_banner", "-loglevel", "error", "-nostdin", "-y", *args])


def digest(path):
    with Path(path).open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def timeline(path):
    data = json.loads(run(["ffprobe", "-v", "error", "-select_streams", "v:0",
        "-show_frames", "-show_streams", "-show_entries",
        "frame=best_effort_timestamp,duration:stream=time_base,avg_frame_rate,width,height",
        "-of", "json", path]))
    if not data.get("frames"):
        raise ValueError("视频没有可解码的画面")
    stream = data["streams"][0]
    scale = Fraction(stream["time_base"]) / TICK
    frames = data["frames"]
    pts = [round(int(f["best_effort_timestamp"]) * scale) for f in frames]
    last = int(frames[-1].get("duration", 0))
    last_delta = round(last * scale) if last else (pts[-1]-pts[-2] if len(pts)>1 else round(1_000_000/Fraction(stream["avg_frame_rate"])))
    pts.append(pts[-1]+last_delta)
    if any(b <= a for a,b in itertools.pairwise(pts)):
        raise ValueError("源视频存在重复或倒序的显示时间戳")
    return pts, stream


def ticks(value):
    return f"{value/1_000_000:.6f}"


def retime(encoded, target, pts):
    # Input H.264 is encoded without B-frames, so packet and display order coincide.
    with av.open(str(encoded)) as src, av.open(str(target), "w", options={
            "video_track_timescale":"1000000","movie_timescale":"1000000"}) as dst:
        vin = src.streams.video[0]
        out = dst.add_stream_from_template(vin)
        out.time_base = TICK
        count = 0
        for packet in src.demux(vin):
            if packet.dts is None:
                continue
            if count >= len(pts)-1:
                raise ValueError("修复引擎输出了多余的视频帧")
            packet.stream = out
            packet.time_base = TICK
            packet.pts = packet.dts = pts[count]-pts[0]
            packet.duration = pts[count+1]-pts[count]
            dst.mux(packet)
            count += 1
        if count != len(pts)-1:
            raise ValueError(f"帧数不符，应有 {len(pts)-1} 帧，实际 {count} 帧")


def mux(video, audio, target):
    inputs = ["-i", video]
    maps = ["-map","0:v:0", "-c:v","copy"]
    for index, wave in enumerate(audio, 1):
        inputs += ["-i", wave]
        maps += ["-map",f"{index}:a:0"]
    ff([*inputs, *maps, "-c:a","aac","-b:a","256k","-movie_timescale","1000000",
        "-video_track_timescale","1000000","-movflags","+faststart", target])
    tracks=json.loads(run(["ffprobe","-v","error","-select_streams","a","-show_entries",
        "stream=sample_rate,duration_ts,time_base,start_time","-of","json",target]))["streams"]
    if len(tracks)!=len(audio):
        raise ValueError("导出音轨数量不符")
    for track,wave in zip(tracks,audio):
        with av.open(str(wave)) as pcm:
            reference=pcm.streams.audio[0]
            duration=reference.duration*reference.time_base
        actual=int(track["duration_ts"])*Fraction(track["time_base"])
        if abs(float(track.get("start_time",0)))>.002 or abs(actual-duration)>.002:
            raise ValueError("导出音轨起点或时长不符")


def verify(path, expected, dimensions=None):
    pts, stream = timeline(path)
    if len(pts) != len(expected) or any(abs((a-pts[0])-(b-expected[0]))>2 for a,b in zip(pts,expected)):
        raise ValueError(f"{path.name} 的帧数或显示时间与原片不符")
    if dimensions and [stream["width"],stream["height"]] != dimensions:
        raise ValueError("修复引擎改变了画面尺寸")


def encode_video(source, target, extra=()):
    ff(["-i",source,"-map","0:v:0",*extra,"-an","-c:v","libx264","-preset","veryfast",
        "-crf","16","-bf","0","-pix_fmt","yuv420p","-threads","3","-fps_mode","passthrough",target])


def work_audio(folder, sid):
    return sorted(folder.glob(f"{sid}-a*.wav"))


def prepare(job, folder):
    source = Path(job["source"])
    pts, _ = timeline(source)
    bounds = {0, len(pts)-1}
    for start, _end in detect(str(source), AdaptiveDetector(), show_progress=False):
        bounds.add(start.get_frames())
    bounds = sorted(b for b in bounds if 0<=b<len(pts))
    audios = json.loads(run(["ffprobe","-v","error","-select_streams","a","-show_entries",
                             "stream=index,sample_rate","-of","json",source]))["streams"]
    (folder/"timeline.json").write_text(json.dumps(pts))
    shots = []
    for i,(a,b) in enumerate(itertools.pairwise(bounds),1):
        sid = f"{i:02d}"
        temp = folder/"cut-encoding.mp4"
        encode_video(source,temp,["-vf",f"trim=start_frame={a}:end_frame={b},setpts=PTS-STARTPTS"])
        video = folder/f"{sid}-picture.mp4"
        retime(temp,video,pts[a:b+1])
        for ix,stream in enumerate(audios):
            sr = int(stream["sample_rate"])
            samples = round(pts[b]*sr*TICK)-round(pts[a]*sr*TICK)
            af = f"asetpts=PTS-({ticks(pts[a])})/TB,aresample={sr}:async=1:first_pts=0,apad,atrim=end_sample={samples}"
            ff(["-copyts","-i",source,"-map",f"0:{stream['index']}","-af",af,
                "-c:a","pcm_s24le",folder/f"{sid}-a{ix:03d}.wav"])
        preview = folder/f"{sid}-raw.mp4"
        mux(video,work_audio(folder,sid),preview)
        verify(preview,pts[a:b+1])
        with av.open(str(preview)) as clip:
            st = clip.streams.video[0]
            size = [st.width,st.height]
        shots.append(dict(id=sid, first=a, end=b, start_us=pts[a]-pts[0],
            end_us=pts[b]-pts[0], size=size, revision=0, approved=None, areas=[],
            mode="sttn-det", note="", sha256=None))
    return shots


def engine(settings):
    home = Path(settings.get("vsr_home") or ROOT/"engines"/"vsr").resolve()
    python = Path(settings.get("vsr_python") or ROOT/".vsr-env"/("Scripts/python.exe" if os.name=="nt" else "bin/python")).resolve()
    if not (home/"backend"/"main.py").is_file() or not python.is_file():
        raise ValueError("VSR 引擎尚未就绪，请检查 vsr_home 和 vsr_python")
    return python,home


def clean(folder, shot, settings):
    python,home = engine(settings)
    sid,rev = shot["id"],shot["revision"]
    prefix = f"{sid}-r{rev}"
    raw = folder/f"{sid}-raw.mp4"
    result = folder/f"{prefix}-{uuid.uuid4().hex[:10]}-vsr.mp4"
    cmd = [str(python),"-m","backend.main","-i",str(raw),"-o",str(result),
           "--inpaint-mode",shot["mode"]]
    for area in shot["areas"]:
        cmd += ["-c",*map(str,area)]
    env = dict(os.environ, PYTHONUTF8="1", PYTHONIOENCODING="utf-8", PYTHONUNBUFFERED="1",
               PADDLE_PDX_DISABLE_MODEL_SOURCE_CHECK="True",QT_QPA_PLATFORM="offscreen")
    log = folder/f"{prefix}.log"
    with log.open("wb") as stream:
        proc = subprocess.run(cmd,cwd=home,env=env,stdout=stream,stderr=subprocess.STDOUT,creationflags=FLAGS)
    if proc.returncode or not result.is_file() or not result.stat().st_size:
        with log.open("rb") as stream:
            stream.seek(max(0,log.stat().st_size-1800))
            hint=stream.read().decode("utf-8","replace")
        if "Exception: No subtitles detected. Check file:" in hint:
            target=folder/f"{prefix}.mp4"
            shutil.copyfile(raw,target)
            shot["result_note"]="引擎未识别到字幕，当前为原画面。请核对，必要时框选区域返工。"
            return digest(target)
        raise RuntimeError(f"VSR 运行失败。日志 {log}\n{hint}")
    pts=json.loads((folder/"timeline.json").read_text())[shot["first"]:shot["end"]+1]
    encoded=folder/f"{prefix}-encoded.mp4"
    encode_video(result,encoded)
    picture=folder/f"{prefix}-picture.mp4"
    retime(encoded,picture,pts)
    target=folder/f"{prefix}.mp4"
    mux(picture,work_audio(folder,sid),target)
    verify(target,pts,shot["size"])
    shot["result_note"]=""
    return digest(target)


def concat_list(folder, name, paths, durations=None):
    # Internal filenames are exclusively generated ASCII basenames.
    listing=folder/name
    lines=["ffconcat version 1.0"]
    for i,p in enumerate(paths):
        lines.append(f"file '{p.name}'")
        if durations is not None:
            lines.append(f"duration {ticks(durations[i])}")
    listing.write_text("\n".join(lines)+"\n",encoding="ascii")
    return ["-f","concat","-safe","1","-i",listing]


def frame_hashes(path):
    result=ff(["-i",path,"-map","0:v:0","-an","-fps_mode","passthrough","-f","framemd5","-"])
    return [line.rsplit(b",",1)[1].strip() for line in result.splitlines() if not line.startswith(b"#")]


def assemble(job,folder):
    selected={s["id"]:s for s in job["shots"]}
    shots=[selected[sid] for sid in job["selected"]]
    pts=json.loads((folder/"timeline.json").read_text())
    durations=[]; expected=[0]; clips=[]; deliveries=[]
    for s in shots:
        stem=f"{s['id']}-r{s['revision']}"
        approved=folder/f"{stem}.mp4"
        if s["approved"] != s["sha256"] or digest(approved) != s["approved"]:
            raise ValueError(f"分镜 {s['id']} 的审核版本已失效")
        # Derive the final picture from the actual hash-approved file.
        pic=folder/f"{stem}-approved.mp4"
        ff(["-i",approved,"-map","0:v:0","-c:v","copy","-an","-video_track_timescale","1000000",
            "-movie_timescale","1000000",pic])
        clips.append(pic)
        local=pts[s["first"]:s["end"]+1]
        offset=expected[-1]
        expected.extend(offset+p-local[0] for p in local[1:])
        durations.append(local[-1]-local[0])
        deliveries.append((approved,f"{job['label']}_分镜{s['id']}_去水印.mp4"))
    picture=folder/"master-picture.mp4"
    ff([*concat_list(folder,"picture.ffconcat",clips,durations),"-c:v","copy",
        "-video_track_timescale","1000000","-movie_timescale","1000000",picture])
    combined=[]
    for ix,track in enumerate(zip(*(work_audio(folder,s["id"]) for s in shots),strict=True)):
        wave=folder/f"master-a{ix:03d}.wav"
        ff([*concat_list(folder,f"track-{ix}.ffconcat",track),"-c:a","pcm_s24le",wave])
        combined.append(wave)
    master=folder/"master.mp4"
    mux(picture,combined,master)
    verify(master,expected,shots[0]["size"])
    approved_frames=itertools.chain.from_iterable(frame_hashes(src) for src,_ in deliveries)
    if any(a!=b for a,b in itertools.zip_longest(approved_frames,frame_hashes(master))):
        raise ValueError("成片的画面或分镜顺序与审核版本不一致")
    ff(["-xerror","-i",master,"-map","0","-f","null","-"])
    return deliveries+[(master,f"{job['label']}_完整去水印.mp4")]


def publish(files,out):
    out.mkdir(exist_ok=True,parents=True)
    for src,name in files:
        dst=out/name
        if dst.exists() and digest(dst)!=digest(src):
            raise ValueError(f"成品目录已有同名文件，请改用其他目录：{dst}")
    for src,name in files:
        dst=out/name
        if dst.exists() and digest(dst)==digest(src):
            continue
        # Atomic no-clobber publication; stage on destination volume for cross-drive exports.
        tmp=out.parent/f".shotwork-{uuid.uuid4().hex}.tmp"
        try:
            shutil.copyfile(src,tmp)
            if os.name=="nt":
                os.rename(tmp,dst)
            else:
                os.link(tmp,dst)
        finally:
            tmp.unlink(missing_ok=True)
    return [str(out/name) for _,name in files]
