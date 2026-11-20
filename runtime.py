import json
import os
import subprocess
import sys
import time
from pathlib import Path
from urllib.request import ProxyHandler, Request, build_opener

ROOT = Path(__file__).resolve().parent
CONFIG = ROOT/"settings.json"
SETTINGS = json.loads(CONFIG.read_text(encoding="utf-8-sig")) if CONFIG.exists() else {}
DATA = Path(os.environ.get("SHOTWORK_DATA") or ROOT/"data").resolve()
PORT = int(os.environ.get("SHOTWORK_PORT", SETTINGS.get("port", 18741)))
URL = f"http://127.0.0.1:{PORT}"
DEFAULT_OUT = str(Path(SETTINGS.get("output_directory") or DATA/"成品").resolve())
OPENER = build_opener(ProxyHandler({}))


def api(path, body=None):
    request = Request(URL+path, data=None if body is None else json.dumps(body).encode(),
                      headers={"Content-Type":"application/json","X-Shotwork":"1"})
    with OPENER.open(request, timeout=10) as response:
        return json.load(response)


def ready():
    try:
        info=api("/api/health")
        if info.get("service")!="shotwork" or info.get("data")!=str(DATA):
            raise RuntimeError("端口被其他服务占用，请修改 settings.json 中的 port")
        return True
    except OSError:
        return False


def ensure_service():
    if ready():
        return
    DATA.mkdir(parents=True,exist_ok=True)
    flags = getattr(subprocess,"CREATE_NO_WINDOW",0) | getattr(subprocess,"CREATE_NEW_PROCESS_GROUP",0)
    with (DATA/"service.log").open("ab") as log:
        subprocess.Popen([sys.executable,"-u",str(ROOT/"service.py")],cwd=ROOT,
            stdin=subprocess.DEVNULL,stdout=log,stderr=log,creationflags=flags,
            start_new_session=os.name!="nt")
    for _ in range(120):
        time.sleep(.25)
        if ready():
            return
    raise RuntimeError(f"审核服务未能启动，请查看 {DATA/'service.log'}")
