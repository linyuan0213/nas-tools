"""媒体库 / 整理 / 调度 / 系统 / 记忆工具 handler"""

from app.agent.tools.base import ToolResult
from app.agent.tools.context import ToolContext
from app.domain.mediatypes import MediaType
from app.schemas.scheduler import RunSchedulerJobRequest


def library_check(ctx: ToolContext, title: str, media_type: str | None = None) -> ToolResult:
    mtype = MediaType.from_string(media_type) if media_type else None
    meta = ctx.media_service.get_media_info(title=title, mtype=mtype)
    if not meta:
        return ToolResult(success=False, error=f"无法识别《{title}》")
    exist_flag, no_exists, messages = ctx.downloader_core.check_exists_medias(meta_info=meta)
    return ToolResult(
        success=True,
        data={
            "title": meta.title,
            "year": meta.year,
            "exists": exist_flag,
            "missing": no_exists or {},
            "messages": messages or [],
        },
    )


def transfer_run(ctx: ToolContext, source_path: str, target_path: str = "", operation: str = "link") -> ToolResult:
    ctx.filetransfer_service.transfer_manually(s_path=source_path, t_path=target_path, operation=operation)
    return ToolResult(success=True, data={"source_path": source_path, "started": True})


def scheduler_list(ctx: ToolContext) -> ToolResult:
    resp = ctx.scheduler_service.get_jobs()
    data = resp.model_dump() if hasattr(resp, "model_dump") else {"raw": str(resp)}
    return ToolResult(success=True, data=data)


def scheduler_run(ctx: ToolContext, job_id: str) -> ToolResult:
    resp = ctx.scheduler_service.run_job(RunSchedulerJobRequest(id=job_id))
    data = resp.model_dump() if hasattr(resp, "model_dump") else {"raw": str(resp)}
    if data.get("code", 0) != 0:
        return ToolResult(success=False, error=data.get("msg", "运行失败"))
    return ToolResult(success=True, data=data)


def system_status(ctx: ToolContext) -> ToolResult:
    info = ctx.system_info_service.get_system_info()
    data = info.model_dump() if hasattr(info, "model_dump") else {"raw": str(info)}
    return ToolResult(success=True, data=data)


def memory_clear(ctx: ToolContext, session_id: str = "", user_id: str = "") -> ToolResult:
    if ctx.conversation_store is None:
        return ToolResult(success=False, error="记忆存储未启用")
    ctx.conversation_store.clear_session(session_id=session_id, user_id=user_id)
    return ToolResult(success=True, data={"cleared": True})


HANDLERS = {
    "library_check": library_check,
    "transfer_run": transfer_run,
    "scheduler_list": scheduler_list,
    "scheduler_run": scheduler_run,
    "system_status": system_status,
    "memory_clear": memory_clear,
}
