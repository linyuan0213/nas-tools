"""媒体检索与知识库工具 handler"""

from uuid import uuid4

from app.agent.tools.base import ToolResult
from app.agent.tools.context import ToolContext
from app.domain.enums import SearchType
from app.services.search_context import SearchContext

_RESULT_FIELDS = {
    "TITLE": "title",
    "YEAR": "year",
    "ES_STRING": "season_episode",
    "TORRENT_NAME": "torrent_name",
    "SITE": "site",
    "SEEDERS": "seeders",
    "SIZE": "size",
    "PAGEURL": "page_url",
    "TMDBID": "tmdb_id",
}


def _pick_result(row) -> dict:
    """搜索结果行（ORM 对象或 dict）→ 精简 dict"""
    item = {}
    for attr, key in _RESULT_FIELDS.items():
        value = row.get(attr) if isinstance(row, dict) else getattr(row, attr, None)
        if value is not None:
            item[key] = value
    return item


def media_search(ctx: ToolContext, query: str, site: list | None = None, seeders: int | None = None) -> ToolResult:
    """统一搜索入口：意图识别 → TMDB → 并发搜索 → 去重排序入库（SearchOrchestrator）"""
    filter_args: dict = {}
    if site:
        filter_args["site"] = site
    if seeders:
        filter_args["seeders"] = seeders
    session_id = f"agent:{uuid4().hex[:12]}"
    sctx = SearchContext(
        keyword=query,
        session_id=session_id,
        search_type=SearchType.WEB,
        filter_args=filter_args or None,
        persist=True,
        auto_download=False,
    )
    _, _, total, _ = ctx.search_orchestrator.orchestrate(sctx)
    if not total:
        return ToolResult(success=True, data={"total": 0, "results": []})
    rows = ctx.search_orchestrator.get_results(session_id)
    return ToolResult(success=True, data={"total": total, "results": [_pick_result(r) for r in rows[:10]]})


def media_detail(ctx: ToolContext, tmdb_id: int, media_type: str) -> ToolResult:
    result = ctx.media_info_service.get_media_info_detail(
        mediaid=tmdb_id, mtype=media_type, title="", year="", page="", rssid=None
    )
    if result is None:
        return ToolResult(success=False, error="未查询到媒体信息")
    data = result.model_dump() if hasattr(result, "model_dump") else {"raw": str(result)}
    return ToolResult(success=True, data=data)


def kb_search(ctx: ToolContext, query: str, namespace: str | None = None) -> ToolResult:
    if ctx.retriever is None:
        return ToolResult(success=False, error="知识库未启用（agent.enabled 或 embedding 未配置）")
    result = ctx.retriever.search(query, namespace)
    if not result.hit:
        return ToolResult(success=True, data={"hit": False, "citations": []})
    return ToolResult(success=True, data={"hit": True, "citations": result.citations})
