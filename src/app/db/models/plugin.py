"""
插件历史和TMDB黑名单模型
包含: 插件历史、TMDB黑名单、删种任务、自定义RSS任务历史、插件框架v2模型
"""

from datetime import datetime
from typing import Any

from sqlalchemy import Boolean, DateTime, Integer, Sequence, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.db.models.base import Base


class PLUGINHISTORY(Base):
    __tablename__ = "PLUGIN_HISTORY"

    ID: Mapped[int] = mapped_column(Integer, Sequence("ID"), primary_key=True)
    PLUGIN_ID: Mapped[str] = mapped_column(String(255), index=True)
    KEY: Mapped[str] = mapped_column(String(255), index=True)
    VALUE: Mapped[str] = mapped_column(String(255))
    DATE: Mapped[str] = mapped_column(String(255))


class TMDBBLACKLIST(Base):
    __tablename__ = "TMDB_BLACKLIST"

    ID: Mapped[int] = mapped_column(Integer, Sequence("ID"), primary_key=True)
    TMDB_ID: Mapped[str] = mapped_column(String(50), index=True)
    TITLE: Mapped[str] = mapped_column(String(255))
    YEAR: Mapped[str] = mapped_column(String(255))
    MEDIA_TYPE: Mapped[str] = mapped_column(String(255))
    POSTER_PATH: Mapped[str] = mapped_column(String(255))
    BACKDROP_PATH: Mapped[str] = mapped_column(String(255))
    NOTE: Mapped[str] = mapped_column(Text)

    def as_dict(self) -> dict[str, Any]:
        return {c.name: getattr(self, c.name) for c in self.__table__.columns}


class TORRENTREMOVETASK(Base):
    __tablename__ = "TORRENT_REMOVE_TASK"

    ID: Mapped[int] = mapped_column(Integer, Sequence("ID"), primary_key=True)
    NAME: Mapped[str] = mapped_column(String(255))
    ACTION: Mapped[int] = mapped_column(Integer)
    INTERVAL: Mapped[int] = mapped_column(Integer)
    ENABLED: Mapped[int] = mapped_column(Integer)
    SAMEDATA: Mapped[int] = mapped_column(Integer)
    ONLY_NEXUS_MEDIA: Mapped[int] = mapped_column(Integer)
    DOWNLOADER: Mapped[str] = mapped_column(String(255))
    CONFIG: Mapped[str] = mapped_column(Text)
    NOTE: Mapped[str | None] = mapped_column(Text, nullable=True)


class USERRSSTASKHISTORY(Base):
    __tablename__ = "USERRSS_TASK_HISTORY"

    ID: Mapped[int] = mapped_column(Integer, Sequence("ID"), primary_key=True)
    TASK_ID: Mapped[str] = mapped_column(String(255), index=True)
    TITLE: Mapped[str] = mapped_column(String(255))
    DOWNLOADER: Mapped[str] = mapped_column(String(255))
    DATE: Mapped[str] = mapped_column(String(255))


class PLUGINMANIFEST(Base):
    """插件框架v2 - 插件清单表"""

    __tablename__ = "PLUGIN_MANIFEST"

    ID: Mapped[str] = mapped_column(String(255), primary_key=True)
    NAME: Mapped[str] = mapped_column(String(255), nullable=False)
    VERSION: Mapped[str] = mapped_column(String(255), nullable=False)
    AUTHOR: Mapped[str] = mapped_column(String(255))
    DESCRIPTION: Mapped[str] = mapped_column(Text)
    CATEGORY: Mapped[str] = mapped_column(String(255), default="tool")
    TAGS: Mapped[str] = mapped_column(Text, default="[]")
    ICON: Mapped[str] = mapped_column(String(255))
    COLOR: Mapped[str] = mapped_column(String(255))
    MANIFEST_JSON: Mapped[str] = mapped_column(Text, nullable=False)
    INSTALLED_AT: Mapped[datetime] = mapped_column(DateTime, default=datetime.now)
    UPDATED_AT: Mapped[datetime] = mapped_column(DateTime, default=datetime.now, onupdate=datetime.now)
    ENABLED: Mapped[bool] = mapped_column(Boolean, default=False)
    INSTALLED: Mapped[bool] = mapped_column(Boolean, default=True)
    PATH: Mapped[str] = mapped_column(String(512), nullable=False)

    def as_dict(self) -> dict[str, Any]:
        return {c.name: getattr(self, c.name) for c in self.__table__.columns}


class PLUGINCONFIG(Base):
    """插件框架v2 - 插件配置表"""

    __tablename__ = "PLUGIN_CONFIG"

    PLUGIN_ID: Mapped[str] = mapped_column(String(255), primary_key=True)
    CONFIG: Mapped[str] = mapped_column(Text, nullable=False, default="{}")
    UPDATED_AT: Mapped[datetime] = mapped_column(DateTime, default=datetime.now, onupdate=datetime.now)

    def as_dict(self) -> dict[str, Any]:
        return {c.name: getattr(self, c.name) for c in self.__table__.columns}


class PLUGINLOGS(Base):
    """插件框架v2 - 插件日志表"""

    __tablename__ = "PLUGIN_LOGS"

    ID: Mapped[int] = mapped_column(Integer, Sequence("ID"), primary_key=True)
    PLUGIN_ID: Mapped[str] = mapped_column(String(255), nullable=False, index=True)
    LEVEL: Mapped[str] = mapped_column(String(50), nullable=False)
    MESSAGE: Mapped[str] = mapped_column(Text, nullable=False)
    CREATED_AT: Mapped[datetime] = mapped_column(DateTime, default=datetime.now)

    def as_dict(self) -> dict[str, Any]:
        return {c.name: getattr(self, c.name) for c in self.__table__.columns}


class PLUGINHOOKS(Base):
    """插件框架v2 - 插件Hook订阅表"""

    __tablename__ = "PLUGIN_HOOKS"

    ID: Mapped[int] = mapped_column(Integer, Sequence("ID"), primary_key=True)
    PLUGIN_ID: Mapped[str] = mapped_column(String(255), nullable=False, index=True)
    EVENT: Mapped[str] = mapped_column(String(255), nullable=False)
    ENABLED: Mapped[bool] = mapped_column(Boolean, default=True)

    def as_dict(self) -> dict[str, Any]:
        return {c.name: getattr(self, c.name) for c in self.__table__.columns}


class PLUGINMARKETSOURCE(Base):
    """插件框架v2 - 远程插件市场源表"""

    __tablename__ = "PLUGIN_MARKET_SOURCE"

    ID: Mapped[int] = mapped_column(Integer, Sequence("ID"), primary_key=True)
    SOURCE_ID: Mapped[str] = mapped_column(String(128), nullable=False, unique=True, index=True)
    NAME: Mapped[str] = mapped_column(String(255), nullable=False)
    URL: Mapped[str] = mapped_column(String(1024), nullable=False)
    PUBLIC_KEY: Mapped[str] = mapped_column(Text, default="")
    ENABLED: Mapped[int] = mapped_column(Integer, default=1)
    AUTO_UPDATE: Mapped[int] = mapped_column(Integer, default=0)
    LAST_SYNC_AT: Mapped[str] = mapped_column(String(64), default="")
    LAST_ERROR: Mapped[str] = mapped_column(Text, default="")

    def as_dict(self) -> dict[str, Any]:
        return {c.name: getattr(self, c.name) for c in self.__table__.columns}
