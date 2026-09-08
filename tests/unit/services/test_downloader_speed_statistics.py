"""DownloadService.get_downloader_speed_statistics 聚合逻辑测试"""

from app.services.download_service import DownloadService


class _FakeClient:
    def __init__(self, stat=None):
        self._stat = stat

    def get_transfer_statistics(self):
        return self._stat


class _FakeDownloader:
    """最小化的下载器门面替身，仅实现速率统计聚合所需接口"""

    def __init__(self, confs, clients):
        self._confs = confs
        self._clients = clients

    def get_downloader_conf(self, did=None):
        if did is None:
            return {str(k): dict(v) for k, v in self._confs.items()}
        conf = self._confs.get(str(did))
        return dict(conf) if conf else None

    def get_downloader(self, downloader_id=None):
        return self._clients.get(str(downloader_id))


def _build_service(confs, clients) -> DownloadService:
    service = object.__new__(DownloadService)
    service._downloader = _FakeDownloader(confs, clients)  # type: ignore[assignment]
    return service


def _conf(did, enabled=True):
    return {"id": did, "name": f"DL-{did}", "enabled": 1 if enabled else 0}


def test_aggregate_single_online_with_limits():
    confs = {"1": _conf(1)}
    clients = {
        "1": _FakeClient(
            {
                "download_speed": 10 * 1024 * 1024,
                "upload_speed": 2 * 1024 * 1024,
                "download_limit": 50 * 1024 * 1024,
                "upload_limit": 10 * 1024 * 1024,
            }
        )
    }
    result = _build_service(confs, clients).get_downloader_speed_statistics()

    assert result["online"] is True
    assert result["online_count"] == 1
    assert result["downloader_count"] == 1
    assert result["download_speed"] == 10 * 1024 * 1024
    assert result["upload_speed"] == 2 * 1024 * 1024
    assert result["download_limit"] == 50 * 1024 * 1024
    assert result["upload_limit"] == 10 * 1024 * 1024
    assert len(result["downloaders"]) == 1


def test_aggregate_multiple_downloaders_sums_speed_and_limit():
    confs = {"1": _conf(1), "2": _conf(2)}
    clients = {
        "1": _FakeClient(
            {
                "download_speed": 1024,
                "upload_speed": 2048,
                "download_limit": 1024 * 1024,
                "upload_limit": 512 * 1024,
            }
        ),
        "2": _FakeClient(
            {
                "download_speed": 4096,
                "upload_speed": 1024,
                "download_limit": 2 * 1024 * 1024,
                "upload_limit": 1024 * 1024,
            }
        ),
    }
    result = _build_service(confs, clients).get_downloader_speed_statistics()

    assert result["online"] is True
    assert result["online_count"] == 2
    assert result["download_speed"] == 5120
    assert result["upload_speed"] == 3072
    assert result["download_limit"] == 3 * 1024 * 1024
    assert result["upload_limit"] == 1536 * 1024
    assert len(result["downloaders"]) == 2


def test_limit_none_when_any_online_downloader_unlimited():
    confs = {"1": _conf(1), "2": _conf(2)}
    clients = {
        "1": _FakeClient({"download_speed": 1024, "upload_speed": 0, "download_limit": None, "upload_limit": 1024}),
        "2": _FakeClient(
            {
                "download_speed": 2048,
                "upload_speed": 0,
                "download_limit": 1024 * 1024,
                "upload_limit": 1024 * 1024,
            }
        ),
    }
    result = _build_service(confs, clients).get_downloader_speed_statistics()

    assert result["download_speed"] == 3072
    assert result["download_limit"] is None
    assert result["upload_limit"] == 1024 * 1024 + 1024


def test_offline_and_disabled_downloader_skipped():
    confs = {"1": _conf(1, enabled=False), "2": _conf(2)}
    clients = {"2": None}
    result = _build_service(confs, clients).get_downloader_speed_statistics()

    assert result["online"] is False
    assert result["online_count"] == 0
    assert result["downloader_count"] == 1
    assert result["downloaders"] == []
