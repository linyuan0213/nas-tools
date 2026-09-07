"""Web Push 订阅仓储."""

from app.db.models import PushSubscription
from app.db.repositories.base_repository import BaseRepository


class PushSubscriptionRepository(BaseRepository):
    """PUSH_SUBSCRIPTION 读写."""

    def upsert(self, endpoint: str, p256dh: str, auth: str, user_id: str = "") -> None:
        """按 endpoint 幂等保存订阅（同一浏览器重复订阅只更新密钥）."""
        with self.session() as db:
            row = db.query(PushSubscription).filter(PushSubscription.ENDPOINT == endpoint).first()
            if row is None:
                row = PushSubscription(ENDPOINT=endpoint, P256DH=p256dh, AUTH=auth, USER_ID=user_id or "")
                db.add(row)
            else:
                row.P256DH = p256dh  # type: ignore[assignment]
                row.AUTH = auth  # type: ignore[assignment]
                row.USER_ID = user_id or ""  # type: ignore[assignment]
            db.commit()

    def delete_by_endpoint(self, endpoint: str) -> bool:
        with self.session() as db:
            n = db.query(PushSubscription).filter(PushSubscription.ENDPOINT == endpoint).delete()
            db.commit()
            return n > 0

    def list_all(self) -> list[PushSubscription]:
        with self.session() as db:
            return db.query(PushSubscription).all()
