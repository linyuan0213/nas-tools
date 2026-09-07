"""刷流删种生命周期接线测试 — 验证 pending_time（等待时间）取进种时长而非 iatime"""

from typing import cast

from app.domain.entities.brush import BrushTaskState
from app.message import Message
from app.schemas.download import Torrent, TorrentStatus
from app.services.brush.torrent_lifecycle import BrushTorrentLifecycle
from app.sites.site_cache import SiteCache

HOUR = 3600


class _Repo:
    def __init__(self, torrent_ids):
        self._ids = torrent_ids
        self.events: list[dict] = []

    def get_brushtask_torrents(self, taskid):
        return [type("T", (), {"DOWNLOAD_ID": i, "ENCLOSURE": "", "PAGE_URL": ""})() for i in self._ids]

    def insert_brush_event(self, **kwargs):
        self.events.append(kwargs)

    def delete_brushtask_torrent(self, taskid, rid):
        pass

    def update_brushtask_torrent_state(self, rows):
        pass

    def add_brushtask_upload_count(self, *args, **kwargs):
        pass


class _Downloader:
    def __init__(self, torrents):
        self._torrents = torrents
        self.deleted: list[str] = []

    def get_downloader_conf(self, downloader_id):
        return {"name": "qb", "id": downloader_id}

    def get_torrents(self, downloader_id, ids):
        return self._torrents

    def delete_torrents(self, downloader_id, ids, delete_file=True):
        self.deleted = list(ids)

    def get_free_space(self, downloader_id, path):
        return 100 * 1024**3


class _Sites:
    def get_sites(self, siteid=None):
        return {"name": "site"}


class _Message:
    def send_brushtask_remove_message(self, **kwargs):
        pass


class _Helper:
    def get_torrent_attr(self, site_info, enclosure):
        return enclosure, {}


def _lifecycle(torrents):
    return BrushTorrentLifecycle(
        helper=_Helper(),
        repo=_Repo([t.id for t in torrents]),
        downloader=_Downloader(torrents),
        sites=cast(SiteCache, _Sites()),
        message=cast(Message, _Message()),
    )


def _task(rule):
    return {
        "id": 1,
        "name": "刷流",
        "state": BrushTaskState.RUNNING.value,
        "downloader": 1,
        "site_id": 1,
        "savepath": "/downloads",
        "remove_rule": rule,
    }


def _pending_torrent(download_time):
    return Torrent(
        id="A",
        name="等待种子",
        download_time=download_time,
        iatime=0,
        status=TorrentStatus.Pending,
    )


def test_pending_torrent_waiting_long_enough_is_deleted():
    """等待种子（从未活动，iatime=0）等待 9h，配置 等待时间>3h → 应删除"""
    lc = _lifecycle([_pending_torrent(9 * HOUR)])
    lc.remove_task_torrents(1, _task({"pending_time": "gt#3", "mode": "or"}))
    assert lc._downloader.deleted == ["A"]


def test_queued_torrent_waiting_long_enough_is_deleted():
    """排队等待下载（Queued）同样计入等待时间"""
    lc = _lifecycle([Torrent(id="A", name="排队种子", download_time=9 * HOUR, iatime=0, status=TorrentStatus.Queued)])
    lc.remove_task_torrents(1, _task({"pending_time": "gt#3", "mode": "or"}))
    assert lc._downloader.deleted == ["A"]


def test_downloading_torrent_not_deleted_by_pending_rule():
    """正在下载的种子不属于等待态，等待时间规则不生效"""
    lc = _lifecycle(
        [Torrent(id="A", name="下载中", download_time=9 * HOUR, iatime=9 * HOUR, status=TorrentStatus.Downloading)]
    )
    lc.remove_task_torrents(1, _task({"pending_time": "gt#3", "mode": "or"}))
    assert lc._downloader.deleted == []


def test_pending_torrent_waiting_too_short_not_deleted():
    """等待时长不足 3h 不删除"""
    lc = _lifecycle([_pending_torrent(1 * HOUR)])
    lc.remove_task_torrents(1, _task({"pending_time": "gt#3", "mode": "or"}))
    assert lc._downloader.deleted == []


class _AttrTrackingHelper:
    """记录 get_torrent_attr 调用次数，验证详情页请求仅在规则需要时发起"""

    def __init__(self):
        self.calls = 0

    def get_torrent_attr(self, site_info, enclosure, use_cache=True):
        self.calls += 1
        return enclosure, {"free": True, "hr": False}


class _RepoWithEnclosure:
    """跟踪种子带真实下载链接，用于验证 need_attr 守卫"""

    def __init__(self, torrent_ids):
        self._ids = torrent_ids

    def get_brushtask_torrents(self, taskid):
        return [
            type(
                "T",
                (),
                {"DOWNLOAD_ID": i, "ENCLOSURE": f"https://site/download/{i}", "PAGE_URL": f"https://site/detail/{i}"},
            )()
            for i in self._ids
        ]


def test_remove_rule_without_attr_does_not_fetch_torrent_attr():
    """空删种规则/纯下载器指标规则：不应为每颗种子抓取详情页（避免消耗站点限流）"""
    torrent = Torrent(
        id="A", name="做种", download_time=1 * HOUR, iatime=1 * HOUR, status=TorrentStatus.Uploading, progress=1.0
    )
    helper = _AttrTrackingHelper()
    lc = BrushTorrentLifecycle(
        helper=helper,
        repo=_RepoWithEnclosure([torrent.id]),
        downloader=_Downloader([torrent]),
        sites=cast(SiteCache, _Sites()),
        message=cast(Message, _Message()),
    )
    lc.remove_task_torrents(1, _task({"ratio": "lt#3", "mode": "or"}))
    assert helper.calls == 0


def test_remove_rule_needing_attr_fetches_torrent_attr():
    """含 freestatus/hr 的删种规则：需要抓取详情页判断免费/HR 状态"""
    torrent = Torrent(
        id="A", name="做种", download_time=1 * HOUR, iatime=1 * HOUR, status=TorrentStatus.Uploading, progress=1.0
    )
    helper = _AttrTrackingHelper()
    lc = BrushTorrentLifecycle(
        helper=helper,
        repo=_RepoWithEnclosure([torrent.id]),
        downloader=_Downloader([torrent]),
        sites=cast(SiteCache, _Sites()),
        message=cast(Message, _Message()),
    )
    lc.remove_task_torrents(1, _task({"freestatus": "NORMAL", "mode": "or"}))
    assert helper.calls == 1


class _UrlTrackingHelper:
    """记录 get_torrent_attr 实际请求的 URL，验证优先使用详情页 page_url"""

    def __init__(self, attr=None):
        self.urls: list[str] = []
        self._attr = attr

    def get_torrent_attr(self, site_info, url, use_cache=True):
        self.urls.append(url)
        return url, self._attr


def _seeding_torrent():
    return Torrent(
        id="A", name="做种", download_time=1 * HOUR, iatime=1 * HOUR, status=TorrentStatus.Uploading, progress=1.0
    )


def _lc_with_helper(helper, torrent):
    return BrushTorrentLifecycle(
        helper=helper,
        repo=_RepoWithEnclosure([torrent.id]),
        downloader=_Downloader([torrent]),
        sites=cast(SiteCache, _Sites()),
        message=cast(Message, _Message()),
    )


def test_attr_fetch_prefers_page_url_over_enclosure():
    """M-Team 等站点 enclosure 为一次性签名链接无法提取 TID，属性检查须用详情页 page_url"""
    torrent = _seeding_torrent()
    helper = _UrlTrackingHelper(attr={"free": True, "hr": False})
    lc = _lc_with_helper(helper, torrent)
    lc.remove_task_torrents(1, _task({"freestatus": "Y", "mode": "or"}))
    assert helper.urls == ["https://site/detail/A"]


def test_free_torrent_not_deleted_when_freestatus_rule_on():
    """免费种子在开启 Free 到期删规则时不应被删除"""
    torrent = _seeding_torrent()
    helper = _UrlTrackingHelper(attr={"free": True, "hr": False})
    lc = _lc_with_helper(helper, torrent)
    lc.remove_task_torrents(1, _task({"freestatus": "Y", "mode": "or"}))
    assert lc._downloader.deleted == []


def test_torrent_not_deleted_when_attr_unknown():
    """详情属性抓取失败（返回 None）：跳过本轮判断，不得按非免费误删"""
    torrent = _seeding_torrent()
    helper = _UrlTrackingHelper(attr=None)
    lc = _lc_with_helper(helper, torrent)
    lc.remove_task_torrents(1, _task({"freestatus": "Y", "mode": "or"}))
    assert lc._downloader.deleted == []


def test_remove_rule_pubdate_alone_triggers_attr_fetch():
    """只配 pubdate 的删种规则也要抓详情页属性（页面发布时间为准）"""
    from app.services.brush.torrent_lifecycle import BrushTorrentLifecycle

    assert BrushTorrentLifecycle._remove_rule_needs_torrent_attr({"pubdate": "0-24"}) is True
    assert BrushTorrentLifecycle._remove_rule_needs_torrent_attr({"pubdate": "#"}) is False
