"""
RSS相关模型
包含: 订阅历史、订阅电影、订阅种子、订阅剧集、订阅剧集分集
"""

from typing import Any

from sqlalchemy import Index, Integer, Sequence, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.db.models.base import Base


class SubscribeHistory(Base):
    __tablename__ = "SUBSCRIBE_HISTORY"

    ID: Mapped[int] = mapped_column(Integer, Sequence("ID"), primary_key=True)
    TYPE: Mapped[str] = mapped_column(String(255))
    RSSID: Mapped[str] = mapped_column(String(255), index=True)
    NAME: Mapped[str] = mapped_column(String(255))
    YEAR: Mapped[str] = mapped_column(String(255))
    TMDBID: Mapped[str] = mapped_column(String(255))
    SEASON: Mapped[str] = mapped_column(String(255))
    IMAGE: Mapped[str] = mapped_column(String(255))
    DESC: Mapped[str] = mapped_column(String(255))
    TOTAL: Mapped[int] = mapped_column(Integer)
    START: Mapped[int] = mapped_column(Integer)
    FINISH_TIME: Mapped[str] = mapped_column(String(255))
    NOTE: Mapped[str] = mapped_column(Text)

    def as_dict(self) -> dict[str, Any]:
        return {c.name: getattr(self, c.name) for c in self.__table__.columns}


class SubscribeMovies(Base):
    __tablename__ = "SUBSCRIBE_MOVIES"

    ID: Mapped[int] = mapped_column(Integer, Sequence("ID"), primary_key=True)
    NAME: Mapped[str] = mapped_column(String(255), index=True)
    YEAR: Mapped[str] = mapped_column(String(255), nullable=True)
    KEYWORD: Mapped[str] = mapped_column(String(255), nullable=True)
    TMDBID: Mapped[str] = mapped_column(String(255), index=True, nullable=True)
    IMAGE: Mapped[str] = mapped_column(String(255), nullable=True)
    RSS_SITES: Mapped[str] = mapped_column(String(255), nullable=True)
    SEARCH_SITES: Mapped[str] = mapped_column(String(255), nullable=True)
    OVER_EDITION: Mapped[int] = mapped_column(Integer, nullable=True)
    FILTER_ORDER: Mapped[int] = mapped_column(Integer, nullable=True)
    FILTER_RESTYPE: Mapped[str] = mapped_column(String(255), nullable=True)
    FILTER_PIX: Mapped[str] = mapped_column(String(255), nullable=True)
    FILTER_RULE: Mapped[int] = mapped_column(Integer, nullable=True)
    FILTER_TEAM: Mapped[str] = mapped_column(String(255), nullable=True)
    FILTER_INCLUDE: Mapped[str] = mapped_column(Text, nullable=True)
    FILTER_EXCLUDE: Mapped[str] = mapped_column(Text, nullable=True)
    FILTER_FREE: Mapped[int] = mapped_column(Integer, nullable=True)
    SAVE_PATH: Mapped[str] = mapped_column(String(255), nullable=True)
    DOWNLOAD_SETTING: Mapped[int] = mapped_column(Integer, nullable=True)
    FUZZY_MATCH: Mapped[int] = mapped_column(Integer, nullable=True)
    STATE: Mapped[str] = mapped_column(String(255), index=True, nullable=True)
    DESC: Mapped[str] = mapped_column(String(255), nullable=True)
    NOTE: Mapped[str] = mapped_column(Text, nullable=True)
    ADD_DATE: Mapped[str | None] = mapped_column(String(255), nullable=True)

    def as_dict(self) -> dict[str, Any]:
        return {c.name: getattr(self, c.name) for c in self.__table__.columns}


class SubscribeTorrents(Base):
    __tablename__ = "SUBSCRIBE_TORRENTS"
    __table_args__ = (Index("INDX_SUBSCRIBE_TORRENTS_NAME", "TITLE", "YEAR", "SEASON", "EPISODE"),)

    ID: Mapped[int] = mapped_column(Integer, Sequence("ID"), primary_key=True)
    TORRENT_NAME: Mapped[str] = mapped_column(String(255))
    ENCLOSURE: Mapped[str] = mapped_column(String(8192))
    TYPE: Mapped[str] = mapped_column(String(255))
    TITLE: Mapped[str] = mapped_column(String(255))
    YEAR: Mapped[str] = mapped_column(String(10))
    SEASON: Mapped[str] = mapped_column(String(10))
    EPISODE: Mapped[str] = mapped_column(String(10))


class SubscribeTvs(Base):
    __tablename__ = "SUBSCRIBE_TVS"

    ID: Mapped[int] = mapped_column(Integer, Sequence("ID"), primary_key=True)
    NAME: Mapped[str] = mapped_column(String(255), index=True)
    YEAR: Mapped[str] = mapped_column(String(255), nullable=True)
    KEYWORD: Mapped[str] = mapped_column(String(255), nullable=True)
    SEASON: Mapped[str] = mapped_column(String(255), nullable=True)
    TMDBID: Mapped[str] = mapped_column(String(255), index=True, nullable=True)
    IMAGE: Mapped[str] = mapped_column(String(255), nullable=True)
    RSS_SITES: Mapped[str] = mapped_column(String(255), nullable=True)
    SEARCH_SITES: Mapped[str] = mapped_column(String(255), nullable=True)
    OVER_EDITION: Mapped[int] = mapped_column(Integer, nullable=True)
    FILTER_ORDER: Mapped[int] = mapped_column(Integer, nullable=True)
    FILTER_RESTYPE: Mapped[str] = mapped_column(String(255), nullable=True)
    FILTER_PIX: Mapped[str] = mapped_column(String(255), nullable=True)
    FILTER_RULE: Mapped[int] = mapped_column(Integer, nullable=True)
    FILTER_TEAM: Mapped[str] = mapped_column(String(255), nullable=True)
    FILTER_INCLUDE: Mapped[str] = mapped_column(Text, nullable=True)
    FILTER_EXCLUDE: Mapped[str] = mapped_column(Text, nullable=True)
    FILTER_FREE: Mapped[int] = mapped_column(Integer, nullable=True)
    SAVE_PATH: Mapped[str] = mapped_column(String(255), nullable=True)
    DOWNLOAD_SETTING: Mapped[int] = mapped_column(Integer, nullable=True)
    FUZZY_MATCH: Mapped[int] = mapped_column(Integer, nullable=True)
    TOTAL_EP: Mapped[int] = mapped_column(Integer, nullable=True)
    CURRENT_EP: Mapped[int] = mapped_column(Integer, nullable=True)
    TOTAL: Mapped[int] = mapped_column(Integer, nullable=True)
    LACK: Mapped[int] = mapped_column(Integer, nullable=True)
    STATE: Mapped[str] = mapped_column(String(255), index=True, nullable=True)
    DESC: Mapped[str] = mapped_column(String(255), nullable=True)
    NOTE: Mapped[str] = mapped_column(Text, nullable=True)
    ADD_DATE: Mapped[str | None] = mapped_column(String(255), nullable=True)

    def as_dict(self) -> dict[str, Any]:
        return {c.name: getattr(self, c.name) for c in self.__table__.columns}


class SubscribeTvEpisodes(Base):
    __tablename__ = "SUBSCRIBE_TV_EPISODES"

    ID: Mapped[int] = mapped_column(Integer, Sequence("ID"), primary_key=True)
    RSSID: Mapped[str] = mapped_column(String(255), index=True)
    EPISODES: Mapped[str] = mapped_column(String(255))
