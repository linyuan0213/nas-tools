"""
Site Repository
Handles site configuration and statistics related database operations.
"""

import contextlib
import datetime
import time

from sqlalchemy import Integer, cast, func

from app.db.models import CONFIGSITE, SITEFAVICON, SITESTATISTICSHISTORY, SITEUSERINFOSTATS, SITEUSERSEEDINGINFO
from app.db.repositories.base_repository import BaseRepository
from app.utils.json_utils import JsonUtils


class SiteRepository(BaseRepository):
    """
    站点仓储
    处理站点配置、统计、图标、做种数据的数据库操作
    """

    # ==================== Site Configuration ====================

    def get_config_site(self) -> list[CONFIGSITE]:
        """
        查询所有站点信息
        """
        with self.session() as db:
            return db.query(CONFIGSITE).order_by(cast(CONFIGSITE.PRI, Integer).asc()).all()

    def get_site_by_id(self, tid: int) -> list[CONFIGSITE]:
        """
        查询1个站点信息
        """
        with self.session() as db:
            return db.query(CONFIGSITE).filter(int(tid) == CONFIGSITE.ID).all()

    def insert_config_site(
        self,
        name: str,
        site_pri: str,
        rssurl: str | None = None,
        signurl: str | None = None,
        cookie: str | None = None,
        api_key: str | None = None,
        bearer_token: str | None = None,
        headers: str | None = None,
        note: str | None = None,
        rss_uses: str | None = None,
    ) -> None:
        """
        插入站点信息
        """
        if not name:
            return
        with self.session() as db:
            db.add(
                CONFIGSITE(
                    NAME=name,
                    PRI=site_pri,
                    RSSURL=rssurl,
                    SIGNURL=signurl,
                    COOKIE=cookie,
                    API_KEY=api_key,
                    BEARER_TOKEN=bearer_token,
                    HEADERS=headers,
                    NOTE=note,
                    INCLUDE=rss_uses,
                )
            )

    def delete_config_site(self, tid: int | None) -> None:
        """
        删除站点信息
        """
        if not tid:
            return
        with self.session() as db:
            db.query(CONFIGSITE).filter(int(tid) == CONFIGSITE.ID).delete()

    def update_config_site(
        self,
        tid: int | None,
        name: str,
        site_pri: str,
        rssurl: str,
        signurl: str,
        cookie: str,
        api_key: str | None = None,
        bearer_token: str | None = None,
        headers: str | None = None,
        note: str | None = None,
        rss_uses: str | None = None,
    ) -> None:
        """
        更新站点信息
        """
        if not tid:
            return
        with self.session() as db:
            db.query(CONFIGSITE).filter(int(tid) == CONFIGSITE.ID).update(
                {
                    "NAME": name,
                    "PRI": site_pri,
                    "RSSURL": rssurl,
                    "SIGNURL": signurl,
                    "COOKIE": cookie,
                    "API_KEY": api_key,
                    "BEARER_TOKEN": bearer_token,
                    "HEADERS": headers,
                    "NOTE": note,
                    "INCLUDE": rss_uses,
                }
            )

    def update_config_site_note(self, tid: int | None, note: str) -> None:
        """
        更新站点属性
        """
        if not tid:
            return
        with self.session() as db:
            db.query(CONFIGSITE).filter(int(tid) == CONFIGSITE.ID).update({"NOTE": note})

    def update_site_cookie_ua(self, tid: int | None, cookie: str, ua: str | None = None) -> None:
        """
        更新站点Cookie和ua
        """
        if not tid:
            return
        with self.session() as db:
            rec = db.query(CONFIGSITE).filter(int(tid) == CONFIGSITE.ID).first()
            if rec.NOTE:
                note = JsonUtils.loads(rec.NOTE)
                if ua:
                    note["ua"] = ua
            else:
                note = {}
            db.query(CONFIGSITE).filter(int(tid) == CONFIGSITE.ID).update(
                {"COOKIE": cookie, "NOTE": JsonUtils.dumps(note)}
            )

    def update_site_rssurl(self, tid: int | None, rssurl: str) -> None:
        """
        更新站点rssurl
        """
        if not tid:
            return
        with self.session() as db:
            db.query(CONFIGSITE).filter(int(tid) == CONFIGSITE.ID).update({"RSSURL": rssurl})

    # ==================== Site User Statistics ====================

    def update_site_user_statistics_site_name(self, new_name: str, old_name: str) -> None:
        """
        更新站点用户数据中站点名称
        """
        with self.session() as db:
            db.query(SITEUSERINFOSTATS).filter(old_name == SITEUSERINFOSTATS.SITE).update({"SITE": new_name})

    def update_site_user_statistics(self, site_user_infos: list) -> None:
        """
        更新站点用户粒度数据
        """
        if not site_user_infos:
            return
        # 按 URL 去重，保留最后一个
        seen = {}
        for info in site_user_infos:
            seen[info.site_url] = info
        site_user_infos = list(seen.values())
        update_at = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(time.time()))

        if not site_user_infos:
            return

        urls = [info.site_url for info in site_user_infos]
        with self.session() as db:
            existing_rows = {
                row.URL: row for row in db.query(SITEUSERINFOSTATS).filter(SITEUSERINFOSTATS.URL.in_(urls)).all()
            }

            for info in site_user_infos:
                row = existing_rows.get(info.site_url)
                if row is None:
                    db.add(
                        SITEUSERINFOSTATS(
                            SITE=info.site_name,
                            USERNAME=info.username,
                            USER_LEVEL=info.user_level,
                            JOIN_AT=info.join_at or "",
                            UPDATE_AT=update_at,
                            UPLOAD=info.upload,
                            DOWNLOAD=info.download,
                            RATIO=info.ratio,
                            SEEDING=info.seeding,
                            LEECHING=info.leeching,
                            SEEDING_SIZE=info.seeding_size,
                            BONUS=info.bonus,
                            URL=info.site_url,
                            MSG_UNREAD=info.message_unread,
                        )
                    )
                else:
                    row.SITE = info.site_name
                    if info.username is not None:
                        row.USERNAME = info.username
                    if info.user_level is not None:
                        row.USER_LEVEL = info.user_level
                    if info.join_at is not None:
                        row.JOIN_AT = info.join_at
                    row.UPDATE_AT = update_at
                    row.UPLOAD = info.upload
                    row.DOWNLOAD = info.download
                    row.RATIO = info.ratio
                    row.SEEDING = info.seeding
                    row.LEECHING = info.leeching
                    row.SEEDING_SIZE = info.seeding_size
                    row.BONUS = info.bonus
                    row.MSG_UNREAD = info.message_unread

    def is_exists_site_user_statistics(self, url: str) -> bool:
        """
        判断站点数据是否存在
        使用first()代替count()提高性能
        """
        if not url:
            return False
        with self.session() as db:
            return db.query(SITEUSERINFOSTATS).filter(url == SITEUSERINFOSTATS.URL).first() is not None

    def is_site_user_statistics_exists(self, url: str) -> bool:
        """
        判断站点用户数据是否存在
        """
        if not url:
            return False
        with self.session() as db:
            return db.query(SITEUSERINFOSTATS).filter(url == SITEUSERINFOSTATS.URL).first() is not None

    def get_site_user_statistics(self, num: int = 100, strict_urls: list | None = None) -> list[SITEUSERINFOSTATS]:
        """
        查询站点数据历史
        """
        with self.session() as db:
            if strict_urls:
                return (
                    db.query(SITEUSERINFOSTATS)
                    .join(CONFIGSITE, SITEUSERINFOSTATS.SITE == CONFIGSITE.NAME)
                    .filter(SITEUSERINFOSTATS.URL.in_(tuple(strict_urls + ["__DUMMY__"])))
                    .order_by(cast(CONFIGSITE.PRI, Integer).asc())
                    .limit(num)
                    .all()
                )
            else:
                return db.query(SITEUSERINFOSTATS).limit(num).all()

    # ==================== Site Favicon ====================

    def update_site_favicon(self, site_user_infos: list) -> None:
        """
        更新站点图标数据
        """
        if not site_user_infos:
            return
        # 按 URL 去重，保留最后一个
        seen = {}
        for info in site_user_infos:
            seen[info.site_url] = info
        site_user_infos = list(seen.values())

        with self.session() as db:
            for site_user_info in site_user_infos:
                if site_user_info.site_favicon:
                    fav = site_user_info.site_favicon
                    if fav.startswith("data:"):
                        site_icon = fav
                    elif fav.startswith("http"):
                        site_icon = f"/img/favicon/external/{fav}"
                    else:
                        site_icon = "data:image/ico;base64," + fav
                else:
                    site_icon = (
                        "/img/favicon/"
                        + site_user_info.site_url.replace("https://", "").replace("http://", "").split("/")[0]
                    )

                if not self.is_exists_site_favicon(site_user_info.site_name):
                    db.add(SITEFAVICON(SITE=site_user_info.site_name, URL=site_user_info.site_url, FAVICON=site_icon))
                elif site_user_info.site_favicon:
                    db.query(SITEFAVICON).filter(site_user_info.site_name == SITEFAVICON.SITE).update(
                        {"URL": site_user_info.site_url, "FAVICON": site_icon}
                    )

    def is_exists_site_favicon(self, site: str) -> bool:
        """
        判断站点图标是否存在
        """
        with self.session() as db:
            count = db.query(SITEFAVICON).filter(site == SITEFAVICON.SITE).count()
            return count > 0

    def get_site_favicons(self, site: str | None = None) -> list[SITEFAVICON]:
        """
        查询站点图标数据
        """
        with self.session() as db:
            if site:
                return db.query(SITEFAVICON).filter(site == SITEFAVICON.SITE).all()
            else:
                return db.query(SITEFAVICON).all()

    # ==================== Site Seeding Info ====================

    def update_site_seed_info_site_name(self, new_name: str, old_name: str) -> None:
        """
        更新站点做种数据中站点名称
        """
        with self.session() as db:
            db.query(SITEUSERSEEDINGINFO).filter(old_name == SITEUSERSEEDINGINFO.SITE).update({"SITE": new_name})

    def update_site_seed_info(self, site_user_infos: list) -> None:
        """
        更新站点做种数据
        """
        if not site_user_infos:
            return
        # 按 URL 去重，保留最后一个
        seen = {}
        for info in site_user_infos:
            seen[info.site_url] = info
        site_user_infos = list(seen.values())
        update_at = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(time.time()))

        with self.session() as db:
            for site_user_info in site_user_infos:
                if not self.is_site_seeding_info_exist(url=site_user_info.site_url):
                    db.add(
                        SITEUSERSEEDINGINFO(
                            SITE=site_user_info.site_name,
                            UPDATE_AT=update_at,
                            SEEDING_INFO=site_user_info.seeding_info,
                            URL=site_user_info.site_url,
                        )
                    )
                else:
                    db.query(SITEUSERSEEDINGINFO).filter(site_user_info.site_url == SITEUSERSEEDINGINFO.URL).update(
                        {
                            "SITE": site_user_info.site_name,
                            "UPDATE_AT": update_at,
                            "SEEDING_INFO": site_user_info.seeding_info,
                        }
                    )

    def is_site_seeding_info_exist(self, url: str) -> bool:
        """
        判断做种数据是否已存在
        """
        with self.session() as db:
            return db.query(SITEUSERSEEDINGINFO).filter(url == SITEUSERSEEDINGINFO.URL).first() is not None

    def get_site_seeding_info(self, site: str) -> tuple | None:
        """
        查询站点做种信息
        """
        with self.session() as db:
            return db.query(SITEUSERSEEDINGINFO.SEEDING_INFO).filter(site == SITEUSERSEEDINGINFO.SITE).first()

    # ==================== Site Statistics History ====================

    def is_site_statistics_history_exists(self, url: str, date: str) -> bool:
        """
        判断站点历史数据是否存在
        """
        if not url or not date:
            return False
        with self.session() as db:
            return (
                db.query(SITESTATISTICSHISTORY)
                .filter(url == SITESTATISTICSHISTORY.URL, date == SITESTATISTICSHISTORY.DATE)
                .first()
                is not None
            )

    def update_site_statistics_site_name(self, new_name: str, old_name: str) -> None:
        """
        更新站点统计数据中站点名称
        """
        with self.session() as db:
            db.query(SITESTATISTICSHISTORY).filter(old_name == SITESTATISTICSHISTORY.SITE).update({"SITE": new_name})

    def insert_site_statistics_history(self, site_user_infos: list) -> None:
        """
        插入站点数据
        使用批量插入/更新提高性能

        精确统计前一天/当天：每日第一个快照（00:05 日界）作为当天历史基准，
        后续周期刷新只更新实时表 SITE_USER_INFO_STATS，不再覆盖当天历史行。
        这样 前一天增量 = 当天日界值 - 前一天日界值（自然日），
            当天增量 = 实时值 - 当天日界值。
        """
        if not site_user_infos:
            return

        date_now = time.strftime("%Y-%m-%d", time.localtime(time.time()))

        with self.session() as db:
            urls = [info.site_url for info in site_user_infos if info.site_url]
            existing_records = {}
            if urls:
                records = (
                    db.query(SITESTATISTICSHISTORY.URL)
                    .filter(date_now == SITESTATISTICSHISTORY.DATE, SITESTATISTICSHISTORY.URL.in_(urls))
                    .all()
                )
                existing_records = {r[0] for r in records}

            insert_mappings = []

            for site_user_info in site_user_infos:
                if site_user_info.site_url in existing_records:
                    # 当天已存在日界快照，跳过不覆盖，保持前一天/当天边界精确
                    continue
                data = {
                    "SITE": site_user_info.site_name,
                    "USER_LEVEL": site_user_info.user_level or "",
                    "DATE": date_now,
                    "UPLOAD": site_user_info.upload,
                    "DOWNLOAD": site_user_info.download,
                    "RATIO": site_user_info.ratio,
                    "SEEDING": site_user_info.seeding,
                    "LEECHING": site_user_info.leeching,
                    "SEEDING_SIZE": site_user_info.seeding_size,
                    "BONUS": site_user_info.bonus,
                    "URL": site_user_info.site_url,
                }
                insert_mappings.append(data)

            if insert_mappings:
                db.bulk_insert_mappings(SITESTATISTICSHISTORY, insert_mappings)
                db.commit()

    def get_site_statistics_history(self, site: str, days: int = 30) -> list[SITESTATISTICSHISTORY]:
        """
        查询站点数据历史
        """
        with self.session() as db:
            return (
                db.query(SITESTATISTICSHISTORY)
                .filter(site == SITESTATISTICSHISTORY.SITE)
                .order_by(SITESTATISTICSHISTORY.DATE.asc())
                .limit(days)
            )

    def get_site_statistics_recent_sites(
        self, days: int = 7, end_day: str | None = None, strict_urls: list | None = None
    ) -> tuple[int, int, list, list, list]:
        """
        查询近期上传下载量
        """
        if strict_urls is None:
            strict_urls = []
        end = datetime.datetime.now()
        if end_day:
            with contextlib.suppress(Exception):
                end = datetime.datetime.strptime(end_day, "%Y-%m-%d")

        b_date = (end - datetime.timedelta(days=days)).strftime("%Y-%m-%d")
        e_date = end.strftime("%Y-%m-%d")

        with self.session() as db:
            date_ret = (
                db.query(func.max(SITESTATISTICSHISTORY.DATE), func.min(SITESTATISTICSHISTORY.DATE))
                .filter(b_date < SITESTATISTICSHISTORY.DATE, e_date >= SITESTATISTICSHISTORY.DATE)
                .all()
            )

            if date_ret and date_ret[0][0]:
                total_upload = 0
                total_download = 0
                ret_site_uploads = []
                ret_site_downloads = []
                min_date = date_ret[0][1]
                max_date = date_ret[0][0]

                if strict_urls:
                    subquery = (
                        db.query(
                            SITESTATISTICSHISTORY.SITE.label("SITE"),
                            SITESTATISTICSHISTORY.DATE.label("DATE"),
                            func.sum(SITESTATISTICSHISTORY.UPLOAD).label("UPLOAD"),
                            func.sum(SITESTATISTICSHISTORY.DOWNLOAD).label("DOWNLOAD"),
                        )
                        .filter(
                            min_date <= SITESTATISTICSHISTORY.DATE,
                            max_date >= SITESTATISTICSHISTORY.DATE,
                            SITESTATISTICSHISTORY.URL.in_(tuple(strict_urls + ["__DUMMY__"])),
                        )
                        .group_by(SITESTATISTICSHISTORY.SITE, SITESTATISTICSHISTORY.DATE)
                        .subquery()
                    )
                else:
                    subquery = (
                        db.query(
                            SITESTATISTICSHISTORY.SITE.label("SITE"),
                            SITESTATISTICSHISTORY.DATE.label("DATE"),
                            func.sum(SITESTATISTICSHISTORY.UPLOAD).label("UPLOAD"),
                            func.sum(SITESTATISTICSHISTORY.DOWNLOAD).label("DOWNLOAD"),
                        )
                        .filter(min_date <= SITESTATISTICSHISTORY.DATE, max_date >= SITESTATISTICSHISTORY.DATE)
                        .group_by(SITESTATISTICSHISTORY.SITE, SITESTATISTICSHISTORY.DATE)
                        .subquery()
                    )

                rets = (
                    db.query(
                        subquery.c.SITE,
                        func.min(subquery.c.UPLOAD),
                        func.min(subquery.c.DOWNLOAD),
                        func.max(subquery.c.UPLOAD),
                        func.max(subquery.c.DOWNLOAD),
                    )
                    .group_by(subquery.c.SITE)
                    .all()
                )

                ret_sites = []
                for ret_b in rets:
                    ret_b = list(ret_b)
                    if ret_b[1] == 0 and ret_b[2] == 0:
                        ret_b[1] = ret_b[3]
                        ret_b[2] = ret_b[4]
                    ret_sites.append(ret_b[0])
                    if int(ret_b[1]) < int(ret_b[3]):
                        total_upload += int(ret_b[3]) - int(ret_b[1])
                        ret_site_uploads.append(int(ret_b[3]) - int(ret_b[1]))
                    else:
                        ret_site_uploads.append(0)
                    if int(ret_b[2]) < int(ret_b[4]):
                        total_download += int(ret_b[4]) - int(ret_b[2])
                        ret_site_downloads.append(int(ret_b[4]) - int(ret_b[2]))
                    else:
                        ret_site_downloads.append(0)

                return total_upload, total_download, ret_sites, ret_site_uploads, ret_site_downloads
            else:
                return 0, 0, [], [], []

    def get_site_daily_history(
        self, days: int = 30, end_day: str | None = None, strict_urls: list | None = None
    ) -> dict:
        """
        查询各站点每日上传量（按站点、按天分组，返回增量）
        """
        if strict_urls is None:
            strict_urls = []
        end = datetime.datetime.now()
        if end_day:
            with contextlib.suppress(Exception):
                end = datetime.datetime.strptime(end_day, "%Y-%m-%d")

        b_date = (end - datetime.timedelta(days=days)).strftime("%Y-%m-%d")
        e_date = end.strftime("%Y-%m-%d")

        with self.session() as db:
            # 按站点、日期分组，取每天的上传/下载总量
            query = db.query(
                SITESTATISTICSHISTORY.SITE,
                SITESTATISTICSHISTORY.DATE,
                func.sum(SITESTATISTICSHISTORY.UPLOAD).label("UPLOAD"),
                func.sum(SITESTATISTICSHISTORY.DOWNLOAD).label("DOWNLOAD"),
            ).filter(b_date < SITESTATISTICSHISTORY.DATE, e_date >= SITESTATISTICSHISTORY.DATE)

            if strict_urls:
                query = query.filter(SITESTATISTICSHISTORY.URL.in_(tuple(strict_urls + ["__DUMMY__"])))

            results = (
                query.group_by(SITESTATISTICSHISTORY.SITE, SITESTATISTICSHISTORY.DATE)
                .order_by(SITESTATISTICSHISTORY.DATE.asc())
                .all()
            )

            if not results:
                return {"dates": [], "series": []}

            # 按站点组织数据
            site_data: dict = {}
            all_dates = set()
            for row in results:
                site_name, date_str, upload, download = row
                all_dates.add(date_str)
                if site_name not in site_data:
                    site_data[site_name] = {}
                site_data[site_name][date_str] = {
                    "upload": int(upload or 0),
                    "download": int(download or 0),
                }

            sorted_dates = sorted(all_dates)

            # 计算每日增量
            series = []
            for site_name in sorted(site_data.keys()):
                uploads = []
                downloads = []
                prev_up = None
                prev_down = None
                for d in sorted_dates:
                    val = site_data[site_name].get(d)
                    if val is None:
                        # 当天无数据：增量为0，prev保持不变（避免下一天被0拉偏）
                        uploads.append(0)
                        downloads.append(0)
                        continue
                    up = val["upload"]
                    down = val["download"]
                    # 前值必须 > 0 才计算增量，避免首次数据/默认值 0 导致跳变
                    if prev_up is not None and prev_up > 0 and up >= prev_up:
                        inc_up = up - prev_up
                    else:
                        inc_up = 0
                    if prev_down is not None and prev_down > 0 and down >= prev_down:
                        inc_down = down - prev_down
                    else:
                        inc_down = 0
                    uploads.append(inc_up)
                    downloads.append(inc_down)
                    prev_up = up
                    prev_down = down
                series.append(
                    {
                        "name": site_name,
                        "upload": uploads,
                        "download": downloads,
                    }
                )

            return {"dates": sorted_dates, "series": series}
