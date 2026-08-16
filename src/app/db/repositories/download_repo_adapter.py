"""
下载领域 Repository 适配器
将旧版 DownloadRepository 适配为新领域接口
"""

from typing import Any

from app.db.repositories.download_repository import DownloadRepository
from app.domain.entities.download import (
    DownloadHistoryEntity,
    DownloadSettingEntity,
    IndexerStatisticsEntity,
)
from app.domain.interfaces.download_repo import IDownloadHistoryRepository


class DownloadHistoryRepositoryAdapter(IDownloadHistoryRepository):
    """下载历史仓储适配器"""

    def __init__(self, repo: DownloadRepository | None = None):
        self._repo = repo or DownloadRepository()

    def is_exists(self, enclosure: str, downloader: str, download_id: str) -> bool:
        return self._repo.is_exists_download_history(enclosure, downloader, download_id)

    def is_exists_by_tmdb(self, tmdb_id: str, season_episode: str) -> bool:
        return self._repo.is_exists_download_history_by_tmdb(int(tmdb_id), season_episode)

    def is_completed_by_tmdb(self, tmdb_id: str, season_episode: str) -> bool:
        return self._repo.is_completed_download_history_by_tmdb(int(tmdb_id), season_episode)

    def get_contiguous_completed_episode_by_tmdb(self, tmdb_id, season: int | None, start: int = 1) -> int:
        """查询某季已完成下载的连续集数（重订阅续订用，季包保守记 start）."""
        return self._repo.get_contiguous_completed_episode_by_tmdb(int(tmdb_id), season, start=start)

    def insert(self, media_info, downloader: str, download_id: str, save_dir: str) -> None:
        self._repo.insert_download_history(media_info, downloader, download_id, save_dir)

    def get_all(
        self, date: str | None = None, hid: int | None = None, num: int = 30, page: int = 1
    ) -> list[DownloadHistoryEntity]:
        rows = self._repo.get_download_history(date=date, hid=hid, num=num, page=page)
        if not rows:
            return []
        return [entity for entity in [DownloadHistoryEntity.from_orm(r) for r in rows] if entity is not None]

    def get_by_title(self, title: str) -> list[DownloadHistoryEntity]:
        rows = self._repo.get_download_history_by_title(title)
        if not rows:
            return []
        return [entity for entity in [DownloadHistoryEntity.from_orm(r) for r in rows] if entity is not None]

    def get_by_path(self, path: str) -> DownloadHistoryEntity | None:
        row = self._repo.get_download_history_by_path(path)
        if not row:
            return None
        return DownloadHistoryEntity.from_orm(row)

    def get_by_downloader(self, downloader: str, download_id: str) -> DownloadHistoryEntity | None:
        row = self._repo.get_download_history_by_downloader(downloader, download_id)
        if not row:
            return None
        return DownloadHistoryEntity.from_orm(row)

    # 兼容旧Repository方法名
    def insert_download_history(self, media_info, downloader: str, download_id: str, save_dir: str) -> None:
        self._repo.insert_download_history(media_info, downloader, download_id, save_dir)

    # 兼容旧Repository方法名
    def get_download_history(self, date=None, hid=None, num=30, page=1):
        return self._repo.get_download_history(date=date, hid=hid, num=num, page=page)

    # 兼容旧Repository方法名
    def get_download_history_by_title(self, title: str):
        return self._repo.get_download_history_by_title(title)

    # 兼容旧Repository方法名
    def get_download_history_by_downloader(self, downloader: str, download_id: str):
        return self._repo.get_download_history_by_downloader(downloader, download_id)

    def get_by_id(self, download_id: str):
        return self._repo.get_download_history_by_id(download_id)

    def is_exists_download_history_by_tmdb(self, tmdb_id, season_episode):
        return self._repo.is_exists_download_history_by_tmdb(int(tmdb_id), season_episode)

    # 兼容旧Repository方法名
    def get_download_history_by_path(self, path: str) -> Any:
        return self._repo.get_download_history_by_path(path)

    def get_download_history_list_by_path(self, path: str) -> Any:
        return self._repo.get_download_history_list_by_path(path)

    def count_download_history_by_path(self, path: str) -> int:
        return self._repo.count_download_history_by_path(path)

    def get_active_downloads(self) -> list[DownloadHistoryEntity]:
        rows = self._repo.get_active_downloads()
        if not rows:
            return []
        return [entity for entity in [DownloadHistoryEntity.from_orm(r) for r in rows] if entity is not None]

    def update_state(self, downloader: str, download_id: str, state: str) -> None:
        self._repo.update_download_state(downloader, download_id, state)

    def batch_update_state(self, items: list[tuple[str, str, str]]) -> None:
        """批量更新下载任务状态"""
        if not items:
            return
        self._repo.batch_update_download_state(items)

    def delete_by_tmdb(self, tmdb_id: str, season_prefix: str | None = None) -> int:
        return self._repo.delete_download_history_by_tmdb(tmdb_id, season_prefix)


class DownloadSettingRepositoryAdapter:
    """下载设置仓储适配器"""

    def __init__(self, repo: DownloadRepository | None = None):
        self._repo = repo or DownloadRepository()

    def delete(self, sid: int) -> None:
        self._repo.delete_download_setting(sid)

    def get_all(self, sid: int | None = None) -> list[DownloadSettingEntity]:
        rows = self._repo.get_download_setting(sid=sid)
        if not rows:
            return []
        return [entity for entity in [DownloadSettingEntity.from_orm(r) for r in rows] if entity is not None]

    def update(
        self,
        sid: int,
        name: str,
        category: str,
        tags: str,
        is_paused: bool,
        upload_limit: float,
        download_limit: float,
        ratio_limit: float,
        seeding_time_limit: float,
        downloader: str,
    ) -> None:
        self._repo.update_download_setting(
            sid=sid,
            name=name,
            category=category,
            tags=tags,
            is_paused=is_paused,
            upload_limit=upload_limit,
            download_limit=download_limit,
            ratio_limit=ratio_limit,
            seeding_time_limit=seeding_time_limit,
            downloader=downloader,
        )

    # 兼容旧Repository方法名
    def get_download_setting(self, sid=None):
        return self._repo.get_download_setting(sid=sid)

    def delete_download_setting(self, sid):
        self._repo.delete_download_setting(sid)

    def update_download_setting(
        self,
        sid,
        name,
        category,
        tags,
        is_paused,
        upload_limit,
        download_limit,
        ratio_limit,
        seeding_time_limit,
        downloader,
    ):
        self._repo.update_download_setting(
            sid=sid,
            name=name,
            category=category,
            tags=tags,
            is_paused=is_paused,
            upload_limit=upload_limit,
            download_limit=download_limit,
            ratio_limit=ratio_limit,
            seeding_time_limit=seeding_time_limit,
            downloader=downloader,
        )


class IndexerStatisticsRepositoryAdapter:
    """索引器统计仓储适配器"""

    def __init__(self, repo: DownloadRepository | None = None):
        self._repo = repo or DownloadRepository()

    def insert(self, indexer: str, itype: str, seconds: float, result: str) -> None:
        self._repo.insert_indexer_statistics(indexer, itype, int(seconds), result)

    def delete_all(self) -> None:
        self._repo.delete_all_indexer_statistics()

    def get_by_client(self, client_id: str) -> list[IndexerStatisticsEntity]:
        rows = self._repo.get_indexer_statistics(client_id)
        if not rows:
            return []
        result = []
        for r in rows:
            result.append(
                IndexerStatisticsEntity(indexer=r[0], total=r[1], fail=r[2], success=r[3], avg_seconds=r[4] or 0)
            )
        return result
