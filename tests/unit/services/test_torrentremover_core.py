"""TorrentRemoverService 单元测试."""

from unittest.mock import MagicMock

import pytest

from app.core.exceptions import ValidationError
from app.downloader.strategy import RemoveStrategy
from app.schemas.download import TorrentStatus
from app.services.torrentremover_core import TorrentRemoverRepository, TorrentRemoverService


def _make_service(repo=None, downloader=None, message=None, scheduler=None):
    return TorrentRemoverService(
        repository=repo or MagicMock(spec=TorrentRemoverRepository),
        downloader=downloader or MagicMock(),
        message=message or MagicMock(),
        scheduler=scheduler or MagicMock(),
    )


def _base_task_data(**overrides):
    data = {
        "tid": "",
        "name": "Test",
        "downloader": "1",
        "action": 1,
        "interval": 60,
        "enabled": 0,
        "samedata": 0,
        "only_nexus_media": 1,
        "ratio": 0,
        "seeding_time": 0,
        "upload_avs": 0,
        "size": "",
        "tags": "",
        "savepath_key": "",
        "tracker_key": "",
        "filter_status": "",
    }
    data.update(overrides)
    return data


class TestUpdateTorrentRemoveTask:
    """删种任务保存校验测试"""

    def test_accepts_global_status_for_any_downloader(self):
        """应接受 TorrentStatus 全局状态，而不受下载器自身支持状态限制"""
        repo = MagicMock(spec=TorrentRemoverRepository)
        svc = _make_service(repo=repo)
        svc._tasks = {}

        svc.update_torrent_remove_task(_base_task_data(filter_status="Stopped"))

        repo.insert_task.assert_called_once()
        config = repo.insert_task.call_args.kwargs["config"]
        assert config["filter_status"] == ["Stopped"]

    def test_rejects_invalid_status(self):
        """非法状态应抛出 ValidationError"""
        svc = _make_service()

        with pytest.raises(ValidationError, match="种子状态参数不合法"):
            svc.update_torrent_remove_task(_base_task_data(filter_status="NotAStatus"))

    def test_update_existing_task_uses_atomic_update(self):
        """带 tid 保存应走原子 UPDATE，不再先删后插"""
        repo = MagicMock(spec=TorrentRemoverRepository)
        repo.update_task.return_value = True
        svc = _make_service(repo=repo)
        svc._tasks = {}

        svc.update_torrent_remove_task(_base_task_data(tid=5, enabled=1))

        repo.update_task.assert_called_once()
        assert repo.update_task.call_args.args[0] == 5
        assert repo.update_task.call_args.kwargs["enabled"] == 1
        repo.insert_task.assert_not_called()
        repo.delete_task.assert_not_called()

    def test_update_falls_back_to_insert_when_task_missing(self):
        """tid 对应的任务已被删除时，应回退为新增"""
        repo = MagicMock(spec=TorrentRemoverRepository)
        repo.update_task.return_value = False
        svc = _make_service(repo=repo)
        svc._tasks = {}

        svc.update_torrent_remove_task(_base_task_data(tid=99))

        repo.update_task.assert_called_once()
        repo.insert_task.assert_called_once()

    def test_create_without_tid_only_inserts(self):
        """不带 tid 保存应仅新增，不触发更新"""
        repo = MagicMock(spec=TorrentRemoverRepository)
        svc = _make_service(repo=repo)
        svc._tasks = {}

        svc.update_torrent_remove_task(_base_task_data())

        repo.update_task.assert_not_called()
        repo.insert_task.assert_called_once()


class TestRemoveStrategy:
    """RemoveStrategy 配置解析测试"""

    def test_converts_status_strings_to_enum(self):
        """字符串状态应转换为 TorrentStatus 枚举"""
        strategy = RemoveStrategy.from_dict({"filter_status": "Stopped"})
        assert strategy.filter_status == [TorrentStatus.Stopped]

    def test_converts_multiple_status_strings(self):
        """多个字符串状态应转换为对应的枚举列表"""
        strategy = RemoveStrategy.from_dict({"filter_status": ["Stopped", "Paused", "Uploading"]})
        assert strategy.filter_status == [
            TorrentStatus.Stopped,
            TorrentStatus.Paused,
            TorrentStatus.Uploading,
        ]

    def test_keeps_enum_values(self):
        """已是 TorrentStatus 枚举的值应保持不变"""
        strategy = RemoveStrategy.from_dict({"filter_status": [TorrentStatus.Downloading]})
        assert strategy.filter_status == [TorrentStatus.Downloading]

    def test_skips_invalid_status_strings(self):
        """非法状态字符串应被忽略"""
        strategy = RemoveStrategy.from_dict({"filter_status": "NotAStatus"})
        assert strategy.filter_status == []

    def test_empty_status(self):
        """空状态应得到空列表"""
        strategy = RemoveStrategy.from_dict({})
        assert strategy.filter_status == []
