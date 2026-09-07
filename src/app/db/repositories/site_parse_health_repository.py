"""站点解析健康度仓储."""

from typing import Any

from app.db.models import SiteParseHealth
from app.db.repositories.base_repository import BaseRepository


class SiteParseHealthRepository(BaseRepository):
    """SITE_PARSE_HEALTH 读写：每日 upsert、最近记录查询."""

    def upsert(self, site_id: int, check_date: str, data: dict[str, Any]) -> None:
        with self.session() as db:
            row = (
                db.query(SiteParseHealth)
                .filter(SiteParseHealth.SITE_ID == site_id, SiteParseHealth.CHECK_DATE == check_date)
                .first()
            )
            if row is None:
                row = SiteParseHealth(SITE_ID=site_id, SITE_NAME=data.get("site_name", ""), CHECK_DATE=check_date)
                db.add(row)
            row.SITE_NAME = data.get("site_name", row.SITE_NAME)
            row.STATUS = data.get("status", "ok")
            row.SAMPLE_COUNT = int(data.get("sample_count", 0))
            row.ATTR_OK = int(data.get("attr_ok", 0))
            row.ATTR_FAIL = int(data.get("attr_fail", 0))
            row.DETAIL = data.get("detail")
            db.commit()

    def latest(self, site_id: int) -> SiteParseHealth | None:
        with self.session() as db:
            return (
                db.query(SiteParseHealth)
                .filter(SiteParseHealth.SITE_ID == site_id)
                .order_by(SiteParseHealth.CHECK_DATE.desc(), SiteParseHealth.ID.desc())
                .first()
            )

    def latest_all(self) -> list[SiteParseHealth]:
        """各站点最近一条健康记录（按检查日期倒序取每站点首条）."""
        with self.session() as db:
            rows = (
                db.query(SiteParseHealth)
                .order_by(
                    SiteParseHealth.SITE_NAME,
                    SiteParseHealth.CHECK_DATE.desc(),
                    SiteParseHealth.ID.desc(),
                )
                .all()
            )
        seen: set[int] = set()
        result: list[SiteParseHealth] = []
        for row in rows:
            if row.SITE_ID in seen:
                continue
            seen.add(row.SITE_ID)
            result.append(row)
        return result

    def history(self, site_id: int, limit: int = 30) -> list[SiteParseHealth]:
        with self.session() as db:
            return (
                db.query(SiteParseHealth)
                .filter(SiteParseHealth.SITE_ID == site_id)
                .order_by(SiteParseHealth.CHECK_DATE.desc(), SiteParseHealth.ID.desc())
                .limit(limit)
                .all()
            )
