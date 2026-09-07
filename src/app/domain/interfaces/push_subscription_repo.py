"""Web Push 订阅领域 Repository 接口."""

from typing import Protocol

from app.domain.entities.push_subscription import PushSubscriptionEntity


class IPushSubscriptionRepository(Protocol):
    """推送订阅仓储接口."""

    def upsert(self, endpoint: str, p256dh: str, auth: str, user_id: str = "") -> None: ...
    def delete_by_endpoint(self, endpoint: str) -> bool: ...
    def list_all(self) -> list[PushSubscriptionEntity]: ...
