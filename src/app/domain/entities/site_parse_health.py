"""站点解析健康领域实体."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime


@dataclass
class SiteParseHealthEntity:
    """站点解析健康记录实体."""

    id: int
    site_id: int
    site_name: str
    check_date: str
    status: str
    sample_count: int
    attr_ok: int
    attr_fail: int
    detail: str | None
    created_at: datetime | None

    @classmethod
    def from_orm(cls, orm_model) -> SiteParseHealthEntity | None:
        if orm_model is None:
            return None
        return cls(
            id=getattr(orm_model, "ID", 0),
            site_id=getattr(orm_model, "SITE_ID", 0),
            site_name=getattr(orm_model, "SITE_NAME", "") or "",
            check_date=getattr(orm_model, "CHECK_DATE", "") or "",
            status=getattr(orm_model, "STATUS", "") or "",
            sample_count=getattr(orm_model, "SAMPLE_COUNT", 0) or 0,
            attr_ok=getattr(orm_model, "ATTR_OK", 0) or 0,
            attr_fail=getattr(orm_model, "ATTR_FAIL", 0) or 0,
            detail=getattr(orm_model, "DETAIL", None),
            created_at=getattr(orm_model, "CREATED_AT", None),
        )
