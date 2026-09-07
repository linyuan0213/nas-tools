"""
转移领域 Repository 适配器
将旧版 TransferRepository 适配为新领域接口
"""

from enum import Enum

from app.db.models import TRANSFERUNKNOWN
from app.db.repositories.transfer_repository import TransferRepository
from app.domain.entities.transfer import (
    TransferHistoryEntity,
    TransferUnknownEntity,
)
from app.schemas.media import TransferMediaDTO


class TransferHistoryRepositoryAdapter:
    """转移历史仓储适配器"""

    def __init__(self, repo: TransferRepository | None = None):
        self._repo = repo or TransferRepository()

    def is_exists(self, source_path: str, source_filename: str, dest_path: str, dest_filename: str) -> bool:
        return self._repo.is_transfer_history_exists(source_path, source_filename, dest_path, dest_filename)

    def insert(
        self, in_from: Enum, rmt_mode: str, in_path: str, out_path: str, dest: str, media_info: TransferMediaDTO
    ) -> None:
        self._repo.insert_transfer_history(in_from, rmt_mode, in_path, out_path, dest, media_info)

    def get_page(self, search: str | None, page: int, rownum: int) -> tuple[int, list[TransferHistoryEntity]]:
        count, rows = self._repo.get_transfer_history(search, page, rownum)
        if not rows:
            return count, []
        return count, [e for e in [TransferHistoryEntity.from_orm(r) for r in rows] if e is not None]

    def get_by_id(self, logid: int) -> TransferHistoryEntity | None:
        row = self._repo.get_transfer_info_by_id(logid)
        return TransferHistoryEntity.from_orm(row)

    def get_by_tmdb(
        self, tmdbid: int, season: str | None = None, season_episode: str | None = None
    ) -> list[TransferHistoryEntity]:
        rows = self._repo.get_transfer_info_by(tmdbid, season, season_episode)
        if not rows:
            return []
        return [e for e in [TransferHistoryEntity.from_orm(r) for r in rows] if e is not None]

    def delete(self, logid: int) -> None:
        self._repo.delete_transfer_log_by_id(logid)

    def delete_by_source(self, source_path: str, source_filename: str) -> None:
        self._repo.delete_transfer_history_by_source(source_path, source_filename)

    # 兼容旧Repository方法名
    def is_sync_in_history(self, path: str, dest: str) -> bool:
        return self._repo.is_sync_in_history(path, dest)

    # 兼容旧Repository方法名
    def insert_sync_history(self, path: str, src: str, dest: str) -> None:
        self._repo.insert_sync_history(path, src, dest)

    # 兼容旧Repository方法名
    def get_transfer_info_by(
        self, tmdbid: int | None, season: str | None = None, season_episode: str | None = None
    ) -> list[TransferHistoryEntity] | None:
        rows = self._repo.get_transfer_info_by(tmdbid, season, season_episode)
        if not rows:
            return None
        return [e for e in [TransferHistoryEntity.from_orm(r) for r in rows] if e is not None]

    def get_contiguous_transferred_episode_by_tmdb(self, tmdbid, season: int | None = None, start: int = 1) -> int:
        """查询某季已成功转移的连续集数（重订阅续订用，季包保守记 start）."""
        return self._repo.get_contiguous_transferred_episode_by_tmdb(tmdbid, season, start=start)

    # 兼容旧Repository方法名
    def get_transfer_info_by_id(self, logid: int | None) -> TransferHistoryEntity | None:
        row = self._repo.get_transfer_info_by_id(logid)
        return TransferHistoryEntity.from_orm(row)

    def get_transfer_history(
        self, search: str | None, page: int, rownum: int
    ) -> tuple[int, list[TransferHistoryEntity]]:
        total, rows = self._repo.get_transfer_history(search, page, rownum)
        entities = [e for e in [TransferHistoryEntity.from_orm(r) for r in rows] if e is not None]
        return total, entities

    def delete_transfer_log_by_id(self, logid: int) -> None:
        self._repo.delete_transfer_log_by_id(logid)

    def delete_transfer_logs(self, logids: list[int]) -> None:
        self._repo.delete_transfer_logs(logids)

    # 兼容旧Repository方法名
    def delete_transfer(self) -> None:
        self._repo.delete_transfer()

    # 兼容旧Repository方法名
    def get_transfer_statistics(self, days: int = 30) -> list[tuple]:
        return self._repo.get_transfer_statistics(days)

    def get_transfer_series_statistics(self, days: int = 30) -> list[tuple]:
        return self._repo.get_transfer_series_statistics(days)

    def delete_transfer_unknown(self, tid: int | None) -> None:
        self._repo.delete_transfer_unknown(tid)

    def delete_transfer_unknowns(self, tids: list[int]) -> None:
        self._repo.delete_transfer_unknowns(tids)

    def get_unknown_info_by_id(self, tid: int | None) -> TransferUnknownEntity | None:
        row = self._repo.get_unknown_info_by_id(tid)
        return TransferUnknownEntity.from_orm(row)

    def update_transfer_unknown_state(self, path: str) -> None:
        self._repo.update_transfer_unknown_state(path)

    # 兼容旧Repository方法名 - 委托给Unknown子适配器
    def get_transfer_unknown_paths(self) -> list[TRANSFERUNKNOWN]:
        return self._repo.get_transfer_unknown_paths()

    def is_transfer_unknown_exists(self, path: str) -> bool:
        return self._repo.is_transfer_unknown_exists(path)

    # 兼容旧Repository方法名 - 委托给Unknown子适配器
    def get_transfer_unknown_paths_by_page(
        self, search: str | None, page: int, rownum: int
    ) -> tuple[int, list[TRANSFERUNKNOWN]]:
        return self._repo.get_transfer_unknown_paths_by_page(search, page, rownum)

    def insert_transfer_blacklist(self, path: str) -> None:
        self._repo.insert_transfer_blacklist(path)

    def delete_transfer_blacklist(self, path: str) -> None:
        self._repo.delete_transfer_blacklist(path)

    # 兼容旧Repository方法名 - 委托给Blacklist子适配器
    def truncate_transfer_blacklist(self) -> None:
        self._repo.truncate_transfer_blacklist()

    # 兼容旧Repository方法名
    def is_transfer_notin_blacklist(self, path: str) -> bool:
        return self._repo.is_transfer_notin_blacklist(path)

    def is_need_insert_transfer_unknown(self, path: str) -> bool:
        return self._repo.is_need_insert_transfer_unknown(path)

    def insert_transfer_unknown(self, path: str, dest: str, rmt_mode: str) -> None:
        self._repo.insert_transfer_unknown(path, dest, rmt_mode)

    def insert_transfer_history(
        self,
        in_from: Enum,
        rmt_mode: str,
        in_path: str,
        out_path: str,
        dest: str,
        media_info: TransferMediaDTO,
        dst_backend: str | None = None,
    ) -> None:
        self._repo.insert_transfer_history(in_from, rmt_mode, in_path, out_path, dest, media_info, dst_backend)


class TransferUnknownRepositoryAdapter:
    """转移未知文件仓储适配器"""

    def __init__(self, repo: TransferRepository | None = None):
        self._repo = repo or TransferRepository()

    def insert(self, path: str, dest: str, mode: str) -> None:
        self._repo.insert_transfer_unknown(path, dest, mode)

    def get_all(self) -> list[TransferUnknownEntity]:
        rows = self._repo.get_transfer_unknowns()
        if not rows:
            return []
        return [e for e in [TransferUnknownEntity.from_orm(r) for r in rows] if e is not None]

    def get_by_id(self, tid: int) -> TransferUnknownEntity | None:
        row = self._repo.get_transfer_unknown_by_id(tid)
        return TransferUnknownEntity.from_orm(row)

    def is_exists(self, path: str) -> bool:
        return self._repo.is_exists_transfer_unknowns(path)

    def delete(self, tid: int) -> None:
        self._repo.delete_transfer_unknown(tid)

    def truncate(self) -> None:
        self._repo.truncate_transfer_unknowns()


class TransferBlacklistRepositoryAdapter:
    """转移黑名单仓储适配器"""

    def __init__(self, repo: TransferRepository | None = None):
        self._repo = repo or TransferRepository()

    def is_exists(self, path: str) -> bool:
        return self._repo.is_exists_transfer_blacklist(path)

    def insert(self, path: str) -> None:
        self._repo.insert_transfer_blacklist(path)

    def delete(self, path: str) -> None:
        self._repo.delete_transfer_blacklist(path)

    def truncate(self) -> None:
        self._repo.truncate_transfer_blacklist()
