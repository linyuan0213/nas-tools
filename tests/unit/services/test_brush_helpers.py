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
