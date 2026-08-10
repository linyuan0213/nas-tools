"""订阅管理工具 handler"""

from app.agent.tools.base import ToolResult
from app.agent.tools.context import ToolContext
from app.domain.enums import SearchType
from app.domain.mediatypes import MediaType


def subscribe_add(
    ctx: ToolContext,
    title: str,
    media_type: str = "movie",
    year: int | None = None,
    season: int | None = None,
) -> ToolResult:
    mtype = MediaType.MOVIE if media_type == "movie" else MediaType.TV
    code, msg, _ = ctx.subscribe_service.add_rss_subscribe(
        mtype=mtype,
        name=title,
        year=str(year) if year else None,
        channel="auto",
        season=season,
        state="R",
        in_from=SearchType.API,
    )
    if code == 0:
        return ToolResult(success=True, data={"title": title, "message": msg or "订阅成功"})
    return ToolResult(success=False, error=msg or "订阅失败")


def subscribe_list(ctx: ToolContext, media_type: str | None = None) -> ToolResult:
    data: dict = {}
    if media_type in (None, "movie"):
        data["movies"] = ctx.subscribe_service.get_subscribe_movies() or []
    if media_type in (None, "tv"):
        data["tvs"] = ctx.subscribe_service.get_subscribe_tvs() or []
    return ToolResult(success=True, data=data)


def subscribe_delete(ctx: ToolContext, sub_id: int, media_type: str = "movie") -> ToolResult:
    mtype = MediaType.MOVIE if media_type == "movie" else MediaType.TV
    ctx.subscribe_service.delete_subscribe(mtype=mtype, rssid=sub_id)
    return ToolResult(success=True, data={"sub_id": sub_id, "deleted": True})


HANDLERS = {
    "subscribe_add": subscribe_add,
    "subscribe_list": subscribe_list,
    "subscribe_delete": subscribe_delete,
}
