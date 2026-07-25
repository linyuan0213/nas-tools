"""
Search Repository
Handles search result related database operations.
"""

import random
from datetime import datetime, timedelta, timezone

from sqlalchemy import inspect
from sqlalchemy.dialects.mysql import insert as mysql_insert
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.dialects.sqlite import insert as sqlite_insert

from app.db.models import SEARCHRESULTINFO
from app.db.repositories.base_repository import BaseRepository
from app.domain.mediatypes import MediaType
from app.utils.json_utils import JsonUtils


class SearchRepository(BaseRepository):
    """
    搜索结果仓储
    处理搜索结果的数据库操作
    """

    def insert_search_results(self, media_items: list, title=None, ident_flag=True, session_id: str | None = None):
        """
        将返回信息插入数据库
        使用 UPSERT 语义：先删除同 session 冲突记录，再批量插入

        Args:
            media_items: 媒体信息列表
            title: 标题（用于非识别模式）
            ident_flag: 是否已识别标识
            session_id: 搜索会话 ID（用于多用户隔离）
        """
        if not media_items:
            return

        with self.session() as db:
            # 清空旧数据：按 session 隔离，避免并发覆盖
            if session_id:
                db.query(SEARCHRESULTINFO).filter(SEARCHRESULTINFO.SEARCH_SESSION_ID == session_id).delete(
                    synchronize_session=False
                )
            else:
                db.query(SEARCHRESULTINFO).delete(synchronize_session=False)

            mappings = []
            for media_item in media_items:
                if media_item.type == MediaType.TV:
                    mtype = MediaType.TV.value
                elif media_item.type == MediaType.MOVIE:
                    mtype = MediaType.MOVIE.value
                else:
                    mtype = MediaType.ANIME.value

                # 截断超长 ENCLOSURE：去掉磁力链接中多余的 tracker，只保留核心 btih
                enclosure = media_item.enclosure or ""
                if enclosure and enclosure.startswith("magnet:"):
                    enclosure = enclosure.split("&")[0]
                elif enclosure and len(enclosure) > 4000:
                    enclosure = enclosure[:4000]

                mapping = {
                    "TORRENT_NAME": media_item.org_string or "",
                    "ENCLOSURE": enclosure,
                    "DESCRIPTION": media_item.description or "",
                    "TYPE": mtype if ident_flag else "",
                    "TITLE": (media_item.title if ident_flag else title) or "",
                    "YEAR": (media_item.year if ident_flag else "") or "",
                    "SEASON": (media_item.get_season_string() if ident_flag else "") or "",
                    "EPISODE": (media_item.get_episode_string() if ident_flag else "") or "",
                    "ES_STRING": (media_item.get_season_episode_string() if ident_flag else "") or "",
                    "VOTE": media_item.vote_average or "0",
                    "IMAGE": (media_item.get_backdrop_image(default=False, original=True) or ""),
                    "POSTER": (media_item.get_poster_image() or ""),
                    "TMDBID": media_item.tmdb_id or "",
                    "OVERVIEW": media_item.overview or "",
                    "RES_TYPE": JsonUtils.dumps(
                        {
                            "respix": media_item.resource_pix,
                            "restype": media_item.resource_type,
                            "reseffect": media_item.resource_effect,
                            "video_encode": media_item.video_encode,
                        }
                    ),
                    "RES_ORDER": media_item.res_order or "0",
                    "SIZE": int(media_item.size or 0),
                    "SEEDERS": int(media_item.seeders)
                    if media_item.seeders and str(media_item.seeders).strip().lstrip("-+").isdigit()
                    else 0,
                    "PEERS": int(media_item.peers)
                    if media_item.peers and str(media_item.peers).strip().lstrip("-+").isdigit()
                    else 0,
                    "SITE": media_item.site or "",
                    "SITE_ORDER": media_item.site_order or "0",
                    "PAGEURL": media_item.page_url or (enclosure[:200] if enclosure else ""),
                    "OTHERINFO": media_item.resource_team or "",
                    "UPLOAD_VOLUME_FACTOR": (
                        media_item.upload_volume_factor if media_item.upload_volume_factor is not None else 1.0
                    ),
                    "DOWNLOAD_VOLUME_FACTOR": (
                        media_item.download_volume_factor if media_item.download_volume_factor is not None else 1.0
                    ),
                    "NOTE": "|".join(media_item.labels)
                    if isinstance(media_item.labels, list)
                    else (media_item.labels or ""),
                }
                if session_id:
                    mapping["SEARCH_SESSION_ID"] = session_id
                mapping["CREATED_AT"] = datetime.now(timezone.utc).replace(tzinfo=None)
                mappings.append(mapping)

            # 按 DB 唯一约束 (PAGEURL, SITE, SEARCH_SESSION_ID) 去重
            # MySQL 唯一键为 PAGEURL 前缀索引（191 字符），其余库使用完整列
            dialect = inspect(db.bind).dialect.name
            pageurl_prefix = 191 if dialect == "mysql" else None
            deduped = {}
            for m in mappings:
                pageurl_key = m["PAGEURL"][:pageurl_prefix] if pageurl_prefix else m["PAGEURL"]
                key = (pageurl_key, m["SITE"], m.get("SEARCH_SESSION_ID"))
                deduped[key] = m
            mappings = list(deduped.values())

            if not mappings:
                return

            if dialect == "mysql":
                stmt = mysql_insert(SEARCHRESULTINFO).values(mappings)
                stmt = stmt.on_duplicate_key_update(
                    TORRENT_NAME=stmt.inserted.TORRENT_NAME,
                    ENCLOSURE=stmt.inserted.ENCLOSURE,
                    DESCRIPTION=stmt.inserted.DESCRIPTION,
                    SIZE=stmt.inserted.SIZE,
                    SEEDERS=stmt.inserted.SEEDERS,
                    PEERS=stmt.inserted.PEERS,
                )
                db.execute(stmt)
            elif dialect == "postgresql":
                stmt = pg_insert(SEARCHRESULTINFO).values(mappings)
                stmt = stmt.on_conflict_do_update(
                    constraint="uq_search_pageurl_site_session",
                    set_={
                        "TORRENT_NAME": stmt.excluded.TORRENT_NAME,
                        "ENCLOSURE": stmt.excluded.ENCLOSURE,
                        "SIZE": stmt.excluded.SIZE,
                        "SEEDERS": stmt.excluded.SEEDERS,
                        "PEERS": stmt.excluded.PEERS,
                    },
                )
                db.execute(stmt)
            else:
                stmt = sqlite_insert(SEARCHRESULTINFO).values(mappings)
                stmt = stmt.on_conflict_do_update(
                    index_elements=["PAGEURL", "SITE", "SEARCH_SESSION_ID"],
                    set_={
                        "TORRENT_NAME": stmt.excluded.TORRENT_NAME,
                        "ENCLOSURE": stmt.excluded.ENCLOSURE,
                        "SIZE": stmt.excluded.SIZE,
                        "SEEDERS": stmt.excluded.SEEDERS,
                        "PEERS": stmt.excluded.PEERS,
                    },
                )
                db.execute(stmt)
            db.commit()
            # 概率性清理：删除 24 小时以上的旧记录
            if random.random() < 0.1:
                cutoff = datetime.now(timezone.utc).replace(tzinfo=None) - timedelta(hours=24)
                deleted = (
                    db.query(SEARCHRESULTINFO)
                    .filter(SEARCHRESULTINFO.CREATED_AT < cutoff)
                    .delete(synchronize_session=False)
                )
                if deleted:
                    db.commit()

    def get_search_result_by_id(self, dl_id):
        """
        根据ID从数据库中查询搜索结果的一条记录
        """
        with self.session() as db:
            return db.query(SEARCHRESULTINFO).filter(dl_id == SEARCHRESULTINFO.ID).all()

    def get_search_results(self, session_id: str | None = None):
        with self.session() as db:
            query = db.query(SEARCHRESULTINFO)
            if session_id:
                query = query.filter(SEARCHRESULTINFO.SEARCH_SESSION_ID == session_id)
            else:
                return []
            return query.all()

    def delete_all_search_torrents(self):
        """
        删除所有搜索的记录（全局清理）
        """
        with self.session() as db:
            db.query(SEARCHRESULTINFO).delete()

    def delete_by_session(self, session_id: str):
        """
        按搜索会话删除记录
        """
        with self.session() as db:
            db.query(SEARCHRESULTINFO).filter(SEARCHRESULTINFO.SEARCH_SESSION_ID == session_id).delete(
                synchronize_session=False
            )
