"""SiteConfigUpdater 站点配置更新源 URL 解析单元测试."""

from app.core.constants import SITES_DATA_URL
from app.services.site_config_updater import SiteConfigUpdater


class TestSiteConfigUpdaterUrlResolution:
    def test_default_url_falls_back_to_constant(self, tmp_path):
        updater = SiteConfigUpdater(config_dir=str(tmp_path))
        assert updater._release_api_url == SITES_DATA_URL
        assert updater._repo_base == "https://github.com/linyuan0213/nexus-media-sites"

    def test_constructor_url_override(self, tmp_path):
        url = "https://api.github.com/repos/linyuan0213/nexus-media-sites/releases/latest"
        updater = SiteConfigUpdater(config_dir=str(tmp_path), release_api_url=url)
        assert updater._release_api_url == url
        assert updater._repo_base == "https://github.com/linyuan0213/nexus-media-sites"

    def test_non_github_url_has_no_repo_base(self, tmp_path):
        url = "https://example.com/custom/releases/latest"
        updater = SiteConfigUpdater(config_dir=str(tmp_path), release_api_url=url)
        assert updater._release_api_url == url
        assert updater._repo_base == ""

    def test_extract_repo_base(self, tmp_path):
        assert (
            SiteConfigUpdater._extract_repo_base("https://api.github.com/repos/foo/bar/releases/latest")
            == "https://github.com/foo/bar"
        )
        assert SiteConfigUpdater._extract_repo_base("https://example.com/x") == ""


class TestSiteConfigUpdaterFindAsset:
    def test_asset_url_from_release_info(self, tmp_path):
        updater = SiteConfigUpdater(config_dir=str(tmp_path))
        release = {"assets": [{"name": "sites-config.zip", "browser_download_url": "https://cdn/zip"}]}
        assert updater._find_asset_url(release) == "https://cdn/zip"

    def test_fallback_download_url_uses_repo_base(self, tmp_path):
        updater = SiteConfigUpdater(config_dir=str(tmp_path))
        release = {"tag_name": "v20260827", "assets": []}
        assert updater._find_asset_url(release) == (
            "https://github.com/linyuan0213/nexus-media-sites/releases/download/v20260827/sites-config.zip"
        )

    def test_no_repo_base_and_no_assets_returns_none(self, tmp_path):
        updater = SiteConfigUpdater(config_dir=str(tmp_path), release_api_url="https://example.com/releases/latest")
        assert updater._find_asset_url({"tag_name": "v1", "assets": []}) is None

    def test_no_assets_no_tag_returns_none(self, tmp_path):
        updater = SiteConfigUpdater(config_dir=str(tmp_path))
        assert updater._find_asset_url({"assets": []}) is None


class TestSiteConfigUpdaterConfigDir:
    def test_default_config_dir_uses_settings_path(self, tmp_path, monkeypatch):
        import types

        import app.services.site_config_updater as module

        monkeypatch.setattr(module, "settings", types.SimpleNamespace(config_path=str(tmp_path)))
        updater = SiteConfigUpdater()
        assert updater._sites_dir == str(tmp_path / "sites")

    def test_version_file_roundtrip(self, tmp_path):
        updater = SiteConfigUpdater(config_dir=str(tmp_path))
        updater._write_local_version("v1.0")
        assert updater._read_local_version() == "v1.0"
