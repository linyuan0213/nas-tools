"""Web Push 订阅领域实体."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass
class PushSubscriptionEntity:
    """浏览器推送订阅实体."""

    id: int
    endpoint: str
    p256dh: str
    auth: str
    user_id: str

    @classmethod
    def from_orm(cls, orm_model) -> PushSubscriptionEntity | None:
        if orm_model is None:
            return None
        return cls(
            id=getattr(orm_model, "ID", 0),
            endpoint=getattr(orm_model, "ENDPOINT", "") or "",
            p256dh=getattr(orm_model, "P256DH", "") or "",
            auth=getattr(orm_model, "AUTH", "") or "",
            user_id=getattr(orm_model, "USER_ID", "") or "",
        )
