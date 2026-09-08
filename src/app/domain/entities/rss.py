"""
订阅领域实体
定义订阅历史、电影订阅、种子、剧集订阅、剧集分集的领域模型
"""

from dataclasses import dataclass, fields
from enum import Enum
from typing import Any, Optional


class SubscribeState(Enum):
    """订阅状态值对象"""

    PENDING = "D"
    SEARCHING = "S"
    RUNNING = "R"
    COMPLETED = "C"
    ERROR = "E"
    CANCELLED = "N"

    @classmethod
    def from_value(cls, value: str) -> "SubscribeState":
        for member in cls:
            if member.value == value:
                return member
        raise ValueError(f"无效的订阅状态: {value}")

    @property
    def display_name(self) -> str:
        return {
            "D": "待处理",
            "S": "搜索中",
            "R": "监控中",
            "C": "已完成",
            "E": "错误",
            "N": "已取消",
        }.get(self.value, self.value)


@dataclass
class SubscribeHistoryEntity:
    """订阅历史记录实体"""

    id: int
    subscribe_type: str
    subscribe_id: str
    name: str
    year: str
    tmdb_id: str
    season: str
    image: str
    description: str
    total: int
    start: int
    finish_time: str
    note: str

    @classmethod
    def from_orm(cls, orm_model) -> Optional["SubscribeHistoryEntity"]:
        if orm_model is None:
            return None
        return cls(
            id=orm_model.ID,
            subscribe_type=orm_model.TYPE or "",
            subscribe_id=orm_model.RSSID or "",
            name=orm_model.NAME or "",
            year=orm_model.YEAR or "",
            tmdb_id=orm_model.TMDBID or "",
            season=orm_model.SEASON or "",
            image=orm_model.IMAGE or "",
            description=orm_model.DESC or "",
            total=orm_model.TOTAL or 0,
            start=orm_model.START or 0,
            finish_time=orm_model.FINISH_TIME or "",
            note=orm_model.NOTE or "",
        )

    # 从 ORM 列名到 dataclass 字段名的映射
    _ORM_FIELD_MAP = {
        "desc": "description",
        "description": "description",
        "tmdbid": "tmdb_id",
    }

    def __getattr__(self, name: str):
        """兼容旧代码的大写属性访问（如 entity.ID -> entity.id）"""
        lower_name = name.lower()
        # 检查是否是 ORM 列名映射
        field_name = self._ORM_FIELD_MAP.get(lower_name, lower_name)
        if field_name in {f.name for f in fields(self)}:
            return getattr(self, field_name)
        raise AttributeError(f"'{self.__class__.__name__}' object has no attribute '{name}'")

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "type": self.subscribe_type,
            "rssid": self.subscribe_id,
            "name": self.name,
            "year": self.year,
            "tmdbid": self.tmdb_id,
            "season": self.season,
            "image": self.image,
            "desc": self.description,
            "total": self.total,
            "start": self.start,
            "finish_time": self.finish_time,
            "note": self.note,
        }


@dataclass
class SubscribeMovieEntity:
    """订阅电影订阅实体"""

    id: int
    name: str
    year: str
    keyword: str
    tmdb_id: str
    image: str
    subscribe_sites: str
    search_sites: str
    over_edition: bool
    filter_order: int
    filter_restype: str
    filter_pix: str
    filter_rule: int
    filter_team: str
    filter_include: str
    filter_exclude: str
    save_path: str
    download_setting: int | None
    fuzzy_match: bool
    state: str
    description: str
    note: str
    add_date: str = ""
    filter_free: bool = False

    @property
    def state_enum(self) -> SubscribeState:
        """返回状态枚举"""
        try:
            return SubscribeState.from_value(self.state)
        except ValueError:
            return SubscribeState.PENDING

    @property
    def is_pending(self) -> bool:
        """是否待处理"""
        return self.state == SubscribeState.PENDING.value

    @property
    def is_searching(self) -> bool:
        """是否搜索中"""
        return self.state == SubscribeState.SEARCHING.value

    @property
    def is_running(self) -> bool:
        """是否监控中"""
        return self.state == SubscribeState.RUNNING.value

    @property
    def is_completed(self) -> bool:
        """是否已完成"""
        return self.state == SubscribeState.COMPLETED.value

    @property
    def is_error(self) -> bool:
        """是否错误"""
        return self.state == SubscribeState.ERROR.value

    @property
    def is_cancelled(self) -> bool:
        """是否已取消"""
        return self.state == SubscribeState.CANCELLED.value

    @property
    def is_active(self) -> bool:
        """是否处于活动状态"""
        return self.is_pending or self.is_searching or self.is_running

    @property
    def can_search(self) -> bool:
        """是否可以开始搜索"""
        return self.is_pending or self.is_error

    def mark_searching(self) -> None:
        """标记为搜索中"""
        self.state = SubscribeState.SEARCHING.value

    def mark_running(self) -> None:
        """标记为监控中"""
        self.state = SubscribeState.RUNNING.value

    def mark_completed(self) -> None:
        """标记为已完成"""
        self.state = SubscribeState.COMPLETED.value

    def mark_error(self) -> None:
        """标记为错误"""
        self.state = SubscribeState.ERROR.value

    def mark_cancelled(self) -> None:
        """标记为已取消"""
        self.state = SubscribeState.CANCELLED.value

    @classmethod
    def from_orm(cls, orm_model) -> Optional["SubscribeMovieEntity"]:
        if orm_model is None:
            return None
        return cls(
            id=orm_model.ID,
            name=orm_model.NAME or "",
            year=orm_model.YEAR or "",
            keyword=orm_model.KEYWORD or "",
            tmdb_id=orm_model.TMDBID or "",
            image=orm_model.IMAGE or "",
            subscribe_sites=orm_model.RSS_SITES or "",
            search_sites=orm_model.SEARCH_SITES or "",
            over_edition=bool(orm_model.OVER_EDITION),
            filter_order=orm_model.FILTER_ORDER or 0,
            filter_restype=orm_model.FILTER_RESTYPE or "",
            filter_pix=orm_model.FILTER_PIX or "",
            filter_rule=orm_model.FILTER_RULE or 0,
            filter_team=orm_model.FILTER_TEAM or "",
            filter_include=orm_model.FILTER_INCLUDE or "",
            filter_exclude=orm_model.FILTER_EXCLUDE or "",
            filter_free=bool(orm_model.FILTER_FREE),
            save_path=orm_model.SAVE_PATH or "",
            download_setting=orm_model.DOWNLOAD_SETTING,
            fuzzy_match=bool(orm_model.FUZZY_MATCH),
            state=orm_model.STATE or "",
            description=orm_model.DESC or "",
            note=orm_model.NOTE or "",
            add_date=getattr(orm_model, "ADD_DATE", None) or "",
        )

    # 从 ORM 列名到 dataclass 字段名的映射
    _ORM_FIELD_MAP = {
        "desc": "description",
        "rss_sites": "subscribe_sites",
        "search_sites": "search_sites",
        "tmdbid": "tmdb_id",
    }

    def __getattr__(self, name: str):
        """兼容旧代码的大写属性访问（如 entity.ID -> entity.id）"""
        lower_name = name.lower()
        # 检查是否是 ORM 列名映射
        field_name = self._ORM_FIELD_MAP.get(lower_name, lower_name)
        if field_name in {f.name for f in fields(self)}:
            return getattr(self, field_name)
        raise AttributeError(f"'{self.__class__.__name__}' object has no attribute '{name}'")

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "name": self.name,
            "year": self.year,
            "keyword": self.keyword,
            "tmdbid": self.tmdb_id,
            "image": self.image,
            "rss_sites": self.subscribe_sites,
            "search_sites": self.search_sites,
            "over_edition": self.over_edition,
            "filter_order": self.filter_order,
            "filter_restype": self.filter_restype,
            "filter_pix": self.filter_pix,
            "filter_rule": self.filter_rule,
            "filter_team": self.filter_team,
            "filter_include": self.filter_include,
            "filter_exclude": self.filter_exclude,
            "filter_free": self.filter_free,
            "save_path": self.save_path,
            "download_setting": self.download_setting,
            "fuzzy_match": self.fuzzy_match,
            "state": self.state,
            "desc": self.description,
            "note": self.note,
        }


@dataclass
class SubscribeTorrentEntity:
    """订阅种子记录实体"""

    id: int
    torrent_name: str
    enclosure: str
    subscribe_type: str
    title: str
    year: str
    season: str
    episode: str

    @classmethod
    def from_orm(cls, orm_model) -> Optional["SubscribeTorrentEntity"]:
        if orm_model is None:
            return None
        return cls(
            id=orm_model.ID,
            torrent_name=orm_model.TORRENT_NAME or "",
            enclosure=orm_model.ENCLOSURE or "",
            subscribe_type=orm_model.TYPE or "",
            title=orm_model.TITLE or "",
            year=orm_model.YEAR or "",
            season=orm_model.SEASON or "",
            episode=orm_model.EPISODE or "",
        )

    # 从 ORM 列名到 dataclass 字段名的映射
    _ORM_FIELD_MAP = {
        "desc": "description",
    }

    def __getattr__(self, name: str):
        """兼容旧代码的大写属性访问（如 entity.ID -> entity.id）"""
        lower_name = name.lower()
        # 检查是否是 ORM 列名映射
        field_name = self._ORM_FIELD_MAP.get(lower_name, lower_name)
        if field_name in {f.name for f in fields(self)}:
            return getattr(self, field_name)
        raise AttributeError(f"'{self.__class__.__name__}' object has no attribute '{name}'")

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "torrent_name": self.torrent_name,
            "enclosure": self.enclosure,
            "type": self.subscribe_type,
            "title": self.title,
            "year": self.year,
            "season": self.season,
            "episode": self.episode,
        }


@dataclass
class SubscribeTvEntity:
    """订阅剧集订阅实体"""

    id: int
    name: str
    year: str
    keyword: str
    season: str
    tmdb_id: str
    image: str
    subscribe_sites: str
    search_sites: str
    over_edition: bool
    filter_order: int
    filter_restype: str
    filter_pix: str
    filter_rule: int
    filter_team: str
    filter_include: str
    filter_exclude: str
    save_path: str
    download_setting: int | None
    fuzzy_match: bool
    total_ep: int
    current_ep: int
    total: int
    lack: int
    state: str
    description: str
    note: str
    add_date: str = ""
    filter_free: bool = False

    @property
    def state_enum(self) -> SubscribeState:
        """返回状态枚举"""
        try:
            return SubscribeState.from_value(self.state)
        except ValueError:
            return SubscribeState.PENDING

    @property
    def is_pending(self) -> bool:
        """是否待处理"""
        return self.state == SubscribeState.PENDING.value

    @property
    def is_searching(self) -> bool:
        """是否搜索中"""
        return self.state == SubscribeState.SEARCHING.value

    @property
    def is_running(self) -> bool:
        """是否监控中"""
        return self.state == SubscribeState.RUNNING.value

    @property
    def is_completed(self) -> bool:
        """是否已完成"""
        return self.state == SubscribeState.COMPLETED.value

    @property
    def is_error(self) -> bool:
        """是否错误"""
        return self.state == SubscribeState.ERROR.value

    @property
    def is_cancelled(self) -> bool:
        """是否已取消"""
        return self.state == SubscribeState.CANCELLED.value

    @property
    def is_active(self) -> bool:
        """是否处于活动状态"""
        return self.is_pending or self.is_searching or self.is_running

    @property
    def can_search(self) -> bool:
        """是否可以开始搜索"""
        return self.is_pending or self.is_error

    def mark_searching(self) -> None:
        """标记为搜索中"""
        self.state = SubscribeState.SEARCHING.value

    def mark_running(self) -> None:
        """标记为监控中"""
        self.state = SubscribeState.RUNNING.value

    def mark_completed(self) -> None:
        """标记为已完成"""
        self.state = SubscribeState.COMPLETED.value

    def mark_error(self) -> None:
        """标记为错误"""
        self.state = SubscribeState.ERROR.value

    def mark_cancelled(self) -> None:
        """标记为已取消"""
        self.state = SubscribeState.CANCELLED.value

    @property
    def is_fully_updated(self) -> bool:
        """是否全部剧集已更新完成"""
        return self.lack <= 0 and self.current_ep >= self.total_ep

    @property
    def remaining(self) -> int:
        """还缺多少集"""
        return max(0, self.total_ep - self.current_ep)

    def update_progress(self, current_ep: int) -> None:
        """更新当前集数并重新计算缺少的集数"""
        self.current_ep = max(0, current_ep)
        self.lack = max(0, self.total_ep - self.current_ep)

    @classmethod
    def from_orm(cls, orm_model) -> Optional["SubscribeTvEntity"]:
        if orm_model is None:
            return None
        return cls(
            id=orm_model.ID,
            name=orm_model.NAME or "",
            year=orm_model.YEAR or "",
            keyword=orm_model.KEYWORD or "",
            season=orm_model.SEASON or "",
            tmdb_id=orm_model.TMDBID or "",
            image=orm_model.IMAGE or "",
            subscribe_sites=orm_model.RSS_SITES or "",
            search_sites=orm_model.SEARCH_SITES or "",
            over_edition=bool(orm_model.OVER_EDITION),
            filter_order=orm_model.FILTER_ORDER or 0,
            filter_restype=orm_model.FILTER_RESTYPE or "",
            filter_pix=orm_model.FILTER_PIX or "",
            filter_rule=orm_model.FILTER_RULE or 0,
            filter_team=orm_model.FILTER_TEAM or "",
            filter_include=orm_model.FILTER_INCLUDE or "",
            filter_exclude=orm_model.FILTER_EXCLUDE or "",
            filter_free=bool(orm_model.FILTER_FREE),
            save_path=orm_model.SAVE_PATH or "",
            download_setting=orm_model.DOWNLOAD_SETTING,
            fuzzy_match=bool(orm_model.FUZZY_MATCH),
            total_ep=orm_model.TOTAL_EP or 0,
            current_ep=orm_model.CURRENT_EP or 0,
            total=orm_model.TOTAL or 0,
            lack=orm_model.LACK or 0,
            state=orm_model.STATE or "",
            description=orm_model.DESC or "",
            note=orm_model.NOTE or "",
            add_date=getattr(orm_model, "ADD_DATE", None) or "",
        )

    # 从 ORM 列名到 dataclass 字段名的映射
    _ORM_FIELD_MAP = {
        "desc": "description",
        "rss_sites": "subscribe_sites",
        "search_sites": "search_sites",
        "tmdbid": "tmdb_id",
    }

    def __getattr__(self, name: str):
        """兼容旧代码的大写属性访问（如 entity.ID -> entity.id）"""
        lower_name = name.lower()
        # 检查是否是 ORM 列名映射
        field_name = self._ORM_FIELD_MAP.get(lower_name, lower_name)
        if field_name in {f.name for f in fields(self)}:
            return getattr(self, field_name)
        raise AttributeError(f"'{self.__class__.__name__}' object has no attribute '{name}'")

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "name": self.name,
            "year": self.year,
            "keyword": self.keyword,
            "season": self.season,
            "tmdbid": self.tmdb_id,
            "image": self.image,
            "rss_sites": self.subscribe_sites,
            "search_sites": self.search_sites,
            "over_edition": self.over_edition,
            "filter_order": self.filter_order,
            "filter_restype": self.filter_restype,
            "filter_pix": self.filter_pix,
            "filter_rule": self.filter_rule,
            "filter_team": self.filter_team,
            "filter_include": self.filter_include,
            "filter_exclude": self.filter_exclude,
            "filter_free": self.filter_free,
            "save_path": self.save_path,
            "download_setting": self.download_setting,
            "fuzzy_match": self.fuzzy_match,
            "total_ep": self.total_ep,
            "current_ep": self.current_ep,
            "total": self.total,
            "lack": self.lack,
            "state": self.state,
            "desc": self.description,
            "note": self.note,
        }


@dataclass
class SubscribeTvEpisodeEntity:
    """订阅剧集分集实体"""

    id: int
    subscribe_id: str
    episodes: str

    @classmethod
    def from_orm(cls, orm_model) -> Optional["SubscribeTvEpisodeEntity"]:
        if orm_model is None:
            return None
        return cls(id=orm_model.ID, subscribe_id=orm_model.RSSID or "", episodes=orm_model.EPISODES or "")

    # 从 ORM 列名到 dataclass 字段名的映射
    _ORM_FIELD_MAP = {
        "desc": "description",
    }

    def __getattr__(self, name: str):
        """兼容旧代码的大写属性访问（如 entity.ID -> entity.id）"""
        lower_name = name.lower()
        # 检查是否是 ORM 列名映射
        field_name = self._ORM_FIELD_MAP.get(lower_name, lower_name)
        if field_name in {f.name for f in fields(self)}:
            return getattr(self, field_name)
        raise AttributeError(f"'{self.__class__.__name__}' object has no attribute '{name}'")

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "rssid": self.subscribe_id,
            "episodes": self.episodes,
        }
