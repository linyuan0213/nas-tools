"""
Download Repository
Handles download history, settings and indexer statistics related database operations.
"""

import os.path
import time
from datetime import datetime, timedelta
from typing import Any

from sqlalchemy import Integer, and_, case, cast, func, tuple_

from app.db.models import DOWNLOADHISTORY, DOWNLOADSETTING, INDEXERSTATISTICS
from app.db.repositories.base_repository import BaseRepository
from app.db.repositories.episode_progress import contiguous_episodes


class DownloadRepository(BaseRepository):
    """
    下载历史和设置仓储
    处理下载历史、下载设置和索引器统计的数据库操作
    """

    # ==================== Download History ====================

    def is_exists_download_history(self, enclosure: str | None, downloader: str, download_id: str) -> bool:
        """
        查询下载历史是否存在，按 downloader + download_id 唯一键判断。
        """
        with self.session() as db:
            return (
                db.query(DOWNLOADHISTORY.ID)
                .filter(downloader == DOWNLOADHISTORY.DOWNLOADER, download_id == DOWNLOADHISTORY.DOWNLOAD_ID)
                .first()
                is not None
            )

    def is_exists_download_history_by_tmdb(self, tmdb_id: int | None, season_episode: str | None) -> bool:
        """
        查询下载历史是否存在，根据TMDB ID和季集信息
        """
        if not tmdb_id:
            return False

        with self.session() as db:
            query = db.query(DOWNLOADHISTORY.ID).filter(
                DOWNLOADHISTORY.TMDBID != "", cast(DOWNLOADHISTORY.TMDBID, Integer) == tmdb_id
            )

            if season_episode:
                query = query.filter(season_episode == DOWNLOADHISTORY.SE)

            return query.first() is not None

    def is_completed_download_history_by_tmdb(self, tmdb_id: int | str | None, season_episode: str | None) -> bool:
        """
        查询已完成的下载历史是否存在，根据TMDB ID和季集信息（仅匹配 STATE=completed）
        """
        if not tmdb_id:
            return False

        with self.session() as db:
            query = db.query(DOWNLOADHISTORY.ID).filter(
                DOWNLOADHISTORY.TMDBID != "",
                DOWNLOADHISTORY.STATE == "completed",
                cast(DOWNLOADHISTORY.TMDBID, Integer) == int(tmdb_id),
            )

            if season_episode:
                query = query.filter(season_episode == DOWNLOADHISTORY.SE)
            return query.first() is not None

    def get_contiguous_completed_episode_by_tmdb(
        self, tmdb_id: int | str | None, season: int | None, start: int = 1
    ) -> int:
        """
        查询某剧集某季已完成的下载历史中「从订阅起点 start 起连续」的最大集号（重订阅续订用）。
        解析逻辑见 episode_progress.contiguous_episodes。
        """
        if not tmdb_id:
            return 0
        with self.session() as db:
            rows = (
                db.query(DOWNLOADHISTORY.SE)
                .filter(
                    DOWNLOADHISTORY.TMDBID != "",
                    DOWNLOADHISTORY.STATE == "completed",
                    DOWNLOADHISTORY.TMDBID == str(tmdb_id),
                )
                .all()
            )
        return contiguous_episodes((se for (se,) in rows), int(season or 1), start=int(start or 1))

    def delete_download_history_by_tmdb(self, tmdb_id: int | str | None, season_prefix: str | None = None) -> int:
        """
        删除已完成的下载历史，根据TMDB ID和可选的季前缀（仅删除 STATE=completed，保留下载中的）
        """
        if not tmdb_id:
            return 0

        with self.session() as db:
            query = db.query(DOWNLOADHISTORY).filter(
                DOWNLOADHISTORY.TMDBID != "",
                DOWNLOADHISTORY.STATE == "completed",
                cast(DOWNLOADHISTORY.TMDBID, Integer) == int(tmdb_id),
            )

            if season_prefix:
                query = query.filter(DOWNLOADHISTORY.SE.like(f"{season_prefix}%"))

            count = query.count()
            query.delete(synchronize_session="fetch")
            db.commit()
            return count

    def insert_download_history(self, media_info: Any, downloader: str, download_id: str, save_dir: str) -> None:
        """
        新增下载历史
        """
        if not media_info:
            return
        # title 为空时，用 org_string 或 get_name() 回退，确保能写入历史
        title = media_info.title or media_info.get_name() or media_info.org_string
        if not title:
            return
        # 回填到 media_info，确保后续使用一致
        media_info.title = title

        # 截断超长 ENCLOSURE：去掉磁力链接中多余的 tracker，只保留核心 btih
        enclosure = media_info.enclosure
        if enclosure and enclosure.startswith("magnet:"):
            # 只保留 magnet:?xt=urn:btih:HASH 部分，去掉 &tr= tracker 列表
            core = enclosure.split("&")[0]
            enclosure = core
        elif enclosure and len(enclosure) > 4000:
            enclosure = enclosure[:4000]
        media_info.enclosure = enclosure

        with self.session() as db:
            if self.is_exists_download_history(enclosure=enclosure, downloader=downloader, download_id=download_id):
                db.query(DOWNLOADHISTORY).filter(
                    downloader == DOWNLOADHISTORY.DOWNLOADER,
                    download_id == DOWNLOADHISTORY.DOWNLOAD_ID,
                ).update(
                    {
                        "TITLE": media_info.title,
                        "YEAR": media_info.year or "",
                        "TYPE": media_info.type.value if media_info.type else "",
                        "TMDBID": media_info.tmdb_id or "",
                        "VOTE": media_info.vote_average or "",
                        "POSTER": media_info.get_poster_image() or "",
                        "OVERVIEW": media_info.overview or "",
                        "TORRENT": media_info.org_string,
                        "ENCLOSURE": media_info.enclosure or "",
                        "DESC": media_info.description or "",
                        "SITE": media_info.site or "",
                        "DOWNLOADER": downloader,
                        "DOWNLOAD_ID": download_id,
                        "SAVE_PATH": save_dir,
                        "SE": media_info.get_season_episode_string() or "",
                        "STATE": "downloading",
                        "DATE": time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(time.time())),
                    }
                )
            else:
                db.add(
                    DOWNLOADHISTORY(
                        TITLE=media_info.title,
                        YEAR=media_info.year or "",
                        TYPE=media_info.type.value if media_info.type else "",
                        TMDBID=media_info.tmdb_id or "",
                        VOTE=media_info.vote_average or "",
                        POSTER=media_info.get_poster_image() or "",
                        OVERVIEW=media_info.overview or "",
                        TORRENT=media_info.org_string,
                        ENCLOSURE=media_info.enclosure or "",
                        DESC=media_info.description or "",
                        DATE=time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(time.time())),
                        SITE=media_info.site or "",
                        DOWNLOADER=downloader,
                        DOWNLOAD_ID=download_id,
                        SAVE_PATH=save_dir,
                        SE=media_info.get_season_episode_string() or "",
                        STATE="downloading",
                    )
                )

    def get_download_history(
        self, date: str | None = None, hid: int | None = None, num: int = 30, page: int = 1
    ) -> list[DOWNLOADHISTORY]:
        """
        查询下载历史
        修复：使用标准 GROUP BY 语法兼容 MySQL/PostgreSQL
        """
        with self.session() as db:
            if hid:
                return db.query(DOWNLOADHISTORY).filter(int(hid) == DOWNLOADHISTORY.ID).all()

            # 使用子查询获取每个 TMDBID + SE 组合的最大日期，而非仅按 TITLE 聚合
            sub_query = (
                db.query(DOWNLOADHISTORY.TMDBID, DOWNLOADHISTORY.SE, func.max(DOWNLOADHISTORY.DATE).label("max_date"))
                .group_by(DOWNLOADHISTORY.TMDBID, DOWNLOADHISTORY.SE)
                .subquery()
            )

            if date:
                return (
                    db.query(DOWNLOADHISTORY)
                    .filter(date < DOWNLOADHISTORY.DATE)
                    .join(
                        sub_query,
                        and_(
                            sub_query.c.TMDBID == DOWNLOADHISTORY.TMDBID,
                            sub_query.c.SE == DOWNLOADHISTORY.SE,
                            sub_query.c.max_date == DOWNLOADHISTORY.DATE,
                        ),
                    )
                    .order_by(DOWNLOADHISTORY.DATE.desc())
                    .all()
                )
            else:
                offset = (int(page) - 1) * int(num)
                return (
                    db.query(DOWNLOADHISTORY)
                    .join(
                        sub_query,
                        and_(
                            sub_query.c.TMDBID == DOWNLOADHISTORY.TMDBID,
                            sub_query.c.SE == DOWNLOADHISTORY.SE,
                            sub_query.c.max_date == DOWNLOADHISTORY.DATE,
                        ),
                    )
                    .order_by(DOWNLOADHISTORY.DATE.desc())
                    .limit(num)
                    .offset(offset)
                    .all()
                )

    def get_download_history_by_title(self, title: str) -> list[DOWNLOADHISTORY]:
        with self.session() as db:
            return db.query(DOWNLOADHISTORY).filter(title == DOWNLOADHISTORY.TITLE).all()

    def get_download_history_by_path(self, path: str) -> DOWNLOADHISTORY | None:
        with self.session() as db:
            return (
                db.query(DOWNLOADHISTORY)
                .filter(os.path.normpath(path) == DOWNLOADHISTORY.SAVE_PATH)
                .order_by(DOWNLOADHISTORY.DATE.desc())
                .first()
            )

    def get_download_history_list_by_path(self, path: str) -> list[DOWNLOADHISTORY]:
        """按路径返回全部下载记录（聚合目录多条）."""
        with self.session() as db:
            return (
                db.query(DOWNLOADHISTORY)
                .filter(os.path.normpath(path) == DOWNLOADHISTORY.SAVE_PATH)
                .order_by(DOWNLOADHISTORY.DATE.desc())
                .all()
            )

    def count_download_history_by_path(self, path: str) -> int:
        with self.session() as db:
            return db.query(DOWNLOADHISTORY).filter(os.path.normpath(path) == DOWNLOADHISTORY.SAVE_PATH).count()

    def get_download_history_by_downloader(self, downloader: str, download_id: str) -> DOWNLOADHISTORY | None:
        """
        根据下载器查找下载历史
        """
        with self.session() as db:
            return (
                db.query(DOWNLOADHISTORY)
                .filter(downloader == DOWNLOADHISTORY.DOWNLOADER, download_id == DOWNLOADHISTORY.DOWNLOAD_ID)
                .order_by(DOWNLOADHISTORY.DATE.desc())
                .first()
            )

    def get_download_history_by_id(self, download_id: str) -> DOWNLOADHISTORY | None:
        """
        仅根据下载ID查找最新的下载历史记录
        """
        with self.session() as db:
            return (
                db.query(DOWNLOADHISTORY)
                .filter(download_id == DOWNLOADHISTORY.DOWNLOAD_ID)
                .order_by(DOWNLOADHISTORY.DATE.desc())
                .first()
            )

    def get_active_downloads(self, days: int = 30, limit: int = 500) -> list[DOWNLOADHISTORY]:
        """
        获取最近几天内的下载任务（包含 downloading 和 completed）。
        兼容迁移后 STATE 被设为 completed 但任务实际还在下载的情况，
        由上层根据下载器实时进度判断真实状态并回写。
        """
        cutoff = (datetime.now() - timedelta(days=days)).strftime("%Y-%m-%d %H:%M:%S")
        with self.session() as db:
            sub = (
                db.query(
                    DOWNLOADHISTORY.DOWNLOADER,
                    DOWNLOADHISTORY.DOWNLOAD_ID,
                    func.max(DOWNLOADHISTORY.ID).label("max_id"),
                )
                .filter(
                    DOWNLOADHISTORY.STATE.in_(["downloading", "completed"]),
                    DOWNLOADHISTORY.DATE >= cutoff,
                )
                .group_by(DOWNLOADHISTORY.DOWNLOADER, DOWNLOADHISTORY.DOWNLOAD_ID)
                .subquery()
            )
            return (
                db.query(DOWNLOADHISTORY)
                .join(sub, DOWNLOADHISTORY.ID == sub.c.max_id)
                .order_by(DOWNLOADHISTORY.DATE.desc())
                .limit(limit)
                .all()
            )

    def update_download_state(self, downloader: str, download_id: str, state: str) -> None:
        """
        更新下载任务状态
        """
        with self.session() as db:
            db.query(DOWNLOADHISTORY).filter(
                downloader == DOWNLOADHISTORY.DOWNLOADER,
                download_id == DOWNLOADHISTORY.DOWNLOAD_ID,
            ).update({"STATE": state})

    def batch_update_download_state(self, items: list[tuple[str, str, str]]) -> None:
        """
        批量更新下载任务状态
        :param items: [(downloader, download_id, state), ...]
        """
        if not items:
            return

        # 按 state 分组批量更新
        states_map: dict[str, list[tuple[str, str]]] = {}
        for downloader, download_id, state in items:
            states_map.setdefault(state, []).append((downloader, download_id))

        with self.session() as db:
            for state, id_pairs in states_map.items():
                db.query(DOWNLOADHISTORY).filter(
                    tuple_(DOWNLOADHISTORY.DOWNLOADER, DOWNLOADHISTORY.DOWNLOAD_ID).in_(id_pairs)
                ).update({"STATE": state}, synchronize_session=False)

    # ==================== Download Settings ====================

    def delete_download_setting(self, sid: int | None) -> None:
        """
        删除下载设置
        """
        if not sid:
            return
        with self.session() as db:
            db.query(DOWNLOADSETTING).filter(int(sid) == DOWNLOADSETTING.ID).delete()

    def get_download_setting(self, sid: int | None = None) -> list[DOWNLOADSETTING]:
        """
        查询下载设置
        """
        with self.session() as db:
            if sid:
                return db.query(DOWNLOADSETTING).filter(int(sid) == DOWNLOADSETTING.ID).all()
            return db.query(DOWNLOADSETTING).all()

    def update_download_setting(
        self,
        sid: int | None,
        name: str,
        category: str,
        tags: str,
        is_paused: int,
        upload_limit: float,
        download_limit: float,
        ratio_limit: float,
        seeding_time_limit: float,
        downloader: str,
    ) -> None:
        """
        设置下载设置
        """
        with self.session() as db:
            if sid:
                db.query(DOWNLOADSETTING).filter(int(sid) == DOWNLOADSETTING.ID).update(
                    {
                        "NAME": name,
                        "CATEGORY": category,
                        "TAGS": tags,
                        "IS_PAUSED": int(is_paused),
                        "UPLOAD_LIMIT": int(float(upload_limit or 0)),
                        "DOWNLOAD_LIMIT": int(float(download_limit or 0)),
                        "RATIO_LIMIT": int(round(float(ratio_limit or 0), 2) * 100),
                        "SEEDING_TIME_LIMIT": int(float(seeding_time_limit or 0)),
                        "DOWNLOADER": downloader,
                    }
                )
            else:
                db.add(
                    DOWNLOADSETTING(
                        NAME=name,
                        CATEGORY=category,
                        TAGS=tags,
                        IS_PAUSED=int(is_paused),
                        UPLOAD_LIMIT=int(float(upload_limit or 0)),
                        DOWNLOAD_LIMIT=int(float(download_limit or 0)),
                        RATIO_LIMIT=int(round(float(ratio_limit or 0), 2) * 100),
                        SEEDING_TIME_LIMIT=int(float(seeding_time_limit or 0)),
                        DOWNLOADER=downloader,
                        NOTE="",
                    )
                )

    # ==================== Indexer Statistics ====================

    def insert_indexer_statistics(self, indexer: str, itype: str, seconds: int, result: str) -> None:
        """
        插入索引器统计，同时清理7天前的旧记录
        """
        cutoff = (datetime.now() - timedelta(days=7)).strftime("%Y-%m-%d %H:%M:%S")
        with self.session() as db:
            db.add(
                INDEXERSTATISTICS(
                    INDEXER=indexer,
                    TYPE=itype,
                    SECONDS=seconds,
                    RESULT=result,
                    DATE=time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(time.time())),
                )
            )
            db.query(INDEXERSTATISTICS).filter(INDEXERSTATISTICS.DATE < cutoff).delete()

    def delete_all_indexer_statistics(self) -> None:
        """
        删除所有搜索的记录
        """
        with self.session() as db:
            db.query(INDEXERSTATISTICS).delete()

    def get_indexer_statistics(self, client_id: str, hours: int = 24) -> list[tuple]:
        """
        查询索引器统计（默认最近24小时）
        """
        cutoff = (datetime.now() - timedelta(hours=hours)).strftime("%Y-%m-%d %H:%M:%S")
        with self.session() as db:
            return (
                db.query(
                    INDEXERSTATISTICS.INDEXER,
                    func.count(INDEXERSTATISTICS.ID).label("TOTAL"),
                    func.sum(case((INDEXERSTATISTICS.RESULT == "N", 1), else_=0)).label("FAIL"),
                    func.sum(case((INDEXERSTATISTICS.RESULT == "Y", 1), else_=0)).label("SUCCESS"),
                    func.avg(INDEXERSTATISTICS.SECONDS).label("AVG"),
                )
                .filter(client_id == INDEXERSTATISTICS.TYPE, INDEXERSTATISTICS.DATE >= cutoff)
                .group_by(INDEXERSTATISTICS.INDEXER)
                .all()
            )
