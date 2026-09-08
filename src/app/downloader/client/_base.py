import os.path
import re
from abc import ABCMeta, abstractmethod
from typing import Any

import log
from app.downloader.strategy import RemoveStrategy
from app.schemas.download import Torrent, TorrentStatus
from app.utils import PathUtils, StringUtils


class _IDownloadClient(metaclass=ABCMeta):
    client_id = ""
    client_type = ""
    client_name = ""
    # 是否支持 PT（私有站点）种子下载。aria2/迅雷等不支持时，私有站点种子将被拦截
    supports_pt: bool = True

    _client_config: dict = {}
    download_dir: list = []
    name: str = ""

    @classmethod
    def match(cls, ctype: str) -> bool:
        return ctype in [cls.client_id, cls.client_type, cls.client_name]

    def get_type(self) -> str:
        return self.client_type

    @abstractmethod
    def connect(self) -> None:
        """连接下载器"""

    @abstractmethod
    def get_status(self) -> bool:
        """检查连通性"""

    @abstractmethod
    def get_torrents(
        self,
        ids: list[str] | str | None = None,
        status: Any = None,
        tag: str | list[str] | None = None,
    ) -> tuple[list[Torrent], bool]:
        """按条件读取种子信息。返回 (list[Torrent], bool)，bool 表示是否发生错误。"""

    @abstractmethod
    def get_downloading_torrents(
        self, ids: list[str] | str | None = None, tag: str | list[str] | None = None
    ) -> list[Torrent] | None:
        """读取下载中的种子信息，发生错误时返回 None"""

    @abstractmethod
    def get_completed_torrents(
        self, ids: list[str] | str | None = None, tag: str | list[str] | None = None
    ) -> list[Torrent] | None:
        """读取下载完成的种子信息，发生错误时返回 None"""

    @abstractmethod
    def get_files(self, tid: str | None = None) -> list[dict] | None:
        """读取种子文件列表（返回下载器原始格式，不建议外部直接调用）"""

    def get_normalized_files(self, tid: str | None = None) -> list[dict]:
        """
        读取种子文件列表并返回统一格式。
        :return: [{"id": file_id, "name": file_name}, ...]
        """
        raw_files = self.get_files(tid)
        if not raw_files:
            return []
        return self._normalize_files(raw_files)

    def _normalize_files(self, raw_files: list[dict]) -> list[dict]:
        """将原始文件列表转换为统一格式。子类必须覆盖。"""
        raise NotImplementedError(f"{self.__class__.__name__} 未实现 _normalize_files")

    def set_file_selection(self, tid: str | None, selected_map: dict[int, bool]) -> bool:
        """
        设置种子文件的选择状态（下载/跳过）。
        :param tid: 种子ID
        :param selected_map: {file_id: True/False, ...}
        :return: 是否成功
        """
        raise NotImplementedError(f"{self.__class__.__name__} 未实现 set_file_selection")

    @abstractmethod
    def set_torrents_status(self, ids: list[str] | str, tags: str | list[str] | None = None) -> bool:
        """迁移完成后设置种子标签为 已整理"""

    @abstractmethod
    def set_torrents_tag(self, ids: list[str] | str | None = None, tags: str | list[str] | None = None) -> bool:
        """设置种子标签"""

    def get_transfer_task(
        self, tag: str | None = None, match_path: bool | None = None, ids: list[str] | None = None
    ) -> list[dict]:
        """获取需要转移的种子列表。子类可覆盖 _get_content_subpath 来自定义路径计算。"""
        torrents = self.get_completed_torrents(ids=ids) or []
        trans_tasks = []
        tag_filtered = 0
        no_path = 0
        for torrent in torrents:
            labels = torrent.labels or []
            if "已整理" in labels:
                continue
            if tag and tag not in labels:
                tag_filtered += 1
                continue
            path = torrent.save_path
            if not path:
                no_path += 1
                continue
            true_path, replace_flag = self.get_replace_path(path, self.download_dir)
            if match_path and not replace_flag:
                continue
            subpath = self._get_content_subpath(torrent) or torrent.name or ""
            trans_tasks.append({"path": os.path.join(true_path, subpath).replace("\\", "/"), "id": torrent.id})
        if tag_filtered:
            log.debug(f"[{self.client_name}]{self.name} 标签隔离：{tag_filtered} 个种子未包含指定标签：{tag}（已忽略）")
        if no_path:
            log.debug(f"[{self.client_name}]{self.name} {no_path} 个种子未获取到下载保存路径")
        return trans_tasks

    def _get_content_subpath(self, torrent: Torrent) -> str | None:
        """获取种子内容相对路径。子类可覆盖，如 QB 的 content_path 处理。"""
        return None

    def get_remove_torrents(self, strategy: RemoveStrategy) -> list[dict]:
        """获取自动删种任务种子。通用默认实现，子类可覆盖以添加特有筛选。"""
        torrents, error_flag = self.get_torrents(status=strategy.filter_status, tag=strategy.filter_tags)
        if error_flag:
            return []

        remove_torrents = []
        remove_torrents_ids: list[str] = []

        for torrent in torrents:
            if strategy.ratio and torrent.ratio <= strategy.ratio:
                continue
            if strategy.seeding_time and torrent.seeding_time <= strategy.seeding_time * 3600:
                continue
            if strategy.size_range is not None:
                minsize, maxsize = strategy.size_range
                if torrent.size >= maxsize or torrent.size <= minsize:
                    continue
            if strategy.upload_avs and torrent.avg_upload_speed >= strategy.upload_avs * 1024:
                continue
            if strategy.savepath_key and not re.findall(strategy.savepath_key, torrent.save_path or "", re.I):
                continue
            if strategy.tracker_key:
                if not torrent.trackers:
                    continue
                tracker_match = any(re.findall(strategy.tracker_key, tracker, re.I) for tracker in torrent.trackers)
                if not tracker_match:
                    continue
            if not self._check_extra_remove_conditions(torrent, strategy):
                continue

            remove_torrents.append(
                {
                    "id": torrent.id,
                    "name": torrent.name,
                    "site": StringUtils.get_site_domain(torrent.trackers[0]) if torrent.trackers else "",
                    "size": torrent.size,
                }
            )
            remove_torrents_ids.append(str(torrent.id) if torrent.id else "")

        if strategy.samedata and remove_torrents:
            remove_torrents_plus = []
            for remove_torrent in remove_torrents:
                name = remove_torrent.get("name")
                size = remove_torrent.get("size")
                for torrent in torrents:
                    if torrent.name == name and torrent.size == size and str(torrent.id) not in remove_torrents_ids:
                        remove_torrents_plus.append(
                            {
                                "id": torrent.id,
                                "name": torrent.name,
                                "site": StringUtils.get_site_domain(torrent.trackers[0]) if torrent.trackers else "",
                                "size": torrent.size,
                            }
                        )
            remove_torrents_plus += remove_torrents
            return remove_torrents_plus

        return remove_torrents

    def _check_extra_remove_conditions(self, torrent: Torrent, strategy: RemoveStrategy) -> bool:
        """子类覆盖此方法以添加下载器特有的删种条件，返回 True 表示保留。"""
        return True

    @abstractmethod
    def add_torrent(self, content: str | bytes, **kwargs) -> bool:
        """添加下载任务"""

    def add_torrent_and_get_id(
        self,
        content: str | bytes,
        is_paused: bool = False,
        download_dir: str | None = None,
        tags: list[str] | None = None,
        category: str | None = None,
        upload_limit: int | None = None,
        download_limit: int | None = None,
        ratio_limit: float | None = None,
        seeding_time_limit: int | None = None,
        cookie: str | None = None,
        **kwargs: Any,
    ) -> str | None:
        """
        添加种子并返回种子ID。
        默认实现调用 add_torrent；子类可覆盖以处理特殊逻辑。
        """
        success = self.add_torrent(
            content,
            is_paused=is_paused,
            download_dir=download_dir,
            tag=tags,
            category=category,
            cookie=cookie,
            **kwargs,
        )
        if success and isinstance(success, str):
            return success
        return None

    @abstractmethod
    def start_torrents(self, ids: list[str] | str | None = None) -> bool:
        """开始种子"""

    @abstractmethod
    def stop_torrents(self, ids: list[str] | str | None = None) -> bool:
        """停止种子"""

    @abstractmethod
    def delete_torrents(self, delete_file: bool = False, ids: list[str] | str | None = None) -> bool:
        """删除种子"""

    @abstractmethod
    def get_download_dirs(self) -> list[str]:
        """获取下载目录清单"""

    def list_remote_dirs(self) -> list[str]:
        """获取下载器已知的目录候选列表（用于 UI 浏览选择保存目录）"""
        dirs: list[str] = []
        try:
            dirs.extend(d for d in (self.get_download_dirs() or []) if d)
        except Exception as e:
            log.debug(f"[{self.client_name}]{self.name} 读取下载目录失败: {e}")
        try:
            torrents, error_flag = self.get_torrents()
            if not error_flag:
                dirs.extend(t.save_path for t in torrents if t.save_path)
        except Exception as e:
            log.debug(f"[{self.client_name}]{self.name} 读取种子保存路径失败: {e}")
        return sorted(set(dirs))

    @staticmethod
    def get_replace_path(path: str, downloaddir: list | None) -> tuple[str, bool]:
        """对目录路径进行转换"""
        if not path or not downloaddir:
            return "", False
        path = os.path.normpath(path)
        for attr in downloaddir:
            save_path = attr.get("save_path")
            if not save_path:
                continue
            save_path = os.path.normpath(save_path)
            container_path = attr.get("container_path")
            if not container_path:
                container_path = save_path
            else:
                container_path = os.path.normpath(container_path)
            if PathUtils.is_path_in_path(save_path, path):
                return path.replace(save_path, container_path), True
        return path, False

    @abstractmethod
    def change_torrent(self, tid: str | None = None, **kwargs: Any) -> bool:
        """修改种子状态"""

    def get_downloading_progress(
        self, ids: list[str] | str | None = None, tag: str | list[str] | None = None
    ) -> list[dict]:
        """获取下载进度。子类可覆盖 _format_progress 或 _format_speed 来自定义。"""
        torrents = self.get_downloading_torrents(ids=ids, tag=tag) or []
        return [self._format_progress(t) for t in torrents]

    def _format_progress(self, torrent: Torrent) -> dict:
        progress = round(torrent.progress * 100, 1)
        if torrent.status in (TorrentStatus.Paused, TorrentStatus.Stopped):
            state, speed = "Stopped", "已暂停"
        else:
            state = "Downloading"
            speed = self._format_speed(torrent)
        return {
            "id": torrent.id,
            "name": torrent.name,
            "speed": speed,
            "state": state,
            "progress": progress,
            "size": StringUtils.str_filesize(torrent.size) if torrent.size else "",
            "labels": getattr(torrent, "labels", []) or [],
            "category": ", ".join(c) if (c := getattr(torrent, "category", [])) else "",
        }

    def _format_speed(self, torrent: Torrent) -> str:
        dl = StringUtils.str_filesize(torrent.download_speed)
        ul = StringUtils.str_filesize(torrent.upload_speed)
        if torrent.progress * 100 >= 100:
            return f"{chr(8595)}{dl}B/s {chr(8593)}{ul}B/s"
        eta = StringUtils.str_timelong(torrent.eta)
        return f"{chr(8595)}{dl}B/s {chr(8593)}{ul}B/s {eta}"

    def get_transfer_statistics(self) -> dict | None:
        """获取下载器实时速率与速度上限；不支持或离线时返回 None"""
        return None

    @abstractmethod
    def set_speed_limit(self, download_limit: int | None = None, upload_limit: int | None = None) -> bool:
        """设置速度限制"""

    @abstractmethod
    def recheck_torrents(self, ids: list[str] | str | None = None) -> bool:
        """重新校验种子"""

    @abstractmethod
    def get_free_space(self, path: str) -> int | None:
        """获取剩余空间"""

    def get_torrent_trackers(self, torrent_hash: str) -> list[str]:
        """获取种子 tracker URL 列表"""
        return []

    def add_torrent_trackers(self, torrent_hash: str, urls: list[str] | str) -> None:
        """添加 tracker"""

    def remove_torrent_trackers(self, torrent_hash: str, urls: list[str] | str) -> None:
        """移除 tracker"""

    def edit_torrent_tracker(self, torrent_hash: str, old_url: str, new_url: str) -> None:
        """替换 tracker"""

    @abstractmethod
    def _map_status(self, raw_state: Any) -> TorrentStatus:
        """将下载器原始状态映射为通用 TorrentStatus"""

    @property
    @abstractmethod
    def _supported_statuses(self) -> list[TorrentStatus]:
        """该下载器支持的状态列表"""
