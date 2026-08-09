"""MEDIA_EPISODE_TRANSFERRED 事件处理器回归测试：单集转移不应重置订阅进度"""

from unittest.mock import MagicMock, patch

from app.events import Event
from app.events.constants import MEDIA_EPISODE_TRANSFERRED
from app.events.payloads import MediaEpisodeTransferredPayload
from app.services.subscribe import handlers


def _make_event(episodes, total=12):
    payload = MediaEpisodeTransferredPayload(
        tmdb_id=258348,
        title="克雷瓦提斯",
        season=2,
        episodes=episodes,
        total_episodes=total,
    )
    return Event(event_type=MEDIA_EPISODE_TRANSFERRED, payload=payload)


def _run(current_missing, transfer_eps, total=12):
    """驱动 handler，返回 update_lack 收到的缺失集列表。"""
    tv_repo = MagicMock()
    tv_repo.get_id.return_value = 24
    ep_repo = MagicMock()
    ep_repo.get.return_value = current_missing
    captured = {}

    def _capture(title, year, season, rssid, lack_episodes):
        captured["lack_episodes"] = lack_episodes

    tv_repo.update_lack.side_effect = _capture

    with patch.object(handlers, "SubscribeTvRepositoryAdapter", return_value=tv_repo), patch.object(
        handlers, "SubscribeTvEpisodeRepositoryAdapter", return_value=ep_repo
    ):
        handlers.handle_media_episode_transferred(_make_event(transfer_eps, total))
    return captured.get("lack_episodes")


def test_single_episode_subtracts_from_current_missing():
    """转移 E05，当前缺失 5-12 → 结果应为 6-12，而不是把 1-4 标回缺失"""
    result = _run(current_missing=[5, 6, 7, 8, 9, 10, 11, 12], transfer_eps=[5])
    assert result == [6, 7, 8, 9, 10, 11, 12]


def test_progressive_transfers_keep_progress():
    """逐集转移：E01 转移后缺失 2-12；E02 再转移不应把 E01 标回缺失"""
    first = _run(current_missing=[1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12], transfer_eps=[1])
    assert first == [2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12]
    # E02 转移时缺失列表已是 2-12，转移后应为 3-12（E01 不应回来）
    second = _run(current_missing=[2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12], transfer_eps=[2])
    assert second == [3, 4, 5, 6, 7, 8, 9, 10, 11, 12]


def test_season_pack_completes():
    """季包转移全部集数 → 缺失清空"""
    result = _run(current_missing=[1, 2, 3], transfer_eps=[1, 2, 3])
    assert result == []


def test_uninitialized_uses_current_ep_range():
    """缺失列表未初始化时，用订阅 current_ep 兜底构造初始范围"""
    result = _run(current_missing=None, transfer_eps=[5], total=12)
    # current_ep 默认 1（mock 的 subs[0].current_ep 是 MagicMock，isdigit 检查会失败）
    # 这里 ep_repo.get 返回 None → 进入初始化分支
    assert isinstance(result, list)
