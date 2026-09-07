"""Web Push 订阅领域 Repository 适配器."""

from app.db.repositories.push_subscription_repository import PushSubscriptionRepository
from app.domain.entities.push_subscription import PushSubscriptionEntity
from app.domain.interfaces.push_subscription_repo import IPushSubscriptionRepository


class PushSubscriptionRepositoryAdapter(IPushSubscriptionRepository):
    """推送订阅仓储适配器."""

    def __init__(self, repo: PushSubscriptionRepository | None = None):
        self._repo = repo or PushSubscriptionRepository()

    def upsert(self, endpoint: str, p256dh: str, auth: str, user_id: str = "") -> None:
        self._repo.upsert(endpoint=endpoint, p256dh=p256dh, auth=auth, user_id=user_id)

    def delete_by_endpoint(self, endpoint: str) -> bool:
        return self._repo.delete_by_endpoint(endpoint)

    def list_all(self) -> list[PushSubscriptionEntity]:
        rows = self._repo.list_all()
        return [e for e in (PushSubscriptionEntity.from_orm(r) for r in rows) if e is not None]
