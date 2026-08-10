"""媒体域工具 handler 单元测试"""

from unittest.mock import MagicMock

import pytest

from app.agent.tools.context import ToolContext
from app.agent.tools.handlers.media import kb_search, media_detail, media_search


def _data(result) -> dict:
    """窄化 ToolResult.data 为 dict"""
    assert isinstance(result.data, dict)
    return result.data


@pytest.fixture
def ctx():
    return ToolContext(
        search_orchestrator=MagicMock(),
        searcher=MagicMock(),
        download_service=MagicMock(),
        downloader_core=MagicMock(),
        subscribe_service=MagicMock(),
        media_service=MagicMock(),
        media_info_service=MagicMock(),
        filetransfer_service=MagicMock(),
        scheduler_service=MagicMock(),
        system_info_service=MagicMock(),
        event_bus=MagicMock(),
        retriever=None,
        conversation_store=None,
    )


class TestMediaSearch:
    def test_no_results(self, ctx):
        ctx.search_orchestrator.orchestrate.return_value = (None, {}, 0, 0)
        result = media_search(ctx, query="流浪地球")
        assert result.success
        assert _data(result)["total"] == 0
        assert _data(result)["results"] == []

    def test_results_picked(self, ctx):
        ctx.search_orchestrator.orchestrate.return_value = (None, {}, 2, 0)
        row = MagicMock()
        row.TITLE = "流浪地球"
        row.YEAR = "2019"
        row.SITE = "hdsky"
        row.SEEDERS = 100
        row.ES_STRING = ""
        row.TORRENT_NAME = "The.Wandering.Earth.2019.1080p"
        row.SIZE = 1024
        row.PAGEURL = "https://x"
        row.TMDBID = "12345"
        ctx.search_orchestrator.get_results.return_value = [row]
        result = media_search(ctx, query="流浪地球")
        assert result.success
        assert _data(result)["total"] == 2
        item = _data(result)["results"][0]
        assert item["title"] == "流浪地球"
        assert item["site"] == "hdsky"
        assert item["seeders"] == 100

    def test_filter_args_passed(self, ctx):
        ctx.search_orchestrator.orchestrate.return_value = (None, {}, 0, 0)
        media_search(ctx, query="x", site=["s1"], seeders=10)
        sctx = ctx.search_orchestrator.orchestrate.call_args[0][0]
        assert sctx.filter_args == {"site": ["s1"], "seeders": 10}


class TestKbSearch:
    def test_disabled(self, ctx):
        result = kb_search(ctx, query="如何配置")
        assert not result.success

    def test_hit(self, ctx):
        retriever = MagicMock()
        retriever.search.return_value = MagicMock(hit=True, citations=[{"source": "docs/a.md", "snippet": "内容"}])
        ctx = MagicMock(wraps=ctx)
        ctx.retriever = retriever
        result = kb_search(ctx, query="如何配置下载器")
        assert result.success
        assert _data(result)["hit"]
        assert _data(result)["citations"][0]["source"] == "docs/a.md"


class TestMediaDetail:
    def test_model_dump(self, ctx):
        dto = MagicMock()
        dto.model_dump.return_value = {"title": "流浪地球"}
        ctx.media_info_service.get_media_info_detail.return_value = dto
        result = media_detail(ctx, tmdb_id=12345, media_type="movie")
        assert result.success
        assert _data(result)["title"] == "流浪地球"

    def test_not_found(self, ctx):
        ctx.media_info_service.get_media_info_detail.return_value = None
        result = media_detail(ctx, tmdb_id=1, media_type="movie")
        assert not result.success
