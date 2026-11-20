"""stdio entry point for any MCP client, independent of its cwd."""
import asyncio
import json
from urllib.error import HTTPError

from mcp.server.fastmcp import FastMCP

from runtime import URL, api, ensure_service

mcp=FastMCP("分镜工坊",instructions="提交本地视频后返回任务编号和审核链接。请用户打开链接选片与复审。程序记录审核并合成，可随时查询任务。")


def call(path,body=None):
    ensure_service()
    try:
        return api(path,body)
    except HTTPError as e:
        raise ValueError(json.load(e).get("error",str(e))) from e


def brief(j):
    keys=("id","label","source","state","selected","error","files","output")
    return {**{k:j[k] for k in keys},"review_url":f"{URL}/review/{j['id']}"}


@mcp.tool()
async def create_video_jobs(sources:list[str],output_directory:str|None=None,
                            titles:list[str]|None=None)->list[dict]:
    """提交一个或多个本地视频绝对路径并返回各自的审核链接。可给同顺序的短标题及成品目录。"""
    rows=await asyncio.to_thread(call,"/api/jobs",dict(sources=sources,output=output_directory,titles=titles))
    return [brief(j) for j in rows]


@mcp.tool()
async def list_video_jobs()->list[dict]:
    """列出本机已有任务、审核阶段、入口与成品路径，便于跨 Agent 接续。"""
    return [brief(j) for j in await asyncio.to_thread(call,"/api/jobs")]


@mcp.tool()
async def get_video_job(job_id:str)->dict:
    """查询任务进度、当前修订、已通过的分镜、审核入口及实际成品路径。"""
    from uuid import UUID
    jid=UUID(job_id).hex
    j=await asyncio.to_thread(call,f"/api/jobs/{jid}")
    return {**brief(j),"shots":[{k:s[k] for k in ("id","revision","approved","start_us","end_us","note")}
                                for s in j["shots"]]}


if __name__=="__main__":
    mcp.run(transport="stdio")
