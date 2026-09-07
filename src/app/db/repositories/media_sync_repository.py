"""
媒体同步 Repository
处理媒体库同步相关的数据库操作
"""

import time

from app.db.models import MEDIASYNCITEMS, MEDIASYNCSTATISTIC
from app.db.repositories.base_repository import BaseRepository
from app.utils.json_utils import JsonUtils


class MediaSyncRepository(BaseRepository):
    """
    媒体同步数据仓储
    处理 MEDIASYNCITEMS 和 MEDIASYNCSTATISTIC 的数据库操作
    """

    def insert_item(self, server_type: str, iteminfo: dict, seasoninfo: list | None = None) -> bool:
        """
        插入/更新媒体同步项目
        id 类字段统一转 str：MEDIASYNC_ITEMS 对应列为 varchar，PostgreSQL 不允许隐式转换
        """
        if not server_type or not iteminfo:
            return False

        item_id = str(iteminfo.get("id") or "")
        tmdb_id = str(iteminfo.get("tmdbid") or "") if iteminfo.get("tmdbid") is not None else ""
        imdb_id = str(iteminfo.get("imdbid") or "") if iteminfo.get("imdbid") is not None else ""
        year = str(iteminfo.get("year") or "") if iteminfo.get("year") is not None else ""

        with self.session() as db:
            db.query(MEDIASYNCITEMS).filter(
                MEDIASYNCITEMS.SERVER == server_type,
                MEDIASYNCITEMS.ITEM_ID == item_id,
            ).delete()

            new_item = MEDIASYNCITEMS(
                SERVER=server_type,
                LIBRARY=iteminfo.get("library") or "",
                ITEM_ID=item_id,
                ITEM_TYPE=iteminfo.get("type") or "",
                TITLE=iteminfo.get("title") or "",
                ORGIN_TITLE=iteminfo.get("originalTitle") or "",
                YEAR=year,
                TMDBID=tmdb_id,
                IMDBID=imdb_id,
                PATH=iteminfo.get("path") or "",
                NOTE=iteminfo.get("note") or "",
                JSON=JsonUtils.dumps(seasoninfo) if seasoninfo is not None else "",
            )
            db.add(new_item)
            db.commit()
            return True

    def empty_items(self, server_type: str | None = None, library: str | None = None) -> bool:
        """
        清空媒体同步项目
        """
        with self.session() as db:
            query = db.query(MEDIASYNCITEMS)
            if server_type and library:
                query = query.filter(
                    MEDIASYNCITEMS.SERVER == server_type,
                    MEDIASYNCITEMS.LIBRARY == library,
                )
            elif server_type:
                query = query.filter(MEDIASYNCITEMS.SERVER == server_type)
            query.delete()
            db.commit()
            return True

    def save_statistics(self, server_type: str, total_count: int, movie_count: int, tv_count: int) -> bool:
        """
        保存媒体同步统计
        """
        if not server_type:
            return False

        with self.session() as db:
            db.query(MEDIASYNCSTATISTIC).filter(MEDIASYNCSTATISTIC.SERVER == server_type).delete()

            new_stat = MEDIASYNCSTATISTIC(
                SERVER=server_type,
                TOTAL_COUNT=str(total_count),
                MOVIE_COUNT=str(movie_count),
                TV_COUNT=str(tv_count),
                UPDATE_TIME=time.strftime("%Y-%m-%d %H:%M:%S", time.localtime()),
            )
            db.add(new_stat)
            db.commit()
            return True

    def query_item(self, server_type: str, title: str, year: str | None = None, tmdbid: str | None = None):
        """
        查询媒体同步项目
        列 TMDBID/YEAR 为 varchar：入参统一转 str，避免 PostgreSQL 下 varchar = integer 报错
        """
        if not server_type or not title:
            return None
        if tmdbid is not None:
            tmdbid = str(tmdbid)
        if year is not None:
            year = str(year)

        with self.session() as db:
            query = db.query(MEDIASYNCITEMS).filter(MEDIASYNCITEMS.SERVER == server_type)

            if tmdbid:
                item = query.filter(MEDIASYNCITEMS.TMDBID == tmdbid).first()
                if item:
                    return item

            if year:
                item = query.filter(
                    MEDIASYNCITEMS.TITLE == title,
                    MEDIASYNCITEMS.YEAR == year,
                ).first()
            else:
                item = query.filter(MEDIASYNCITEMS.TITLE == title).first()

            return item

    def get_statistics(self, server_type: str):
        """
        获取媒体同步统计
        """
        if not server_type:
            return None
        with self.session() as db:
            return db.query(MEDIASYNCSTATISTIC).filter(MEDIASYNCSTATISTIC.SERVER == server_type).first()
