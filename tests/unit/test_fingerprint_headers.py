"""指纹 → 请求头映射与站点配置应用测试."""

from unittest.mock import MagicMock, patch

from app.services.browser_fingerprint_service import (
    apply_fingerprint_to_site_configs,
    is_mobile_fingerprint,
    sync_fingerprint_to_chrome,
)
from app.utils.fingerprint_headers import fingerprint_to_browser_headers, merge_fingerprint_headers
from app.utils.json_utils import JsonUtils

_FP = {
    "ua": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36",
    "ua_brand_version": "Google Chrome 126.0.0.0",
    "ua_full_version": "126.0.6478.127",
    "platform": "Win32",
    "uad_platform": "Windows",
    "uad_arch": "x86",
    "uad_model": "",
    "languages": ["zh-CN", "zh", "en"],
    "touch_points": 0,
}


class TestFingerprintToBrowserHeaders:
    """指纹 → 请求头映射"""

    def test_ua_mapped(self):
        headers = fingerprint_to_browser_headers(_FP, "html")
        assert headers["User-Agent"] == _FP["ua"]

    def test_sec_ch_ua_brand(self):
        headers = fingerprint_to_browser_headers(_FP, "html")
        assert '"Google Chrome";v="126.0.0.0"' in headers["sec-ch-ua"]
        assert len(headers["sec-ch-ua"]) > 0

    def test_platform_mapping(self):
        headers = fingerprint_to_browser_headers(_FP, "html")
        assert headers["sec-ch-ua-platform"] == '"Windows"'
        assert headers["sec-ch-ua-mobile"] == "?0"

    def test_arch_and_language(self):
        headers = fingerprint_to_browser_headers(_FP, "html")
        assert headers["sec-ch-ua-arch"] == '"x86"'
        assert headers["Accept-Language"] == "zh-CN, zh, en"

    def test_api_headers(self):
        headers = fingerprint_to_browser_headers(_FP, "api")
        assert "application/json" in headers["Accept"]
        assert headers["Sec-Fetch-Dest"] == "empty"
        assert headers["Sec-Fetch-Mode"] == "cors"

    def test_html_headers(self):
        headers = fingerprint_to_browser_headers(_FP, "html")
        assert "text/html" in headers["Accept"]
        assert headers["Sec-Fetch-Dest"] == "document"
        assert headers["Sec-Fetch-Mode"] == "navigate"
        assert headers["Upgrade-Insecure-Requests"] == "1"

    def test_platform_fallback_from_navigator(self):
        fp = dict(_FP)
        fp.pop("uad_platform", None)
        fp["platform"] = "MacIntel"
        headers = fingerprint_to_browser_headers(fp, "html")
        assert headers["sec-ch-ua-platform"] == '"macOS"'

    def test_no_ua_returns_empty_user_agent(self):
        headers = fingerprint_to_browser_headers({"platform": "Linux"}, "html")
        assert "User-Agent" not in headers


class TestMergeFingerprintHeaders:
    """高级请求头合并：仅覆盖 UA 相关键，保留自定义键"""

    def test_preserves_custom_headers(self):
        existing = {"Cookie": "a=1", "X-Custom": "keep", "User-Agent": "old"}
        fp_headers = fingerprint_to_browser_headers(_FP, "html")
        merged = merge_fingerprint_headers(existing, fp_headers)
        assert merged["Cookie"] == "a=1"
        assert merged["X-Custom"] == "keep"
        assert merged["User-Agent"] == _FP["ua"]
        assert "sec-ch-ua" in merged

    def test_no_override_auth_keys(self):
        existing = {"Authorization": "Bearer xyz"}
        merged = merge_fingerprint_headers(existing, fingerprint_to_browser_headers(_FP, "api"))
        assert merged["Authorization"] == "Bearer xyz"


class TestApplyFingerprintToSiteConfigs:
    """指纹应用到站点配置（写 CONFIG_SITE，启用状态取自 INDEXER_SITE_CONFIG）"""

    @staticmethod
    def _make_site(name: str, sign_url: str = "", rss_url: str = "", note: dict | None = None, headers=None):
        ent = MagicMock()
        ent.name = name
        ent.sign_url = sign_url
        ent.rss_url = rss_url
        ent.note = note if note is not None else {"ua": "old-ua"}
        ent.headers = headers
        return ent

    def test_updates_site_ua_and_headers(self):
        api_site = self._make_site("Rousi", sign_url="https://rousi.pro", note={"ua": "old-ua"})
        html_site = self._make_site("HDKylin", rss_url="https://www.hdkyl.in", note={"ua": "", "headers": None})
        site_repo = MagicMock()
        site_repo.list_all.return_value = [api_site, html_site]

        indexer_repo = MagicMock()
        indexer_repo.list_enabled_names.return_value = ["Rousi", "HDKylin"]

        engine = MagicMock()
        api_def = MagicMock()
        api_def.api = MagicMock()
        api_def.html = None
        html_def = MagicMock()
        html_def.api = None
        html_def.html = MagicMock()
        engine.get_by_url.side_effect = lambda url: api_def if "rousi" in url else html_def

        with (
            patch("app.services.browser_fingerprint_service.SiteEngine", return_value=engine),
            patch("app.services.browser_fingerprint_service.SiteRepositoryAdapter", return_value=site_repo),
            patch(
                "app.services.browser_fingerprint_service.IndexerSiteConfigRepositoryAdapter",
                return_value=indexer_repo,
            ),
        ):
            count = apply_fingerprint_to_site_configs(_FP)

        assert count == 2
        # API 站点：Accept JSON；UA 仅写入 ua 字段，高级请求头不重复 User-Agent
        api_entity = site_repo.update.call_args_list[0].args[0]
        assert api_entity.note["ua"] == _FP["ua"]
        assert "application/json" in api_entity.note["headers"]["Accept"]
        assert "User-Agent" not in api_entity.note["headers"]
        headers_col = JsonUtils.loads(api_entity.headers)
        assert "User-Agent" not in headers_col
        assert headers_col["Sec-Fetch-Dest"] == "empty"
        assert headers_col["Accept"] == api_entity.note["headers"]["Accept"]
        # HTML 站点：Accept 文档
        html_entity = site_repo.update.call_args_list[1].args[0]
        assert "text/html" in html_entity.note["headers"]["Accept"]
        assert html_entity.note["headers"]["Sec-Fetch-Dest"] == "document"

    def test_skips_disabled_sites(self):
        site = self._make_site("Rousi", sign_url="https://rousi.pro")
        site_repo = MagicMock()
        site_repo.list_all.return_value = [site]
        indexer_repo = MagicMock()
        indexer_repo.list_enabled_names.return_value = []  # 全部禁用
        engine = MagicMock()
        with (
            patch("app.services.browser_fingerprint_service.SiteEngine", return_value=engine),
            patch("app.services.browser_fingerprint_service.SiteRepositoryAdapter", return_value=site_repo),
            patch(
                "app.services.browser_fingerprint_service.IndexerSiteConfigRepositoryAdapter",
                return_value=indexer_repo,
            ),
        ):
            count = apply_fingerprint_to_site_configs(_FP)
        assert count == 0
        site_repo.update.assert_not_called()

    def test_skip_without_ua(self):
        with patch("app.services.browser_fingerprint_service.SiteRepositoryAdapter") as site_repo_cls:
            count = apply_fingerprint_to_site_configs({"platform": "Windows"})
        assert count == 0
        site_repo_cls.assert_not_called()

    def test_preserves_user_custom_headers(self):
        site = self._make_site(
            "Rousi",
            sign_url="https://rousi.pro",
            note={"headers": {"Cookie": "a=1", "Authorization": "Bearer xyz"}},
        )
        site_repo = MagicMock()
        site_repo.list_all.return_value = [site]
        indexer_repo = MagicMock()
        indexer_repo.list_enabled_names.return_value = ["Rousi"]
        engine = MagicMock()
        site_def = MagicMock()
        site_def.api = MagicMock()
        engine.get_by_url.return_value = site_def
        with (
            patch("app.services.browser_fingerprint_service.SiteEngine", return_value=engine),
            patch("app.services.browser_fingerprint_service.SiteRepositoryAdapter", return_value=site_repo),
            patch(
                "app.services.browser_fingerprint_service.IndexerSiteConfigRepositoryAdapter",
                return_value=indexer_repo,
            ),
        ):
            apply_fingerprint_to_site_configs(_FP)
        headers = site.note["headers"]
        assert headers["Cookie"] == "a=1"
        assert headers["Authorization"] == "Bearer xyz"
        # UA 由 ua 字段承载，不重复写入高级请求头
        assert "User-Agent" not in headers
        assert site.note["ua"] == _FP["ua"]

    def test_headers_json_string_parsed(self):
        site = self._make_site("S", sign_url="https://api.example.com", headers='{"Cookie":"a=1"}')
        site_repo = MagicMock()
        site_repo.list_all.return_value = [site]
        indexer_repo = MagicMock()
        indexer_repo.list_enabled_names.return_value = ["S"]
        engine = MagicMock()
        site_def = MagicMock()
        site_def.api = MagicMock()
        engine.get_by_url.return_value = site_def
        with (
            patch("app.services.browser_fingerprint_service.SiteEngine", return_value=engine),
            patch("app.services.browser_fingerprint_service.SiteRepositoryAdapter", return_value=site_repo),
            patch(
                "app.services.browser_fingerprint_service.IndexerSiteConfigRepositoryAdapter",
                return_value=indexer_repo,
            ),
        ):
            apply_fingerprint_to_site_configs(_FP)
        assert site.note["headers"]["Cookie"] == "a=1"
        assert "User-Agent" not in site.note["headers"]
        assert site.note["ua"] == _FP["ua"]


class TestMobileFingerprintGuard:
    """移动端提交保护：不覆盖已有桌面端指纹"""

    _DESKTOP_FP = {
        "ua": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
            "(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36"
        ),
        "platform": "Win32",
        "touch_points": 0,
    }
    _MOBILE_FP = {
        "ua": (
            "Mozilla/5.0 (Linux; Android 14; Pixel 8) AppleWebKit/537.36 "
            "(KHTML, like Gecko) Chrome/126.0.0.0 Mobile Safari/537.36"
        ),
        "platform": "Linux armv8l",
        "touch_points": 5,
    }

    def test_is_mobile_fingerprint(self):
        assert not is_mobile_fingerprint(self._DESKTOP_FP)
        assert is_mobile_fingerprint(self._MOBILE_FP)

    def test_mobile_does_not_overwrite_desktop_fp(self):
        """移动端 + 已存在桌面指纹：不设置默认画像、不应用站点配置"""
        site = MagicMock()
        site.name = "Rousi"
        site.note = {"ua": self._DESKTOP_FP["ua"]}
        site_repo = MagicMock()
        site_repo.list_all.return_value = [site]
        indexer_repo = MagicMock()
        indexer_repo.list_enabled_names.return_value = ["Rousi"]

        with (
            patch("app.services.browser_fingerprint_service.get_chrome_server_url", return_value="http://chrome:9222"),
            patch("app.services.browser_fingerprint_service.httpx2.post") as post,
            patch("app.services.browser_fingerprint_service._set_default_fp_profile_id") as set_default,
            patch("app.services.browser_fingerprint_service.apply_fingerprint_to_site_configs") as apply_fp,
            patch("app.services.browser_fingerprint_service.SiteRepositoryAdapter", return_value=site_repo),
            patch(
                "app.services.browser_fingerprint_service.IndexerSiteConfigRepositoryAdapter",
                return_value=indexer_repo,
            ),
        ):
            result = sync_fingerprint_to_chrome(1, self._MOBILE_FP)

        assert result.profile_id == "user_1_mobile"
        assert result.site_skipped is True
        assert result.site_skip_reason
        post.assert_called_once()
        payload = post.call_args.kwargs["json"]
        assert payload["profile_id"] == "user_1_mobile"
        set_default.assert_not_called()
        apply_fp.assert_not_called()

    def test_desktop_applies_normally(self):
        """桌面端提交正常设置默认画像并应用站点配置"""
        site = MagicMock()
        site.name = "Rousi"
        site.note = {"ua": self._DESKTOP_FP["ua"]}
        site_repo = MagicMock()
        site_repo.list_all.return_value = [site]
        indexer_repo = MagicMock()
        indexer_repo.list_enabled_names.return_value = ["Rousi"]

        with (
            patch("app.services.browser_fingerprint_service.get_chrome_server_url", return_value="http://chrome:9222"),
            patch("app.services.browser_fingerprint_service.httpx2.post") as post,
            patch("app.services.browser_fingerprint_service._set_default_fp_profile_id") as set_default,
            patch("app.services.browser_fingerprint_service.apply_fingerprint_to_site_configs") as apply_fp,
            patch("app.services.browser_fingerprint_service.SiteRepositoryAdapter", return_value=site_repo),
            patch(
                "app.services.browser_fingerprint_service.IndexerSiteConfigRepositoryAdapter",
                return_value=indexer_repo,
            ),
        ):
            result = sync_fingerprint_to_chrome(1, self._DESKTOP_FP)

        assert result.profile_id == "user_1"
        assert result.site_skipped is False
        payload = post.call_args.kwargs["json"]
        assert payload["profile_id"] == "user_1"
        set_default.assert_called_once_with("user_1")
        apply_fp.assert_called_once()

    def test_mobile_first_setup_applies(self):
        """无桌面指纹时移动端首次设置可应用（站点配置为空 UA）"""
        site = MagicMock()
        site.name = "Rousi"
        site.note = {}
        site_repo = MagicMock()
        site_repo.list_all.return_value = [site]
        indexer_repo = MagicMock()
        indexer_repo.list_enabled_names.return_value = ["Rousi"]

        with (
            patch("app.services.browser_fingerprint_service.get_chrome_server_url", return_value="http://chrome:9222"),
            patch("app.services.browser_fingerprint_service.httpx2.post"),
            patch("app.services.browser_fingerprint_service._set_default_fp_profile_id"),
            patch("app.services.browser_fingerprint_service.apply_fingerprint_to_site_configs") as apply_fp,
            patch("app.services.browser_fingerprint_service.SiteRepositoryAdapter", return_value=site_repo),
            patch(
                "app.services.browser_fingerprint_service.IndexerSiteConfigRepositoryAdapter",
                return_value=indexer_repo,
            ),
        ):
            result = sync_fingerprint_to_chrome(1, self._MOBILE_FP)

        assert result.profile_id == "user_1"
        assert result.site_skipped is False
        apply_fp.assert_called_once()
