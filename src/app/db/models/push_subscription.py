"""Web Push 订阅表模型 — 存储浏览器的推送订阅（endpoint + 公钥）."""

from datetime import datetime

from sqlalchemy import DateTime, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.db.models.base import Base


class PushSubscription(Base):
    """浏览器 Web Push 订阅."""

    __tablename__ = "PUSH_SUBSCRIPTION"

    ID: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    ENDPOINT: Mapped[str] = mapped_column(Text, nullable=False)
    P256DH: Mapped[str] = mapped_column(String(255), nullable=False)
    AUTH: Mapped[str] = mapped_column(String(255), nullable=False)
    USER_ID: Mapped[str] = mapped_column(String(64), nullable=False, default="")
    CREATED_AT: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=datetime.now)
