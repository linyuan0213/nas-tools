"""下载管理工具 handler"""

from app.agent.tools.base import ToolResult
from app.agent.tools.context import ToolContext
from app.domain.enums import SearchType


def download_add_link(ctx: ToolContext, link: str, title: str = "", save_path: str = "") -> ToolResult:
    result = ctx.download_service.download_from_link(
        site="",
        enclosure=link,
        title=title or link[:60],
        description="",
        page_url=link,
        size="",
        seeders="",
        uploadvolumefactor="",
        downloadvolumefactor="",
        dl_dir=save_path,
        dl_setting="",
        user_name="agent",
    )
    if getattr(result, "success", False):
        return ToolResult(success=True, data={"message": getattr(result, "message", "已添加下载")})
    return ToolResult(success=False, error=getattr(result, "message", "添加下载失败"))


def media_download(ctx: ToolContext, title: str, media_format: str = "") -> ToolResult:
    meta = ctx.media_service.get_media_info(title=title)
    if not meta or not meta.tmdb_info:
        return ToolResult(success=False, error=f"无法识别《{title}》的媒体信息")
    filters = {"media_format": media_format} if media_format else None
    _, no_exists, total, download_count = ctx.searcher.search_one_media(
        media_info=meta,
        in_from=SearchType.API,
        no_exists={},
        filters=filters or {},
        user_name="agent",
    )
    if download_count:
        return ToolResult(success=True, data={"title": meta.title, "downloaded": download_count})
    if total:
        return ToolResult(success=False, error="搜索到资源但均已下载过或不满足条件")
    return ToolResult(success=False, error="未找到可下载资源", data={"no_exists": bool(no_exists)})


def download_list(ctx: ToolContext, page_size: int = 10) -> ToolResult:
    result = ctx.download_service.get_downloading_with_media_info(page=1, page_size=page_size or 10)
    return ToolResult(success=True, data=result)


def download_control(
    ctx: ToolContext,
    action: str,
    ids: list,
    delete_file: bool = False,
    confirmed: bool = False,
) -> ToolResult:
    if not ids:
        return ToolResult(success=False, error="缺少任务 ids")
    if action == "remove" and not confirmed:
        return ToolResult(
            success=True,
            need_confirm=True,
            data={"action": action, "ids": ids, "delete_file": delete_file, "message": "删除下载任务需确认"},
        )
    core = ctx.downloader_core
    if action == "start":
        core.start_torrents(ids=ids)
    elif action == "stop":
        core.stop_torrents(ids=ids)
    elif action == "recheck":
        core.recheck_torrents(ids=ids)
    elif action == "remove":
        core.delete_torrents(ids=ids, delete_file=delete_file)
    else:
        return ToolResult(success=False, error=f"不支持的操作: {action}")
    return ToolResult(success=True, data={"action": action, "ids": ids, "done": True})


def downloader_status(ctx: ToolContext) -> ToolResult:
    status = ctx.downloader_core.get_status()
    data = status if isinstance(status, (dict, list)) else {"raw": str(status)}
    return ToolResult(success=True, data=data)


HANDLERS = {
    "download_add_link": download_add_link,
    "media_download": media_download,
    "download_list": download_list,
    "download_control": download_control,
    "downloader_status": downloader_status,
}
