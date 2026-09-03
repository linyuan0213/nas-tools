from math import floor
from typing import Callable

from app.core.exceptions import DomainError, RepositoryError, ServiceError  # noqa: F401
from app.domain.mediatypes import MediaType
from app.infrastructure.cache_system import get_cache_manager
from app.schemas.media import TransferHistoryPageDTO, UnknownListPageDTO
from app.services.filetransfer_service import FileTransferService as FileTransfer
from app.services.sync_service import SyncService


class TransferHistoryService:
    """
    转移历史业务服务
    """

    def __init__(
        self,
        filetransfer: FileTransfer,
        sync_service: SyncService,
        cache_ttl: int = 30,
        poster_resolver: Callable[[str, int], str] | None = None,
    ):
        self._filetransfer = filetransfer
        self._sync_service = sync_service
        self._cache = get_cache_manager().get_or_create("transfer_history_service", cache_type="memory", maxsize=100)
        self._cache_ttl = cache_ttl
        # (type, tmdbid) -> 海报 URL；None 表示不富化海报
        self._poster_resolver = poster_resolver
        # 进程级 memo：同一 (type, tmdbid) 只回源一次，跨页复用
        self._poster_memo: dict[tuple[str, int], str] = {}

    def _cache_key(self, prefix: str, *parts) -> str:
        return f"{prefix}:{':'.join(str(p) for p in parts)}"

    def get_transfer_history_page(self, search_str, page, page_num) -> TransferHistoryPageDTO:
        """分页查询转移历史（带缓存）"""
        if not page_num:
            page_num = 30
        if not page:
            page = 1
        else:
            page = int(page)
        cache_key = self._cache_key("history", search_str or "", page, page_num)
        cached = self._cache.get(cache_key)
        if cached is not None:
            return cached
        result = self._filetransfer.get_transfer_history(search_str, page, page_num)
        if result is None:
            total_count, historys = 0, []
        else:
            total_count, historys = result
        historys_list = []
        for history in historys:
            history = history.as_dict()
            sync_mode = history.get("mode")
            rmt_mode = sync_mode or ""
            history = {k.upper(): v for k, v in history.items()}
            history.update({"SYNC_MODE": sync_mode, "RMT_MODE": rmt_mode})
            # 海报富化：同 (type, tmdbid) 进程内只解析一次，缺 TMDBID/无解析器则跳过
            history["image"] = ""
            if self._poster_resolver:
                tmdbid = history.get("TMDBID")
                if tmdbid:
                    poster_key = (str(history.get("TYPE") or ""), int(tmdbid))
                    if poster_key not in self._poster_memo:
                        self._poster_memo[poster_key] = self._poster_resolver(poster_key[0], poster_key[1]) or ""
                    history["image"] = self._poster_memo[poster_key]
            historys_list.append(history)
        total_page = floor(total_count / page_num) + 1
        dto = TransferHistoryPageDTO(
            total=total_count, result=historys_list, total_page=total_page, page_num=page_num, current_page=page
        )
        self._cache.set(cache_key, dto, ttl=self._cache_ttl)
        return dto

    def get_transfer_statistics(self, days=90) -> dict:
        """获取转移统计（带缓存）"""
        cache_key = self._cache_key("stats", days)
        cached = self._cache.get(cache_key)
        if cached is not None:
            return cached
        data = {}
        for statistic in self._filetransfer.get_transfer_statistics(days) or []:
            if not statistic[2]:
                continue
            label = statistic[1]
            parsed = MediaType.from_string(statistic[0])
            if parsed not in (MediaType.MOVIE, MediaType.TV, MediaType.ANIME):
                continue
            entry = data.setdefault(label, {"movie": 0, "tv": 0, "anime": 0})
            if parsed == MediaType.MOVIE:
                entry["movie"] = statistic[2]
            elif parsed == MediaType.TV:
                entry["tv"] = statistic[2]
            elif parsed == MediaType.ANIME:
                entry["anime"] = statistic[2]
        labels = list(data.keys())
        result = {
            "labels": labels,
            "movie_nums": [data[label]["movie"] for label in labels],
            "tv_nums": [data[label]["tv"] for label in labels],
            "anime_nums": [data[label]["anime"] for label in labels],
        }
        self._cache.set(cache_key, result, ttl=self._cache_ttl)
        return result

    def _convert_unknown_record(self, rec) -> dict | None:
        """将未识别记录转换为前端需要的字典结构."""
        rec_path = str(rec.PATH or "")
        if not rec_path:
            return None
        path = rec_path.replace("\\", "/")
        path_to = str(rec.DEST or "").replace("\\", "/")
        sync_mode = str(rec.MODE or "")
        return {
            "id": rec.ID,
            "path": path,
            "to": path_to,
            "name": path,
            "sync_mode": sync_mode,
            "rmt_mode": sync_mode,
            "dst_backend": self._filetransfer.get_sync_backend_by_dest(path_to),
        }

    def get_unknown_list(self) -> list[dict]:
        """获取未识别记录列表（带缓存）"""
        cache_key = self._cache_key("unknown_list")
        cached = self._cache.get(cache_key)
        if cached is not None:
            return cached
        items = []
        for rec in self._filetransfer.get_transfer_unknown_paths() or []:
            item = self._convert_unknown_record(rec)
            if item:
                items.append(item)
        self._cache.set(cache_key, items, ttl=self._cache_ttl)
        return items

    def get_unknown_list_by_page(self, search_str, page, page_num) -> UnknownListPageDTO:
        """分页查询未识别记录（带缓存）"""
        if not page_num:
            page_num = 30
        if not page:
            page = 1
        else:
            page = int(page)
        cache_key = self._cache_key("unknown_page", search_str or "", page, page_num)
        cached = self._cache.get(cache_key)
        if cached is not None:
            return cached
        result2 = self._filetransfer.get_transfer_unknown_paths_by_page(search_str, page, page_num)
        if result2 is None:
            total_count, records = 0, []
        else:
            total_count, records = result2
        items = []
        for rec in records:
            item = self._convert_unknown_record(rec)
            if item:
                items.append(item)
        total_page = floor(total_count / page_num) + 1
        dto = UnknownListPageDTO(
            total=total_count, items=items, total_page=total_page, page_num=page_num, current_page=page
        )
        self._cache.set(cache_key, dto, ttl=self._cache_ttl)
        return dto

    def re_identify_unknown(self) -> int:
        """重新识别所有未识别记录"""
        item_ids = [rec.ID for rec in self._filetransfer.get_transfer_unknown_paths() or [] if rec.PATH]
        if item_ids:
            self._sync_service.re_identify_items(flag="unidentification", ids=item_ids)
        return len(item_ids)

    def clear_history(self):
        """清空识别记录"""
        self._filetransfer.delete_transfer()
        self._filetransfer.truncate_transfer_blacklist()
        self._cache.clear()
