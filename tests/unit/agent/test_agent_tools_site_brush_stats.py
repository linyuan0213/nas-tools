"""站点 / 刷流 / 订阅详情 / 数据总览 agent 工具测试"""

from typing import cast

from app.agent.tools.context import ToolContext
from app.agent.tools.handlers.brush import brush_status
from app.agent.tools.handlers.ops import (
    indexer_status,
    kb_status,
    stats_summary,
    storage_status,
    torrent_remover_status,
    transfer_history,
)
from app.agent.tools.handlers.rss_task import rss_task_list
from app.agent.tools.handlers.site import site_status, site_update_cookie
from app.agent.tools.handlers.subscribe import subscribe_detail


class _SiteService:
    def __init__(self, sites):
        self.sites = sites
        self.updated = []

    def get_sites(self, rss=False, brush=False, statistic=False, basic=False, source=None):
        return self.sites

    def update_site_cookie_ua(self, siteid, cookie, ua):
        self.updated.append((siteid, cookie))


class _BrushService:
    def __init__(self, tasks):
        self.tasks = tasks

    def get_tasks(self):
        return self.tasks


class _SubscribeService:
    def __init__(self, tvs):
        self.tvs = tvs

    def get_subscribe_tvs(self, rid=None, state=None):
        return self.tvs


class _Downloader:
    def get_download_history(self, date=None, hid=None, num=30, page=1):
        return [object(), object(), object()]


class _SystemInfo:
    @staticmethod
    def get_system_info():
        return type("I", (), {"model_dump": lambda self: {"version": "4.6.3", "uptime": "3天", "memory_mb": 512.0}})()


class _Library:
    def get_media_count(self):
        return {"Movie": "98", "Series": "362", "Episodes": "4821"}


def _ctx(
    site=None,
    brush=None,
    sub=None,
    lib=None,
    dl=None,
    sysinfo=None,
    transfer=None,
    rss=None,
    ingestor=None,
    indexer=None,
    remover=None,
    storage=None,
):
    return cast(
        ToolContext,
        ToolContext(
            search_orchestrator=None,
            searcher=None,
            download_service=None,
            downloader_core=dl,
            subscribe_service=sub,
            media_service=None,
            media_info_service=None,
            filetransfer_service=None,
            scheduler_service=None,
            system_info_service=sysinfo,
            event_bus=None,
            site_service=site,
            brush_service=brush,
            media_library_service=lib,
            transfer_history_service=transfer,
            user_rss_service=rss,
            knowledge_ingestor=ingestor,
            indexer_service=indexer,
            torrent_remover_service=remover,
            storage_backend_service=storage,
        ),
    )


def _data(result) -> dict:
    assert isinstance(result.data, dict)
    return result.data


class TestSiteStatus:
    def test_site_status_summary(self):
        sites = [
            {
                "id": 1,
                "name": "憨憨",
                "enabled": True,
                "rss_enable": True,
                "statistic_enable": True,
                "brush_enable": False,
                "cookie": "abc",
            },
            {"id": 2, "name": "猫站", "enabled": True, "rss_enable": True, "statistic_enable": False, "api_key": "k"},
            {"id": 3, "name": "关闭站", "enabled": False, "rss_enable": False, "statistic_enable": False},
        ]
        result = site_status(_ctx(site=_SiteService(sites)))
        assert result.success
        assert _data(result)["total"] == 3
        assert _data(result)["enabled"] == 2
        assert _data(result)["items"][0]["name"] == "憨憨"
        assert _data(result)["items"][0]["has_auth"] is True
        assert _data(result)["items"][2]["has_auth"] is False


class TestBrushStatus:
    def test_brush_status_list(self):
        tasks = [{"id": 1, "name": "奶站刷流", "site": "cat", "state": "running", "free": 0}]
        result = brush_status(_ctx(brush=_BrushService(tasks)))
        assert result.success
        assert _data(result)["total"] == 1
        assert _data(result)["items"][0]["name"] == "奶站刷流"


class TestSubscribeDetail:
    _TVS = {
        "1": {
            "id": 1,
            "name": "尼古喵喵",
            "year": "2026",
            "season": "S01",
            "tmdbid": 312949,
            "total": 12,
            "lack": 5,
            "total_ep": 12,
            "current_ep": 7,
            "state": "R",
        },
        "2": {
            "id": 2,
            "name": "无职转生",
            "year": "2021",
            "season": "S03",
            "tmdbid": 2,
            "total": 14,
            "lack": 2,
            "total_ep": 14,
            "current_ep": 12,
            "state": "R",
        },
    }

    def test_subscribe_detail_by_title(self):
        result = subscribe_detail(_ctx(sub=_SubscribeService(dict(self._TVS))), title="尼古喵喵")
        assert result.success
        assert _data(result)["total"] == 1
        assert _data(result)["items"][0]["lack"] == 5

    def test_subscribe_detail_by_tmdb(self):
        result = subscribe_detail(_ctx(sub=_SubscribeService(dict(self._TVS))), title="x", tmdb_id=312949)
        assert result.success
        assert _data(result)["items"][0]["name"] == "尼古喵喵"

    def test_subscribe_detail_not_found(self):
        result = subscribe_detail(_ctx(sub=_SubscribeService(dict(self._TVS))), title="不存在")
        assert not result.success
        assert "未找到" in result.error


class TestStatsSummary:
    def test_stats_summary(self):
        result = stats_summary(
            _ctx(
                site=_SiteService([{"id": 1, "name": "A", "enabled": True}, {"id": 2, "name": "B", "enabled": False}]),
                lib=_Library(),
                dl=_Downloader(),
                sysinfo=_SystemInfo(),
            )
        )
        assert result.success
        data = _data(result)
        assert data["library"]["movie"] == "98"
        assert data["download"]["total"] == 3
        assert data["sites"] == {"total": 2, "enabled": 1}
        assert data["system"]["version"] == "4.6.3"


class TestTransferHistory:
    def test_transfer_history(self):
        svc = type(
            "S",
            (),
            {
                "get_transfer_history_page": lambda self, search_str="", page=1, page_num=20: type(
                    "D",
                    (),
                    {
                        "total": 2,
                        "result": [
                            {
                                "title": "流浪地球",
                                "season_episode": "S01E01",
                                "dest_filename": "a.mkv",
                                "date": "2026-08-01",
                            },
                            {
                                "title": "电锯人",
                                "season_episode": "S01E07",
                                "dest_filename": "b.mkv",
                                "date": "2026-08-02",
                            },
                        ],
                    },
                )(),
            },
        )()
        result = transfer_history(_ctx(transfer=svc), keyword="")
        assert result.success
        assert _data(result)["total"] == 2
        assert _data(result)["items"][0]["title"] == "流浪地球"


class TestRssTaskList:
    def test_rss_task_list(self):
        svc = type(
            "S",
            (),
            {
                "get_tasks": lambda self: [
                    {"id": 1, "name": "追番RSS", "address": ["https://rss/1"], "interval": 30, "state": "R"},
                ]
            },
        )()
        result = rss_task_list(_ctx(rss=svc))
        assert result.success
        assert _data(result)["total"] == 1
        assert _data(result)["items"][0]["name"] == "追番RSS"


class TestSiteUpdateCookie:
    def test_requires_confirm(self):
        result = site_update_cookie(_ctx(site=_SiteService([])), site_id=1, cookie="abc")
        assert result.need_confirm

    def test_confirm_updates(self):
        svc = _SiteService([])
        result = site_update_cookie(_ctx(site=svc), site_id=1, cookie="abc", confirmed=True)
        assert result.success

    def test_empty_cookie_rejected(self):
        result = site_update_cookie(_ctx(site=_SiteService([])), site_id=1, cookie="", confirmed=True)
        assert not result.success


class TestKbStatus:
    def test_kb_status(self):
        ingestor = type("I", (), {"status": lambda self: {"docs": 100}})()
        result = kb_status(_ctx(ingestor=ingestor))
        assert result.success
        assert _data(result)["namespaces"] == {"docs": 100}

    def test_kb_status_not_enabled(self):
        result = kb_status(_ctx(ingestor=None))
        assert not result.success
        assert "未启用" in result.error


class TestIndexerStatus:
    def test_indexer_status(self):
        dto = type(
            "D", (), {"model_dump": lambda self: {"name": "猫站", "total": 10, "fail": 2, "success": 8, "avg": 1.5}}
        )()  # noqa: E501
        svc = type("S", (), {"get_indexer_statistics": lambda self: ([dto], [])})()
        result = indexer_status(_ctx(indexer=svc))
        assert result.success
        assert _data(result)["total"] == 1
        assert _data(result)["items"][0]["name"] == "猫站"
        assert _data(result)["items"][0]["fail"] == 2


class TestTorrentRemoverStatus:
    def test_torrent_remover_status(self):
        svc = type("S", (), {"get_tasks": lambda self: [{"id": 1, "name": "删种规则A", "site": "cat", "state": "R"}]})()
        result = torrent_remover_status(_ctx(remover=svc))
        assert result.success
        assert _data(result)["total"] == 1
        assert _data(result)["items"][0]["name"] == "删种规则A"


class TestStorageStatus:
    def test_storage_status(self):
        svc = type(
            "S", (), {"list_backends": lambda self: [{"id": 1, "name": "主存储", "type": "local", "enabled": 1}]}
        )()  # noqa: E501
        result = storage_status(_ctx(storage=svc))
        assert result.success
        assert _data(result)["total"] == 1
        assert _data(result)["items"][0]["type"] == "local"
