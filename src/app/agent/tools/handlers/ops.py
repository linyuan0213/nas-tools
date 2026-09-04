"""媒体库 / 整理 / 调度 / 系统 / 记忆工具 handler"""

from app.agent.pydantic_agent import PydanticChatAgent
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


def stats_summary(ctx: ToolContext) -> ToolResult:
    """系统数据总览：媒体库规模 / 下载记录 / 站点数量 / 系统运行信息"""
    summary: dict = {}
    # 媒体库规模
    try:
        if ctx.media_library_service is not None:
            count = ctx.media_library_service.get_media_count()
            if count:
                summary["library"] = {
                    "movie": count.get("Movie"),
                    "series": count.get("Series"),
                    "episodes": count.get("Episodes"),
                }
    except Exception as e:  # noqa: BLE001
        summary.setdefault("warnings", []).append(f"媒体库统计失败: {e}")
    # 下载记录
    try:
        history = ctx.downloader_core.get_download_history(num=200) or []
        summary["download"] = {"total": len(history)}
    except Exception as e:  # noqa: BLE001
        summary.setdefault("warnings", []).append(f"下载记录统计失败: {e}")
    # 站点数量
    try:
        if ctx.site_service is not None:
            sites = ctx.site_service.get_sites() or []
            summary["sites"] = {
                "total": len(sites),
                "enabled": sum(1 for s in sites if isinstance(s, dict) and s.get("enabled")),
            }
    except Exception as e:  # noqa: BLE001
        summary.setdefault("warnings", []).append(f"站点统计失败: {e}")
    # 系统运行信息
    try:
        info = ctx.system_info_service.get_system_info()
        if hasattr(info, "model_dump"):
            data = info.model_dump()
        elif hasattr(info, "__dict__"):
            data = dict(vars(info))
        else:
            data = {}
        summary["system"] = {
            "version": data.get("version"),
            "uptime": data.get("uptime"),
            "memory_mb": data.get("memory_mb"),
        }
    except Exception as e:  # noqa: BLE001
        summary.setdefault("warnings", []).append(f"系统信息获取失败: {e}")
    return ToolResult(success=True, data=summary)


def transfer_history(ctx: ToolContext, keyword: str = "", page: int = 1, page_num: int = 20) -> ToolResult:
    """查询媒体转移/入库历史"""
    try:
        dto = ctx.transfer_history_service.get_transfer_history_page(
            search_str=keyword or "", page=page or 1, page_num=page_num or 20
        )
    except Exception as e:  # noqa: BLE001
        return ToolResult(success=False, error=f"查询转移历史失败: {e}")
    result = getattr(dto, "result", None) or []
    items = []
    for rec in result:
        if not isinstance(rec, dict):
            continue
        items.append(
            {
                "title": rec.get("title") or rec.get("TITLE"),
                "year": rec.get("year") or rec.get("YEAR"),
                "season_episode": rec.get("season_episode") or rec.get("SE"),
                "dest_filename": rec.get("dest_filename") or rec.get("DEST_FILENAME"),
                "date": rec.get("date") or rec.get("DATE"),
            }
        )
    return ToolResult(
        success=True,
        data={"total": getattr(dto, "total", len(items)), "items": items},
    )


def kb_status(ctx: ToolContext) -> ToolResult:
    """查询知识库状态（各命名空间索引块数）"""
    if ctx.knowledge_ingestor is None:
        return ToolResult(success=False, error="Agent RAG 未启用")
    try:
        return ToolResult(success=True, data={"namespaces": ctx.knowledge_ingestor.status()})
    except Exception as e:  # noqa: BLE001
        return ToolResult(success=False, error=f"查询知识库状态失败: {e}")


def indexer_status(ctx: ToolContext) -> ToolResult:
    """查询索引器统计"""
    try:
        dtos, _ = ctx.indexer_service.get_indexer_statistics()
    except Exception as e:  # noqa: BLE001
        return ToolResult(success=False, error=f"查询索引器统计失败: {e}")
    items = []
    for d in dtos or []:
        data = d.model_dump() if hasattr(d, "model_dump") else {}
        items.append(
            {
                "name": data.get("name"),
                "total": data.get("total"),
                "fail": data.get("fail"),
                "success": data.get("success"),
                "avg": data.get("avg"),
            }
        )
    return ToolResult(success=True, data={"total": len(items), "items": items})


def torrent_remover_status(ctx: ToolContext) -> ToolResult:
    """查询自动删种任务列表"""
    try:
        svc = ctx.torrent_remover_service
        repo = getattr(svc, "_repo", None)
        if hasattr(svc, "get_tasks"):
            tasks = svc.get_tasks()
        elif repo is not None and hasattr(repo, "get_tasks"):
            tasks = repo.get_tasks()
        else:
            return ToolResult(success=False, error="删种任务服务不可用")
    except Exception as e:  # noqa: BLE001
        return ToolResult(success=False, error=f"查询删种任务失败: {e}")
    if not isinstance(tasks, list):
        tasks = []
    items = [
        {
            "id": t.get("id"),
            "name": t.get("name"),
            "site": t.get("site"),
            "state": t.get("state"),
        }
        for t in tasks
        if isinstance(t, dict)
    ]
    return ToolResult(success=True, data={"total": len(items), "items": items})


def storage_status(ctx: ToolContext) -> ToolResult:
    """查询存储后端列表"""
    try:
        backends = ctx.storage_backend_service.list_backends()
    except Exception as e:  # noqa: BLE001
        return ToolResult(success=False, error=f"查询存储后端失败: {e}")
    items = [
        {
            "id": b.get("id"),
            "name": b.get("name"),
            "type": b.get("type"),
            "enabled": b.get("enabled"),
        }
        for b in (backends or [])
        if isinstance(b, dict)
    ]
    return ToolResult(success=True, data={"total": len(items), "items": items})


def memory_forget(ctx: ToolContext, text: str, session_id: str = "", user_id: str = "") -> ToolResult:
    if ctx.semantic_memory is None:
        return ToolResult(success=False, error="长程语义记忆未启用")
    # 命名空间与抽取保持一致：优先 user_id/session_id，匿名回退 anon（与抽取端一致）
    uid = user_id or session_id or "anon"
    deleted = ctx.semantic_memory.forget(uid, text)
    return ToolResult(
        success=True,
        data={
            "deleted": deleted,
            "message": "已删除该偏好记忆" if deleted else "未找到匹配的偏好记忆",
        },
    )


def memory_clear(ctx: ToolContext, session_id: str = "", user_id: str = "", channel: str = "") -> ToolResult:
    if ctx.conversation_store is None:
        return ToolResult(success=False, error="记忆存储未启用")
    target_channel = channel or "web"
    ctx.conversation_store.clear_session(
        session_id=session_id, user_id=user_id or session_id or "anon", channel=target_channel
    )
    # 同时删除会话 checkpoint（pydantic-ai 消息历史快照），否则下一轮仍会恢复旧上下文
    try:
        path = PydanticChatAgent._checkpoint_path(session_id, user_id or session_id or "anon", target_channel)
        if path.exists():
            path.unlink()
    except Exception as e:  # noqa: BLE001
        return ToolResult(success=False, error=f"清理会话失败: {e}")
    return ToolResult(success=True, data={"cleared": True})
