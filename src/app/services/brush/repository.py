"""Brush repository - 刷流任务数据仓库."""

from typing import Any

from app.db.repositories.brush_repository import BrushRepository


class BrushTaskRepository:
    """
    刷流任务数据仓库（原 BrushTask 中的数据层提取）
    职责：所有与刷流任务/种子相关的数据库操作。
    """

    def __init__(self, repo: BrushRepository | None = None):
        self._repo = repo or BrushRepository()

    def get_brushtasks(self, brush_id: int | None = None) -> Any:
        return self._repo.get_brushtasks(brush_id=brush_id)

    def get_brushtask_totalsize(self, task_id: int | None) -> Any:
        return self._repo.get_brushtask_totalsize(task_id)

    def get_brushtask_torrents(self, brush_id, active=True):
        return self._repo.get_brushtask_torrents(brush_id, active)

    def get_brushtask_torrent_by_enclosure(self, enclosure: str | None) -> Any:
        return self._repo.get_brushtask_torrent_by_enclosure(enclosure or "")

    def get_brush_events(
        self,
        task_id: int | None = None,
        action: str | None = None,
        page: int = 1,
        page_size: int = 50,
    ):
        return self._repo.get_brush_events(task_id, action, page, page_size)

    def get_brushtask_torrents_by_domain(self, domain: str | None) -> list:
        return self._repo.get_brushtask_torrents_by_domain(domain or "")

    def insert_brushtask_torrent(
        self,
        brush_id: int | None,
        title: str,
        enclosure: str,
        downloader: int,
        download_id: str,
        size: int,
        page_url: str = "",
    ) -> Any:
        return self._repo.insert_brushtask_torrent(
            brush_id=brush_id,
            title=title,
            enclosure=enclosure,
            downloader=str(downloader),
            download_id=download_id,
            size=str(size),
            page_url=page_url,
        )

    def add_brushtask_download_count(self, brush_id: int | None) -> Any:
        return self._repo.add_brushtask_download_count(brush_id=brush_id)

    def add_brushtask_upload_count(self, taskid: int | None, uploaded: int, downloaded: int, count: int) -> Any:
        return self._repo.add_brushtask_upload_count(taskid, uploaded, downloaded, count)

    def update_brushtask(self, brushtask_id: int | None, item: dict) -> Any:
        return self._repo.update_brushtask(brushtask_id, item)

    def delete_brushtask(self, brushtask_id: int | None) -> Any:
        return self._repo.delete_brushtask(brushtask_id or 0)

    def update_brushtask_state(self, tid: int | None, state: str | None) -> Any:
        return self._repo.update_brushtask_state(tid=tid, state=state or "")

    def update_brushtask_torrent_state(self, update_torrents: list | None) -> Any:
        return self._repo.update_brushtask_torrent_state(update_torrents or [])

    def delete_brushtask_torrent(self, taskid: int | None, download_id: str | None) -> Any:
        return self._repo.delete_brushtask_torrent(taskid, download_id)
