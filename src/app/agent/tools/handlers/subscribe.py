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


def subscribe_detail(ctx: ToolContext, title: str, tmdb_id: int | None = None) -> ToolResult:
    """查询单个订阅详情（进度/缺集/站点等）"""
    try:
        tvs = ctx.subscribe_service.get_subscribe_tvs() or {}
    except Exception as e:  # noqa: BLE001
        return ToolResult(success=False, error=f"查询订阅详情失败: {e}")
    keyword = (title or "").strip().lower()
    found = []
    for item in tvs.values() if isinstance(tvs, dict) else []:
        if not isinstance(item, dict):
            continue
        name = str(item.get("name") or "").lower()
        if (keyword and keyword in name) or (tmdb_id and int(item.get("tmdbid") or 0) == int(tmdb_id)):
            found.append(
                {
                    "id": item.get("id"),
                    "name": item.get("name"),
                    "year": item.get("year"),
                    "season": item.get("season"),
                    "tmdb_id": item.get("tmdbid"),
                    "total": item.get("total"),
                    "lack": item.get("lack"),
                    "total_ep": item.get("total_ep"),
                    "current_ep": item.get("current_ep"),
                    "state": item.get("state"),
                    "rss_sites": item.get("rss_sites"),
                    "search_sites": item.get("search_sites"),
                    "keyword": item.get("keyword"),
                }
            )
    if not found:
        return ToolResult(success=False, error=f"未找到订阅: {title}")
    return ToolResult(success=True, data={"total": len(found), "items": found})
