import asyncio
import socket
from contextlib import asynccontextmanager

import uvicorn
from starlette.applications import Starlette
from starlette.middleware.trustedhost import TrustedHostMiddleware
from starlette.responses import FileResponse, JSONResponse
from starlette.routing import Route

import jobs
from runtime import DATA, DEFAULT_OUT, PORT, ROOT, URL


@asynccontextmanager
async def startup(app):
    with jobs.LOCK:
        for job in jobs.all_jobs():
            jobs.schedule(job)
    yield


async def health(req):
    return JSONResponse(dict(service="shotwork",data=str(DATA),output=DEFAULT_OUT))


async def collection(req):
    if req.method=="GET":
        return JSONResponse([jobs.summary(j) for j in jobs.all_jobs()])
    data=await req.json()
    created=await asyncio.to_thread(jobs.create,data["sources"],data.get("output"),data.get("titles"))
    return JSONResponse(created,status_code=201)


async def job(req):
    jid=req.path_params["jid"]
    if req.method=="GET":
        return JSONResponse(jobs.get(jid))
    return JSONResponse(await asyncio.to_thread(jobs.action,jid,await req.json()))


async def asset(req):
    jid=req.path_params["jid"]
    j=jobs.get(jid)
    name=req.path_params["name"]
    for s in j["shots"]:
        raw=f"{s['id']}-raw.mp4"
        clean=f"{s['id']}-r{s['revision']}.mp4"
        if name==raw or (name==clean and s["sha256"]):
            return FileResponse(DATA/"jobs"/jid/name,media_type="video/mp4")
    if name=="master.mp4" and j["state"]=="done":
        return FileResponse(DATA/"jobs"/jid/name,media_type="video/mp4")
    raise KeyError("未找到预览视频")


async def page(req):
    return FileResponse(ROOT/"web"/"index.html",media_type="text/html")


async def static(req):
    name=req.path_params["name"]
    if name not in {"ui.js","ui.css"}:
        raise KeyError("未找到文件")
    return FileResponse(ROOT/"web"/name)


async def failure(req,exc):
    return JSONResponse({"error":str(exc)},status_code=404 if isinstance(exc,KeyError) else 400)


app=Starlette(routes=[
    Route("/",page), Route("/review/{jid}",page), Route("/static/{name}",static),
    Route("/api/health",health),Route("/api/jobs",collection,methods=["GET","POST"]),
    Route("/api/jobs/{jid}",job,methods=["GET","POST"]),Route("/media/{jid}/{name}",asset)
],lifespan=startup,exception_handlers={ValueError:failure,KeyError:failure,TypeError:failure})
app.add_middleware(TrustedHostMiddleware,allowed_hosts=["127.0.0.1","localhost"])


@app.middleware("http")
async def local_only(req,call_next):
    if req.method=="POST":
        origin=req.headers.get("origin")
        if (req.headers.get("x-shotwork")!="1" or origin not in (None,URL,f"http://localhost:{PORT}")
                or req.headers.get("sec-fetch-site")=="cross-site"):
            return JSONResponse({"error":"请从本地审核页提交"},status_code=403)
    response=await call_next(req)
    response.headers["X-Frame-Options"]="DENY"
    response.headers["Referrer-Policy"]="no-referrer"
    response.headers["Cross-Origin-Resource-Policy"]="same-origin"
    if not req.url.path.startswith("/media/"):
        response.headers["Cache-Control"]="no-store"
    return response


if __name__=="__main__":
    # Acquire the port before lifespan startup can resume any durable work.
    with socket.socket(socket.AF_INET,socket.SOCK_STREAM) as listener:
        if hasattr(socket,"SO_EXCLUSIVEADDRUSE"):
            listener.setsockopt(socket.SOL_SOCKET,socket.SO_EXCLUSIVEADDRUSE,1)
        listener.bind(("127.0.0.1",PORT))
        server=uvicorn.Server(uvicorn.Config(app,host="127.0.0.1",port=PORT,access_log=False))
        server.run(sockets=[listener])
