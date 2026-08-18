"""指纹 → 请求头映射与站点配置应用测试."""

from unittest.mock import MagicMock, patch

from app.services.browser_fingerprint_service import apply_fingerprint_to_site_configs
from app.utils.fingerprint_headers import fingerprint_to_browser_headers, merge_fingerprint_headers

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
    """指纹应用到站点配置（区分 API / HTML）"""

    def test_updates_site_ua_and_headers(self):
        api_cfg = MagicMock()
        api_cfg.site_name = "Rousi"
        api_cfg.default_settings = {
            "signurl": "https://rousi.pro",
            "ua": "old-ua",
            "headers": {"Cookie": "a=1"},
        }
        html_cfg = MagicMock()
        html_cfg.site_name = "HDKylin"
        html_cfg.default_settings = {"rssurl": "https://www.hdkyl.in", "ua": "", "headers": None}

        repo = MagicMock()
        repo.list_all.return_value = [api_cfg, html_cfg]

        engine = MagicMock()
        api_def = MagicMock()
        api_def.api = MagicMock()
        api_def.html = None
        html_def = MagicMock()
        html_def.api = None
        html_def.html = MagicMock()
        engine.get_by_url.side_effect = lambda url: api_def if "rousi" in url else html_def

        with (
            patch(
                "app.services.browser_fingerprint_service.IndexerSiteConfigRepositoryAdapter",
                return_value=repo,
            ),
            patch("app.services.browser_fingerprint_service.SiteEngine", return_value=engine),
        ):
            count = apply_fingerprint_to_site_configs(_FP)

        assert count == 2
        # API 站点：Accept JSON
        api_note = repo.update_default_settings.call_args_list[0].args[1]
        assert api_note["ua"] == _FP["ua"]
        assert "application/json" in api_note["headers"]["Accept"]
        assert api_note["headers"]["Cookie"] == "a=1"
        # HTML 站点：Accept 文档
        html_note = repo.update_default_settings.call_args_list[1].args[1]
        assert "text/html" in html_note["headers"]["Accept"]
        assert html_note["headers"]["Sec-Fetch-Dest"] == "document"

    def test_skip_without_ua(self):
        repo = MagicMock()
        with patch(
            "app.services.browser_fingerprint_service.IndexerSiteConfigRepositoryAdapter",
            return_value=repo,
        ):
            count = apply_fingerprint_to_site_configs({"platform": "Windows"})
        assert count == 0
        repo.list_all.assert_not_called()

    def test_headers_json_string_parsed(self):
        cfg = MagicMock()
        cfg.site_name = "S"
        cfg.default_settings = {"signurl": "https://api.example.com", "headers": '{"Cookie":"a=1"}'}
        repo = MagicMock()
        repo.list_all.return_value = [cfg]
        engine = MagicMock()
        site_def = MagicMock()
        site_def.api = MagicMock()
        engine.get_by_url.return_value = site_def
        with (
            patch(
                "app.services.browser_fingerprint_service.IndexerSiteConfigRepositoryAdapter",
                return_value=repo,
            ),
            patch("app.services.browser_fingerprint_service.SiteEngine", return_value=engine),
        ):
            apply_fingerprint_to_site_configs(_FP)
        note = repo.update_default_settings.call_args.args[1]
        assert note["headers"]["Cookie"] == "a=1"
        assert note["headers"]["User-Agent"] == _FP["ua"]
