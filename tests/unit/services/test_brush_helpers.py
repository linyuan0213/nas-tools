"""刷流任务 download_torrent 单元测试."""

from unittest.mock import MagicMock, patch

from app.services.brush.helpers import BrushTaskHelper

MODULE = "app.services.brush.helpers"


def _make_helper(download_ret=("qbittorrent", None, "")):
    helper = BrushTaskHelper.__new__(BrushTaskHelper)
    helper._repo = MagicMock()
    helper._downloader = MagicMock()
    helper._sites = MagicMock()
    helper._siteconf = MagicMock()
    helper._message = MagicMock()
    helper._site_engine = MagicMock()
    helper._hr_counts = {}
    helper._downloader.download.return_value = download_ret
    helper._downloader.get_downloader_conf.return_value = {"name": "QB"}
    helper._sites.check_ratelimit.return_value = False
    return helper


def _taskinfo():
    return {
        "id": 1,
        "name": "刷流任务",
        "transfer": False,
        "sendmessage": False,
        "downloader": "1",
        "savepath": "/downloads",
        "label": "",
    }


def _call(helper):
    with patch(f"{MODULE}.meta_info") as mock_meta:
        mock_meta.return_value = MagicMock()
        return helper.download_torrent(
            taskinfo=_taskinfo(),
            rss_rule={},
            site_info={"id": 1, "name": "馒头"},
            title="SDAM-151 2026 1080p DM WEB-DL AAC2.0 H.264-MTeam",
            enclosure="https://api.m-team.io/api/torrent/download?id=12345",
            size=7517684570,
            page_url="https://kp.m-team.cc/detail/12345",
        )


class TestGetTorrentAttrUrl:
    """get_torrent_attr 详情页 URL 重建：RSS 域与主站域分离的站点（M-Team）不得拼错"""

    def _make(self):
        from app.sites.engine import SiteDefinition, SiteEngine

        helper = BrushTaskHelper.__new__(BrushTaskHelper)
        helper._repo = MagicMock()
        helper._downloader = MagicMock()
        helper._sites = MagicMock()
        helper._siteconf = MagicMock()
        helper._siteconf.check_torrent_attr.return_value = {}
        helper._message = MagicMock()
        engine = SiteEngine(definitions_dir="/nonexistent")
        site = SiteDefinition(
            id="mteam",
            name="M-Team",
            domain="kp.m-team.cc",
            domain_aliases=["api.m-team.cc"],
            detail_page_url="/detail/{tid}",
        )
        engine.register(site)
        helper._site_engine = engine
        return helper

    def _site_info(self):
        return {
            "name": "M-Team",
            "ua": "UA",
            "headers": "",
            "proxy": False,
            "cookie": "",
            "api_key": "k",
            "rssurl": "https://rss.m-team.cc/api/rss/fetch?sign=abc&uid=1",
        }

    def test_page_url_keeps_main_domain(self):
        """详情页 page_url 命中站点：详情 URL 用主站域 kp.m-team.cc 而非 RSS 域"""
        helper = self._make()
        url, _ = helper.get_torrent_attr(self._site_info(), "https://kp.m-team.cc/detail/1247728", use_cache=False)
        assert url == "https://kp.m-team.cc/detail/1247728"

    def test_sign_link_falls_back_to_rss_base(self):
        """签名链接不命中站点：按原逻辑落到 rss 基域，属性解析失败由上层收敛"""
        helper = self._make()
        url, _ = helper.get_torrent_attr(
            self._site_info(), "https://rss.m-team.cc/api/rss/dlv2?sign=abc123", use_cache=False
        )
        assert url == "https://rss.m-team.cc/detail/"

    def test_other_site_unchanged(self):
        """RSS 与主站同域的站点：URL 构建结果与旧逻辑一致"""
        from app.sites.engine import SiteDefinition, SiteEngine

        helper = BrushTaskHelper.__new__(BrushTaskHelper)
        helper._siteconf = MagicMock()
        helper._siteconf.check_torrent_attr.return_value = {}
        engine = SiteEngine(definitions_dir="/nonexistent")
        site = SiteDefinition(id="hdsky", name="天空", domain="hdsky.me", detail_page_url="/details.php?id={tid}")
        engine.register(site)
        helper._site_engine = engine
        url, _ = helper.get_torrent_attr(
            {
                "name": "天空",
                "ua": "UA",
                "headers": "",
                "proxy": False,
                "cookie": "",
                "rssurl": "https://hdsky.me/rss.php",
            },
            "https://hdsky.me/download.php?id=999",
            use_cache=False,
        )
        assert url == "https://hdsky.me/details.php?id=999"

    def test_domain_with_scheme_not_double_prefixed(self):
        """domain 自带 scheme 的站点（如观众 https://audiences.me）不得重复拼接协议头"""
        from app.sites.engine import SiteDefinition, SiteEngine

        helper = BrushTaskHelper.__new__(BrushTaskHelper)
        helper._siteconf = MagicMock()
        helper._siteconf.check_torrent_attr.return_value = {}
        engine = SiteEngine(definitions_dir="/nonexistent")
        site = SiteDefinition(
            id="audiences", name="观众", domain="https://audiences.me", detail_page_url="/details.php?id={tid}"
        )
        engine.register(site)
        helper._site_engine = engine
        url, _ = helper.get_torrent_attr(
            {
                "name": "观众",
                "ua": "UA",
                "headers": "",
                "proxy": False,
                "cookie": "",
                "rssurl": "https://audiences.me/rss.php",
            },
            "https://audiences.me/download.php?id=888&passkey=x",
            use_cache=False,
        )
        assert url == "https://audiences.me/details.php?id=888"


class TestDownloadTorrentExistsNoId:
    def test_qb_exists_path_skips_insert(self):
        """qb 种子已存在（download_id=None, 无错误）时跳过入库，不再触发 NOT NULL 约束"""
        helper = _make_helper(download_ret=("1", None, ""))
        assert _call(helper) is True
        helper._repo.insert_brushtask_torrent.assert_not_called()
        helper._repo.add_brushtask_download_count.assert_not_called()
        # 事件日志仍记录（download_id 用空串）
        helper._repo.insert_brush_event.assert_called_once()
        assert helper._repo.insert_brush_event.call_args.kwargs["download_id"] == ""

    def test_normal_path_inserts_with_id(self):
        helper = _make_helper(download_ret=("1", "abc123hash", ""))
        helper._repo.insert_brushtask_torrent.return_value = True
        assert _call(helper) is True
        helper._repo.insert_brushtask_torrent.assert_called_once()
        assert helper._repo.insert_brushtask_torrent.call_args.kwargs["download_id"] == "abc123hash"
        helper._repo.add_brushtask_download_count.assert_called_once()

    def test_add_failure_returns_false(self):
        helper = _make_helper(download_ret=("1", None, "下载器连接失败"))
        assert _call(helper) is False
        helper._repo.insert_brushtask_torrent.assert_not_called()


class TestTorrentAttrCache:
    def test_cache_store_and_get(self):
        from app.services.brush.helpers import cached_torrent_attr, store_torrent_attr

        store_torrent_attr("https://site/1", {"free": True, "hr": False})
        hit = cached_torrent_attr("https://site/1")
        assert hit == {"free": True, "hr": False}

    def test_cache_unknown_not_stored(self):
        from app.services.brush.helpers import cached_torrent_attr, store_torrent_attr

        store_torrent_attr("https://site/2", None)
        assert cached_torrent_attr("https://site/2") is None
