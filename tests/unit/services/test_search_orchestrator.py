"""SearchOrchestrator 搜索进度失败站点汇总测试"""

from unittest.mock import MagicMock

from app.services.search_orchestrator import SearchOrchestrator


def _make_orchestrator() -> SearchOrchestrator:
    return SearchOrchestrator(
        searcher=MagicMock(),
        search_repo=MagicMock(),
        download_repo=MagicMock(),
        downloader=MagicMock(),
        media_service=MagicMock(),
        message=MagicMock(),
        progress_helper=MagicMock(),
        event_bus=MagicMock(),
        intent_resolver=None,
    )


def _set_progress(orch: SearchOrchestrator, detail: dict) -> None:
    orch._progress.get_process = MagicMock(return_value=detail)


class TestFailedSitesSummary:
    def test_no_sites_returns_empty(self):
        orch = _make_orchestrator()
        _set_progress(orch, {"value": 100, "text": "x"})
        assert orch._failed_sites_summary("search:s1") == ""

    def test_no_failed_sites_returns_empty(self):
        orch = _make_orchestrator()
        _set_progress(
            orch,
            {
                "sites": [
                    {"name": "站点A", "status": "ok", "count": 3, "error": ""},
                ]
            },
        )
        assert orch._failed_sites_summary("search:s1") == ""

    def test_mixed_sites_summarizes_failures(self):
        orch = _make_orchestrator()
        _set_progress(
            orch,
            {
                "sites": [
                    {"name": "站点A", "status": "ok", "count": 3, "error": ""},
                    {"name": "站点B", "status": "error", "count": 0, "error": "超时"},
                    {"name": "站点C", "status": "timeout", "count": 0, "error": "超过 10s"},
                ]
            },
        )
        summary = orch._failed_sites_summary("search:s1")
        assert "站点B(超时)" in summary
        assert "站点C(超过 10s)" in summary
        assert "站点A" not in summary

    def test_failed_site_without_error_uses_status(self):
        orch = _make_orchestrator()
        _set_progress(
            orch,
            {
                "sites": [
                    {"name": "站点D", "status": "error", "count": 0, "error": ""},
                ]
            },
        )
        assert "站点D(error)" in orch._failed_sites_summary("search:s1")


class TestOrchestrateFinalText:
    def test_final_text_includes_failed_sites(self):
        """orchestrate 结束时 progress 文本带失败站点汇总"""
        from unittest.mock import MagicMock, patch

        from app.services.search_context import SearchContext

        orch = _make_orchestrator()
        ctx = MagicMock(spec=SearchContext)
        ctx.session_id = "s1"
        ctx.keyword = "测试"
        ctx.no_exists = {}
        ctx.user_name = ""
        ctx.match_media = None
        ctx.persist = False
        ctx.auto_download = False
        ctx.user_id = None
        ctx.ident_flag = True

        orch._searcher.search_one_media = MagicMock(return_value=([MagicMock()], {}, None, None))
        orch._progress = MagicMock()
        orch._progress.get_process.return_value = {
            "sites": [
                {"name": "站点B", "status": "error", "count": 0, "error": "超时"},
            ]
        }
        with (
            patch("app.services.search_orchestrator.SearchResultDeduplicator.deduplicate", return_value=[MagicMock()]),
            patch("app.services.search_orchestrator.SearchResultProcessor.sort_results", side_effect=lambda x, **kw: x),
            patch.object(orch, "_enrich_and_persist"),
            patch.object(orch, "_filter_downloaded", return_value=[]),
        ):
            orch.orchestrate(ctx)

        calls = [str(c) for c in orch._progress.update.call_args_list]
        final = [c for c in calls if "搜索完成" in c]
        assert final, "应有搜索完成的 progress update"
        assert "站点B(超时)" in final[-1]
