"""SiteService 单元测试."""

from unittest.mock import MagicMock

import pytest

from app.services.site_service import SiteService


@pytest.fixture
def site_service():
    return SiteService(
        sites=MagicMock(),
        site_user_info=MagicMock(),
        site_conf=MagicMock(),
        indexer_service=MagicMock(),
        site_repo=MagicMock(),
        site_favicon_service=MagicMock(),
        site_resolver=MagicMock(),
        site_cookie=MagicMock(),
        string_utils=MagicMock(),
        site_entity_repo=MagicMock(),
    )


class TestSiteServiceUpdate:
    def test_update_site_rejects_new_site_without_definition(self, site_service):
        site_service._site_engine = MagicMock()
        site_service._site_engine.get_by_name.return_value = None
        result = site_service.update_site(
            {
                "site_name": "UnknownSite",
                "site_pri": "1",
                "site_rssurl": "https://example.com/rss",
                "site_signurl": "https://example.com",
                "site_cookie": "c=1",
                "site_note": "{}",
            }
        )
        assert result.code == 400
        assert "站点定义" in result.msg
        site_service._site_entity_repo.insert.assert_not_called()

    def test_update_site_allows_new_site_with_definition(self, site_service):
        site_service._site_engine = MagicMock()
        site_service._site_engine.get_by_name.return_value = MagicMock(name="DefinedSite")
        result = site_service.update_site(
            {
                "site_name": "DefinedSite",
                "site_pri": "1",
                "site_rssurl": "https://example.com/rss",
                "site_signurl": "https://example.com",
                "site_cookie": "c=1",
                "site_note": "{}",
            }
        )
        assert result.code == 0
        site_service._site_entity_repo.insert.assert_called_once()

    def test_update_site_allows_existing_site_without_definition(self, site_service):
        site_service._site_engine = MagicMock()
        site_service._site_engine.get_by_name.return_value = None
        site_service._site_entity_repo.get_by_id.return_value = MagicMock(name="OldSite")
        result = site_service.update_site(
            {
                "site_id": "1",
                "site_name": "UnknownSite",
                "site_pri": "1",
                "site_rssurl": "https://example.com/rss",
                "site_signurl": "https://example.com",
                "site_cookie": "c=1",
                "site_note": "{}",
            }
        )
        assert result.code == 0
        site_service._site_entity_repo.update.assert_called_once()

    def test_update_site_computes_include_from_switches(self, site_service):
        site_service._site_entity_repo.get_by_id.return_value = MagicMock(name="OldSite")
        site_service.update_site(
            {
                "site_id": "1",
                "site_name": "Test",
                "site_pri": "1",
                "site_rssurl": "https://example.com/rss",
                "site_signurl": "https://example.com",
                "site_cookie": "",
                "site_api_key": "",
                "site_bearer_token": "token",
                "site_headers": "",
                "site_note": "{}",
                "rss_enable": True,
                "brush_enable": True,
                "statistic_enable": True,
            }
        )
        updated = site_service._site_entity_repo.update.call_args[0][0]
        assert updated.rss_uses == "DST"

    def test_update_site_falls_back_to_include_when_switches_missing(self, site_service):
        site_service._site_entity_repo.get_by_id.return_value = MagicMock(name="OldSite")
        site_service.update_site(
            {
                "site_id": "1",
                "site_name": "Test",
                "site_pri": "1",
                "site_rssurl": "https://example.com/rss",
                "site_signurl": "https://example.com",
                "site_cookie": "",
                "site_api_key": "",
                "site_bearer_token": "token",
                "site_headers": "",
                "site_note": "{}",
                "site_include": "DT",
            }
        )
        updated = site_service._site_entity_repo.update.call_args[0][0]
        assert updated.rss_uses == "DT"

    def test_update_site_disabled_switch_removes_include_letter(self, site_service):
        site_service._site_entity_repo.get_by_id.return_value = MagicMock(name="OldSite")
        site_service.update_site(
            {
                "site_id": "1",
                "site_name": "Test",
                "site_pri": "1",
                "site_rssurl": "https://example.com/rss",
                "site_signurl": "https://example.com",
                "site_cookie": "c=1",
                "site_api_key": "",
                "site_bearer_token": "",
                "site_headers": "",
                "site_note": "{}",
                "rss_enable": True,
                "brush_enable": False,
                "statistic_enable": True,
            }
        )
        updated = site_service._site_entity_repo.update.call_args[0][0]
        assert updated.rss_uses == "DT"

    def test_update_site_partial_switch_preserves_other_letters(self, site_service):
        site_service._site_entity_repo.get_by_id.return_value = MagicMock(name="OldSite", rss_uses="ST")
        site_service.update_site(
            {
                "site_id": "1",
                "site_name": "Test",
                "site_pri": "1",
                "site_rssurl": "https://example.com/rss",
                "site_signurl": "https://example.com",
                "site_cookie": "c=1",
                "site_api_key": "",
                "site_bearer_token": "",
                "site_headers": "",
                "site_note": "{}",
                "rss_enable": True,
            }
        )
        updated = site_service._site_entity_repo.update.call_args[0][0]
        assert "D" in updated.rss_uses
        assert "S" in updated.rss_uses
        assert "T" in updated.rss_uses

    def test_update_site_partial_edit_preserves_credentials(self, site_service):
        """部分编辑（只发开关/note，不带 cookie/headers）不得清空存量认证（站点维护修复）"""
        existing = MagicMock(name="OldSite", rss_uses="ST")
        existing.cookie = "c=existing"
        existing.headers = '{"ua": "old"}'
        existing.api_key = "old_key"
        existing.bearer_token = "old_token"
        site_service._site_entity_repo.get_by_id.return_value = existing
        site_service.update_site(
            {
                "site_id": "1",
                "site_name": "Test",
                "site_note": '{"message": true}',
                "rss_enable": True,
            }
        )
        updated = site_service._site_entity_repo.update.call_args[0][0]
        # 未携带的认证字段保留存量
        assert updated.cookie == "c=existing"
        assert updated.headers == '{"ua": "old"}'
        assert updated.api_key == "old_key"
        assert updated.bearer_token == "old_token"
        # 显式提供的 note 生效；rss_uses 保留存量（开关加 D 需 rssurl，未携带则不添加）
        assert updated.note == {"message": True}
        assert updated.rss_uses == "ST"

    def test_update_site_normalizes_note_switches_to_boolean(self, site_service):
        site_service._site_entity_repo.get_by_id.return_value = MagicMock(name="OldSite")
        site_service.update_site(
            {
                "site_id": "1",
                "site_name": "Test",
                "site_pri": "1",
                "site_rssurl": "https://example.com/rss",
                "site_signurl": "https://example.com",
                "site_cookie": "c=1",
                "site_api_key": "",
                "site_bearer_token": "",
                "site_headers": "",
                "site_note": '{"parse": "Y", "message": "N", "chrome": true, "proxy": false, "tag": "Y"}',
                "rss_enable": True,
                "brush_enable": True,
                "statistic_enable": True,
            }
        )
        updated = site_service._site_entity_repo.update.call_args[0][0]
        assert updated.note["parse"] is True
        assert updated.note["message"] is False
        assert updated.note["chrome"] is True
        assert updated.note["proxy"] is False
        assert updated.note["tag"] is True


class TestSiteServiceGet:
    def test_get_site_definitions_returns_sorted_definitions(self, site_service):
        api_site = MagicMock()
        api_site.id = "api1"
        api_site.name = "BApiSite"
        api_site.domain = "https://api.example.com"
        api_site.api = MagicMock()
        api_site.html = None
        api_site.public = False
        api_site.domain_aliases = ["api.example.com"]
        api_site.encoding = "UTF-8"
        api_site.detail_page_url = "/detail/{tid}"

        html_site = MagicMock()
        html_site.id = "html1"
        html_site.name = "AHtmlSite"
        html_site.domain = "https://html.example.com"
        html_site.api = None
        html_site.html = MagicMock()
        html_site.public = True
        html_site.domain_aliases = []
        html_site.encoding = "UTF-8"
        html_site.detail_page_url = "/details.php?id={tid}"

        site_service._site_engine = MagicMock()
        site_service._site_engine.all_sites.return_value = [api_site, html_site]

        defs = site_service.get_site_definitions()
        assert len(defs) == 2
        assert defs[0].name == "AHtmlSite"
        assert defs[0].type == "html"
        assert defs[1].name == "BApiSite"
        assert defs[1].type == "api"

    def test_get_site_returns_cache_with_computed_switches(self, site_service):
        site_service._sites.get_sites.return_value = {
            "id": 1,
            "name": "Test",
            "rss_enable": True,
            "brush_enable": False,
            "statistic_enable": True,
            "parse": True,
            "chrome": False,
            "signurl": "https://example.com",
        }
        site_service._site_conf.get_grap_conf.return_value = {"FREE": True}
        result = site_service.get_site("1")
        assert result.site["rss_enable"] is True
        assert result.site["statistic_enable"] is True
        assert result.site_free is True
