"""站点解析健康度表模型 — 记录每日解析自检结果与刷流详情抓取失败率."""

from datetime import datetime

from sqlalchemy import DateTime, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.db.models.base import Base


class SiteParseHealth(Base):
    """站点解析健康度（每日一条）."""

    __tablename__ = "SITE_PARSE_HEALTH"
    __table_args__ = (UniqueConstraint("SITE_ID", "CHECK_DATE", name="ux_site_parse_date"),)

    ID: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    SITE_ID: Mapped[int] = mapped_column(Integer, nullable=False, index=True)
    SITE_NAME: Mapped[str] = mapped_column(String(64), nullable=False)
    CHECK_DATE: Mapped[str] = mapped_column(String(10), nullable=False)
    STATUS: Mapped[str] = mapped_column(String(16), nullable=False, default="ok")
    SAMPLE_COUNT: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    ATTR_OK: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    ATTR_FAIL: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    DETAIL: Mapped[str | None] = mapped_column(Text, nullable=True)
    CREATED_AT: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=datetime.now)
