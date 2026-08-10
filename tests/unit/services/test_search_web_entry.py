"""Web 搜索统一入口（make_web_search_fn）单元测试"""

from unittest.mock import MagicMock, patch

from app.domain.mediatypes import MediaType
from app.services.search_web_entry import make_web_search_fn


class TestMakeWebSearchFn:
    def test_success_when_results(self):
        orchestrator = MagicMock()
        orchestrator.orchestrate.return_value = (None, {}, 5, 0)
        fn = make_web_search_fn(orchestrator, system_config=None)
        code, msg = fn("流浪地球")
        assert code == 0
        assert msg == ""
        ctx = orchestrator.orchestrate.call_args[0][0]
        assert ctx.keyword == "流浪地球"
        assert ctx.persist is True

    def test_no_results(self):
        orchestrator = MagicMock()
        orchestrator.orchestrate.return_value = (None, {}, 0, 0)
        fn = make_web_search_fn(orchestrator, system_config=None)
        code, msg = fn("不存在的资源")
        assert code == 1
        assert "未搜索到" in msg

    def test_tmdbid_resolves_media(self):
        orchestrator = MagicMock()
        orchestrator.orchestrate.return_value = (None, {}, 3, 0)
        fake_media = MagicMock()
        with patch("app.services.search_web_entry.get_mediainfo_from_id", return_value=fake_media) as m:
            fn = make_web_search_fn(orchestrator, system_config=None)
            code, _ = fn("x", tmdbid="12345", media_type=MediaType.MOVIE)
        assert code == 0
        m.assert_called_once()
        ctx = orchestrator.orchestrate.call_args[0][0]
        assert ctx.match_media is fake_media

    def test_tmdbid_unresolved_returns_error(self):
        orchestrator = MagicMock()
        with patch("app.services.search_web_entry.get_mediainfo_from_id", return_value=None):
            fn = make_web_search_fn(orchestrator, system_config=None)
            code, msg = fn("x", tmdbid="99999")
        assert code == -1
        orchestrator.orchestrate.assert_not_called()

    def test_default_sites_applied(self):
        orchestrator = MagicMock()
        orchestrator.orchestrate.return_value = (None, {}, 1, 0)
        system_config = MagicMock()
        system_config.get.return_value = {"search_sites": ["site_a"]}
        fn = make_web_search_fn(orchestrator, system_config=system_config)
        fn("x", media_type=MediaType.TV)
        ctx = orchestrator.orchestrate.call_args[0][0]
        assert ctx.filter_args["site"] == ["site_a"]

    def test_explicit_sites_not_overridden(self):
        orchestrator = MagicMock()
        orchestrator.orchestrate.return_value = (None, {}, 1, 0)
        system_config = MagicMock()
        fn = make_web_search_fn(orchestrator, system_config=system_config)
        fn("x", filters={"site": ["manual"]})
        ctx = orchestrator.orchestrate.call_args[0][0]
        assert ctx.filter_args["site"] == ["manual"]
        system_config.get.assert_not_called()
