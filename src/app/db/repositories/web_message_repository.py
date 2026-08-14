"""Web 消息仓储 — 通知/回复持久化（刷新/重启后恢复）"""

from datetime import datetime

from sqlalchemy import func

from app.db.models.agent_memory import AGENTWEBMESSAGE
from app.db.repositories.base_repository import BaseRepository
from app.db.web_visibility import visible_sql


class WebMessageRepository(BaseRepository):
    """Web 消息仓储（游标 = 自增 ID，单调递增）"""

    def max_cursor(self) -> int:
        """当前最大游标（fallback 序号接续基线）"""
        with self.session() as db:
            return db.query(func.max(AGENTWEBMESSAGE.ID)).scalar() or 0

    def add_message(
        self,
        user_id: str,
        kind: str,
        title: str,
        content: str,
        image: str = "",
        url: str = "",
        items: list | None = None,
    ) -> int:
        with self.session() as db:
            row = AGENTWEBMESSAGE(
                USER_ID=user_id,
                KIND=kind,
                TITLE=title or "",
                CONTENT=content or "",
                IMAGE=image or "",
                URL=url or "",
                ITEMS=items,
            )
            db.add(row)
            db.flush()
            return row.ID

    def history(self, user_id: str, limit: int = 50) -> list[dict]:
        """最近通知（全局 user_id='' + 本人）"""
        with self.session() as db:
            rows = (
                db.query(AGENTWEBMESSAGE)
                .filter(visible_sql(AGENTWEBMESSAGE.USER_ID, user_id))
                .order_by(AGENTWEBMESSAGE.ID.desc())
                .limit(limit)
                .all()
            )
        return [self._to_dict(r) for r in reversed(rows)]

    def after(self, cursor: int, user_id: str, limit: int = 50) -> list[dict]:
        """cursor 之后的消息（按用户过滤）"""
        with self.session() as db:
            rows = (
                db.query(AGENTWEBMESSAGE)
                .filter(
                    AGENTWEBMESSAGE.ID > cursor,
                    visible_sql(AGENTWEBMESSAGE.USER_ID, user_id),
                )
                .order_by(AGENTWEBMESSAGE.ID.asc())
                .limit(limit)
                .all()
            )
        return [self._to_dict(r) for r in rows]

    def unread_count(self, user_id: str) -> int:
        """当前用户未读消息数"""
        with self.session() as db:
            return (
                db.query(func.count(AGENTWEBMESSAGE.ID))
                .filter(
                    AGENTWEBMESSAGE.READ.is_(False),
                    visible_sql(AGENTWEBMESSAGE.USER_ID, user_id),
                )
                .scalar()
                or 0
            )

    def mark_read(self, user_id: str, ids: list[int] | None = None) -> int:
        """标记已读（ids 为空则全部已读），返回受影响条数"""
        with self.session() as db:
            q = db.query(AGENTWEBMESSAGE).filter(
                AGENTWEBMESSAGE.READ.is_(False),
                visible_sql(AGENTWEBMESSAGE.USER_ID, user_id),
            )
            if ids:
                q = q.filter(AGENTWEBMESSAGE.ID.in_(ids))
            count = q.update({AGENTWEBMESSAGE.READ: True, AGENTWEBMESSAGE.READ_AT: datetime.now()})
            db.commit()
            return count or 0

    @staticmethod
    def _to_dict(row: AGENTWEBMESSAGE) -> dict:
        created = row.CREATED_AT or datetime.now()
        return {
            "cursor": row.ID,
            "id": row.ID,
            "kind": row.KIND,
            "title": row.TITLE,
            "content": row.CONTENT,
            "image": row.IMAGE,
            "url": row.URL,
            "items": row.ITEMS or [],
            "user_id": row.USER_ID,
            "read": bool(row.READ),
            "time": created.strftime("%H:%M:%S"),
            "ts": created.timestamp(),
        }
