"""
Brush Repository
Handles brush task and torrent related database operations.
"""

import time
from typing import Any

from sqlalchemy import Integer, and_, case, cast, func, or_

from app.db.models import BRUSHEVENTLOG, CONFIGSITE, SITEBRUSHRULE, SITEBRUSHTASK, SITEBRUSHTORRENTS
from app.db.repositories.base_repository import BaseRepository
from app.domain.entities.brush import BrushTaskState
from app.utils.json_utils import JsonUtils


class BrushRepository(BaseRepository):
    """
    刷流任务仓储
    处理刷流任务和种子信息的数据库操作
    """

    def update_brushtask(self, brush_id: int | None, item: dict) -> None:
        """
        新增或更新刷流任务
        """
        with self.session() as db:
            if not brush_id:
                db.add(
                    SITEBRUSHTASK(
                        NAME=item.get("name"),
                        SITE=item.get("site"),
                        FREELEECH=item.get("free"),
                        RSS_RULE=JsonUtils.dumps(item.get("rss_rule"), ensure_ascii=False),
                        REMOVE_RULE=JsonUtils.dumps(item.get("remove_rule"), ensure_ascii=False),
                        STOP_RULE=JsonUtils.dumps(item.get("stop_rule"), ensure_ascii=False),
                        RSS_RULE_ID=item.get("rss_rule_id"),
                        REMOVE_RULE_ID=item.get("remove_rule_id"),
                        STOP_RULE_ID=item.get("stop_rule_id"),
                        SEED_SIZE=item.get("seed_size"),
                        TIME_RANGE=item.get("time_range"),
                        ACTIVE_WEEKDAYS=item.get("active_weekdays"),
                        DOWNLOAD_SWITCH=item.get("download_switch", "Y"),
                        REMOVE_SWITCH=item.get("remove_switch", "Y"),
                        STOP_SWITCH=item.get("stop_switch", "Y"),
                        DAILY_DELETE_LIMIT=item.get("daily_delete_limit", ""),
                        MAX_SEEDING=item.get("max_seeding", ""),
                        HR_LIMIT=item.get("hr_limit", ""),
                        RSSURL=item.get("rssurl"),
                        INTEVAL=item.get("interval"),
                        DOWNLOADER=item.get("downloader"),
                        LABEL=item.get("label"),
                        SAVEPATH=item.get("savepath"),
                        TRANSFER=item.get("transfer"),
                        DOWNLOAD_COUNT=0,
                        REMOVE_COUNT=0,
                        DOWNLOAD_SIZE=0,
                        UPLOAD_SIZE=0,
                        STATE=item.get("state"),
                        LST_MOD_DATE=time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(time.time())),
                        SENDMESSAGE=item.get("sendmessage"),
                    )
                )
            else:
                db.query(SITEBRUSHTASK).filter(int(brush_id) == SITEBRUSHTASK.ID).update(
                    {
                        "NAME": item.get("name"),
                        "SITE": item.get("site"),
                        "FREELEECH": item.get("free"),
                        "RSS_RULE": JsonUtils.dumps(item.get("rss_rule"), ensure_ascii=False),
                        "REMOVE_RULE": JsonUtils.dumps(item.get("remove_rule"), ensure_ascii=False),
                        "STOP_RULE": JsonUtils.dumps(item.get("stop_rule"), ensure_ascii=False),
                        "RSS_RULE_ID": item.get("rss_rule_id"),
                        "REMOVE_RULE_ID": item.get("remove_rule_id"),
                        "STOP_RULE_ID": item.get("stop_rule_id"),
                        "SEED_SIZE": item.get("seed_size"),
                        "TIME_RANGE": item.get("time_range"),
                        "ACTIVE_WEEKDAYS": item.get("active_weekdays"),
                        "DOWNLOAD_SWITCH": item.get("download_switch", "Y"),
                        "REMOVE_SWITCH": item.get("remove_switch", "Y"),
                        "STOP_SWITCH": item.get("stop_switch", "Y"),
                        "DAILY_DELETE_LIMIT": item.get("daily_delete_limit", ""),
                        "MAX_SEEDING": item.get("max_seeding", ""),
                        "HR_LIMIT": item.get("hr_limit", ""),
                        "RSSURL": item.get("rssurl"),
                        "INTEVAL": item.get("interval"),
                        "DOWNLOADER": item.get("downloader"),
                        "LABEL": item.get("label"),
                        "SAVEPATH": item.get("savepath"),
                        "TRANSFER": item.get("transfer"),
                        "STATE": item.get("state"),
                        "LST_MOD_DATE": time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(time.time())),
                        "SENDMESSAGE": item.get("sendmessage"),
                    }
                )

    def delete_brushtask(self, brush_id: int) -> None:
        """
        删除刷流任务
        """
        with self.session() as db:
            db.query(SITEBRUSHTASK).filter(int(brush_id) == SITEBRUSHTASK.ID).delete()
            db.query(SITEBRUSHTORRENTS).filter(cast(SITEBRUSHTORRENTS.TASK_ID, Integer) == brush_id).delete()
            db.query(BRUSHEVENTLOG).filter(cast(BRUSHEVENTLOG.TASK_ID, Integer) == brush_id).delete()

    def get_brushtasks(self, brush_id: int | None = None) -> SITEBRUSHTASK | None | list[SITEBRUSHTASK]:
        """
        查询刷流任务
        """
        with self.session() as db:
            if brush_id:
                return db.query(SITEBRUSHTASK).filter(int(brush_id) == SITEBRUSHTASK.ID).first()
            else:
                # LEFT JOIN：站点被删除或 ID 不匹配时任务仍须返回，
                # 否则重启后 load_brushtasks 查不到该任务（新建任务丢失）
                return (
                    db.query(SITEBRUSHTASK)
                    .outerjoin(CONFIGSITE, cast(SITEBRUSHTASK.SITE, Integer) == CONFIGSITE.ID)
                    .order_by(func.coalesce(cast(CONFIGSITE.PRI, Integer), 999999))
                    .all()
                )

    def get_brushtask_totalsize(self, brush_id: int | None) -> int:
        """
        查询刷流任务总体积
        """
        if not brush_id:
            return 0
        with self.session() as db:
            ret = (
                db.query(func.sum(cast(SITEBRUSHTORRENTS.TORRENT_SIZE, Integer)))
                .filter(
                    cast(SITEBRUSHTORRENTS.TASK_ID, Integer) == brush_id,
                    SITEBRUSHTORRENTS.DOWNLOAD_ID != "0",
                    SITEBRUSHTORRENTS.TORRENT_SIZE != "",
                    SITEBRUSHTORRENTS.TORRENT_SIZE.isnot(None),
                )
                .first()
            )
            return ret[0] or 0 if ret else 0

    def update_brushtask_site(self, brush_id: int, site_id: str) -> None:
        """修正刷流任务站点标识为 DB 主键 id（历史配置 id 数据迁移）."""
        with self.session() as db:
            db.query(SITEBRUSHTASK).filter(int(brush_id) == SITEBRUSHTASK.ID).update({"SITE": site_id})

    def update_brushtask_state(self, state: str, tid: int | None = None) -> None:
        """
        改变刷流任务的状态
        """
        normalized = BrushTaskState.from_value(state).value
        with self.session() as db:
            if tid:
                db.query(SITEBRUSHTASK).filter(int(tid) == SITEBRUSHTASK.ID).update({"STATE": normalized})
            else:
                db.query(SITEBRUSHTASK).update({"STATE": normalized})

    def add_brushtask_download_count(self, brush_id: int | None) -> None:
        """
        增加刷流下载数
        """
        if not brush_id:
            return
        with self.session() as db:
            db.query(SITEBRUSHTASK).filter(int(brush_id) == SITEBRUSHTASK.ID).update(
                {
                    "DOWNLOAD_COUNT": SITEBRUSHTASK.DOWNLOAD_COUNT + 1,
                    "LST_MOD_DATE": time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(time.time())),
                }
            )

    def get_brushtask_remove_size(self, brush_id: int | None) -> list[tuple]:
        """
        获取已删除种子的上传量
        """
        if not brush_id:
            return []
        with self.session() as db:
            return (
                db.query(SITEBRUSHTORRENTS.TORRENT_SIZE)
                .filter(cast(SITEBRUSHTORRENTS.TASK_ID, Integer) == brush_id, SITEBRUSHTORRENTS.DOWNLOAD_ID == "0")
                .all()
            )

    def add_brushtask_upload_count(
        self, brush_id: int | None, upload_size: int, download_size: int, remove_count: int
    ) -> None:
        """
        更新上传下载量和删除种子数
        """
        if not brush_id:
            return
        delete_upsize = 0
        delete_dlsize = 0
        remove_sizes = self.get_brushtask_remove_size(brush_id)
        for remove_size in remove_sizes:
            if not remove_size[0]:
                continue
            if str(remove_size[0]).find(",") != -1:
                sizes = str(remove_size[0]).split(",")
                delete_upsize += int(sizes[0] or 0)
                if len(sizes) > 1:
                    delete_dlsize += int(sizes[1] or 0)
            else:
                delete_upsize += int(remove_size[0])

        with self.session() as db:
            db.query(SITEBRUSHTASK).filter(int(brush_id) == SITEBRUSHTASK.ID).update(
                {
                    "REMOVE_COUNT": SITEBRUSHTASK.REMOVE_COUNT + remove_count,
                    "UPLOAD_SIZE": int(upload_size) + delete_upsize,
                    "DOWNLOAD_SIZE": int(download_size) + delete_dlsize,
                }
            )

    def insert_brushtask_torrent(
        self,
        brush_id: int | None,
        title: str,
        enclosure: str,
        downloader: str,
        download_id: str,
        size: str,
        page_url: str = "",
    ) -> None:
        """
        增加刷流下载的种子信息
        """
        if not brush_id:
            return
        if enclosure and enclosure.startswith("magnet:"):
            enclosure = enclosure.split("&")[0]
        elif enclosure and len(enclosure) > 4000:
            enclosure = enclosure[:4000]
        if self.is_brushtask_torrent_exists(brush_id, title, enclosure):
            return

        with self.session() as db:
            db.add(
                SITEBRUSHTORRENTS(
                    TASK_ID=brush_id,
                    TORRENT_NAME=title,
                    TORRENT_SIZE=size,
                    ENCLOSURE=enclosure,
                    DOWNLOADER=downloader,
                    DOWNLOAD_ID=download_id,
                    PAGE_URL=page_url or "",
                    LST_MOD_DATE=time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(time.time())),
                )
            )

    def get_brushtask_torrents(self, brush_id: int | None, active: bool = True) -> list[SITEBRUSHTORRENTS]:
        """
        查询刷流任务所有种子
        """
        if not brush_id:
            return []
        with self.session() as db:
            if active:
                return (
                    db.query(SITEBRUSHTORRENTS)
                    .filter(
                        cast(SITEBRUSHTORRENTS.TASK_ID, Integer) == int(brush_id), SITEBRUSHTORRENTS.DOWNLOAD_ID != "0"
                    )
                    .all()
                )
            else:
                return (
                    db.query(SITEBRUSHTORRENTS)
                    .filter(cast(SITEBRUSHTORRENTS.TASK_ID, Integer) == int(brush_id))
                    .order_by(SITEBRUSHTORRENTS.LST_MOD_DATE.desc())
                    .all()
                )

    def get_brushtask_torrent_by_enclosure(self, enclosure: str) -> SITEBRUSHTORRENTS | None:
        """
        根据URL精确查询刷流任务种子
        """
        if not enclosure:
            return None
        with self.session() as db:
            return (
                db.query(SITEBRUSHTORRENTS)
                .filter(
                    enclosure == SITEBRUSHTORRENTS.ENCLOSURE,
                    SITEBRUSHTORRENTS.DOWNLOAD_ID != "0",
                )
                .first()
            )

    def get_brushtask_torrents_by_domain(self, domain: str) -> list[SITEBRUSHTORRENTS]:
        """
        根据域名模糊查询刷流任务种子（供 tid-based dedup 使用）
        """
        if not domain:
            return []
        with self.session() as db:
            return (
                db.query(SITEBRUSHTORRENTS)
                .filter(
                    SITEBRUSHTORRENTS.ENCLOSURE.like(f"%{domain}%"),
                    SITEBRUSHTORRENTS.DOWNLOAD_ID != "0",
                )
                .all()
            )

    def is_brushtask_torrent_exists(self, brush_id: int | None, title: str, enclosure: str) -> bool:
        """
        查询刷流任务种子是否已存在
        """
        if not brush_id:
            return False
        with self.session() as db:
            count = (
                db.query(SITEBRUSHTORRENTS)
                .filter(
                    cast(SITEBRUSHTORRENTS.TASK_ID, Integer) == brush_id,
                    title == SITEBRUSHTORRENTS.TORRENT_NAME,
                    enclosure == SITEBRUSHTORRENTS.ENCLOSURE,
                    SITEBRUSHTORRENTS.DOWNLOAD_ID != "0",
                )
                .count()
            )
            return count > 0

    def update_brushtask_torrent_state(self, ids: list) -> None:
        """
        更新刷流种子的状态
        """
        if not ids:
            return
        with self.session() as db:
            conditions = [
                and_(cast(SITEBRUSHTORRENTS.TASK_ID, Integer) == task_id, SITEBRUSHTORRENTS.DOWNLOAD_ID == download_id)
                for _, task_id, download_id in ids
            ]
            case_stmt = case(
                *[(cond, torrent_size) for (_, torrent_size), cond in zip(ids, conditions)],
                else_=SITEBRUSHTORRENTS.TORRENT_SIZE,
            )
            db.query(SITEBRUSHTORRENTS).filter(or_(*conditions)).update(
                {"TORRENT_SIZE": case_stmt, "DOWNLOAD_ID": "0"}, synchronize_session=False
            )

    def delete_brushtask_torrent(self, brush_id: int | None, download_id: str | None) -> None:
        """
        删除刷流种子记录
        """
        if not download_id or not brush_id:
            return
        with self.session() as db:
            db.query(SITEBRUSHTORRENTS).filter(
                cast(SITEBRUSHTORRENTS.TASK_ID, Integer) == brush_id, download_id == SITEBRUSHTORRENTS.DOWNLOAD_ID
            ).delete()

    # ---------- 刷流规则模板 ----------

    def insert_brushrule(self, name: str, rule_type: str, json_rule: str) -> int:
        """新增刷流规则模板，返回自增 ID。"""
        with self.session() as db:
            entity = SITEBRUSHRULE(
                NAME=name,
                TYPE=rule_type,
                RSS_RULE=json_rule if rule_type == "rss" else "",
                REMOVE_RULE=json_rule if rule_type == "remove" else "",
                STOP_RULE=json_rule if rule_type == "stop" else "",
                LST_MOD_DATE=time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(time.time())),
            )
            db.add(entity)
            db.flush()
            return entity.ID

    def update_brushrule(
        self,
        rule_id: int,
        name: str | None,
        rule_type: str | None,
        json_rule: str | None,
    ) -> None:
        """更新刷流规则模板。"""
        updates: dict[str, Any] = {}
        if name is not None:
            updates["NAME"] = name
        if rule_type is not None:
            updates["TYPE"] = rule_type
            if rule_type == "rss":
                updates["RSS_RULE"] = json_rule or ""
            elif rule_type == "remove":
                updates["REMOVE_RULE"] = json_rule or ""
            elif rule_type == "stop":
                updates["STOP_RULE"] = json_rule or ""
        if updates:
            updates["LST_MOD_DATE"] = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(time.time()))
            with self.session() as db:
                db.query(SITEBRUSHRULE).filter(int(rule_id) == SITEBRUSHRULE.ID).update(updates)

    def get_brushrules(self, rule_id: int | None = None, rule_type: str | None = None):
        """查询刷流规则模板。"""
        with self.session() as db:
            if rule_id:
                return db.query(SITEBRUSHRULE).filter(int(rule_id) == SITEBRUSHRULE.ID).first()
            query = db.query(SITEBRUSHRULE).order_by(SITEBRUSHRULE.ID.desc())
            if rule_type:
                query = query.filter(SITEBRUSHRULE.TYPE == rule_type)
            return query.all()

    def delete_brushrule(self, rule_id: int) -> None:
        """删除刷流规则模板，并将关联任务的引用置空。"""
        with self.session() as db:
            for col in ["RSS_RULE_ID", "REMOVE_RULE_ID", "STOP_RULE_ID"]:
                db.query(SITEBRUSHTASK).filter(int(rule_id) == getattr(SITEBRUSHTASK, col)).update({col: None})
            db.query(SITEBRUSHRULE).filter(int(rule_id) == SITEBRUSHRULE.ID).delete()

    # ---------- 事件日志 ----------

    def insert_brush_event(
        self,
        task_id: int,
        task_name: str,
        torrent_name: str,
        download_id: str,
        action: str,
        reason: str,
        downloader_name: str = "",
        site_name: str = "",
        torrent_url: str = "",
    ) -> None:
        with self.session() as db:
            entity = BRUSHEVENTLOG(
                TASK_ID=task_id,
                TASK_NAME=task_name,
                TORRENT_NAME=torrent_name,
                DOWNLOAD_ID=download_id,
                ACTION=action,
                REASON=reason,
                DOWNLOADER_NAME=downloader_name,
                SITE_NAME=site_name,
                TORRENT_URL=torrent_url,
                CREATED_AT=time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(time.time())),
            )
            db.add(entity)

    def get_brush_events(
        self,
        task_id: int | None = None,
        action: str | None = None,
        page: int = 1,
        page_size: int = 50,
    ):
        with self.session() as db:
            query = db.query(BRUSHEVENTLOG)
            if task_id:
                query = query.filter(BRUSHEVENTLOG.TASK_ID == task_id)
            if action:
                query = query.filter(BRUSHEVENTLOG.ACTION == action)
            total = query.count()
            rows = query.order_by(BRUSHEVENTLOG.ID.desc()).offset((page - 1) * page_size).limit(page_size).all()
            return total, rows
