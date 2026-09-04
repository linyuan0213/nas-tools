"""Agent 会话/消息仓储 — 短程记忆持久化"""

from datetime import datetime, timedelta

from sqlalchemy.exc import IntegrityError

from app.db.models.agent_memory import AGENTCONVERSATION, AGENTMESSAGE
from app.db.repositories.base_repository import BaseRepository


class AgentConversationRepository(BaseRepository):
    """Agent 会话仓储"""

    def get_or_create(self, user_id: str, channel: str, session_id: str) -> AGENTCONVERSATION:
        with self.session() as db:
            conv = self._query_conversation(db, user_id, channel, session_id)
            if conv:
                return conv
            conv = AGENTCONVERSATION(USER_ID=user_id, CHANNEL=channel, SESSION_ID=session_id)
            db.add(conv)
            try:
                db.commit()
            except IntegrityError:
                # 并发下两请求同时创建 → 唯一约束冲突，回滚后重查
                db.rollback()
                conv = self._query_conversation(db, user_id, channel, session_id)
                if conv:
                    return conv
                raise
            db.refresh(conv)
            return conv

    def _query_conversation(self, db, user_id: str, channel: str, session_id: str) -> AGENTCONVERSATION | None:
        return (
            db.query(AGENTCONVERSATION)
            .filter(
                AGENTCONVERSATION.USER_ID == user_id,
                AGENTCONVERSATION.CHANNEL == channel,
                AGENTCONVERSATION.SESSION_ID == session_id,
            )
            .first()
        )

    def get(self, user_id: str, channel: str, session_id: str) -> AGENTCONVERSATION | None:
        with self.session() as db:
            return (
                db.query(AGENTCONVERSATION)
                .filter(
                    AGENTCONVERSATION.USER_ID == user_id,
                    AGENTCONVERSATION.CHANNEL == channel,
                    AGENTCONVERSATION.SESSION_ID == session_id,
                )
                .first()
            )

    def get_messages(self, conversation_id: int, limit: int = 50) -> list[AGENTMESSAGE]:
        """返回最早 limit 条消息（升序）——供滚动摘要归档使用"""
        with self.session() as db:
            return (
                db.query(AGENTMESSAGE)
                .filter(AGENTMESSAGE.CONVERSATION_ID == conversation_id)
                .order_by(AGENTMESSAGE.ID.asc())
                .limit(limit)
                .all()
            )

    def get_messages_latest(self, conversation_id: int, limit: int = 50) -> list[AGENTMESSAGE]:
        """返回最近 limit 条消息（内部按最新优先取数，返回升序），避免长会话取到最旧记录"""
        with self.session() as db:
            rows = (
                db.query(AGENTMESSAGE)
                .filter(AGENTMESSAGE.CONVERSATION_ID == conversation_id)
                .order_by(AGENTMESSAGE.ID.desc())
                .limit(limit)
                .all()
            )
            rows.reverse()
            return rows

    def append_message(
        self, conversation_id: int, role: str, content: str, tokens: int = 0, tool_calls: dict | None = None
    ) -> None:
        with self.session() as db:
            db.add(
                AGENTMESSAGE(
                    CONVERSATION_ID=conversation_id, ROLE=role, CONTENT=content, TOKENS=tokens, TOOL_CALLS=tool_calls
                )
            )
            db.query(AGENTCONVERSATION).filter(AGENTCONVERSATION.ID == conversation_id).update(
                {"UPDATED_AT": datetime.now()}
            )
            db.commit()

    def update_summary(self, conversation_id: int, summary: str, token_usage: int) -> None:
        with self.session() as db:
            db.query(AGENTCONVERSATION).filter(AGENTCONVERSATION.ID == conversation_id).update(
                {"SUMMARY": summary, "TOKEN_USAGE": token_usage, "UPDATED_AT": datetime.now()}
            )
            db.commit()

    def delete_messages_before(self, conversation_id: int, message_id: int) -> None:
        """摘要归档后删除已并入摘要的旧消息"""
        with self.session() as db:
            db.query(AGENTMESSAGE).filter(
                AGENTMESSAGE.CONVERSATION_ID == conversation_id, AGENTMESSAGE.ID <= message_id
            ).delete()
            db.commit()

    def delete_conversation(self, user_id: str, channel: str, session_id: str) -> None:
        with self.session() as db:
            conv = (
                db.query(AGENTCONVERSATION)
                .filter(
                    AGENTCONVERSATION.USER_ID == user_id,
                    AGENTCONVERSATION.CHANNEL == channel,
                    AGENTCONVERSATION.SESSION_ID == session_id,
                )
                .first()
            )
            if not conv:
                return
            db.query(AGENTMESSAGE).filter(AGENTMESSAGE.CONVERSATION_ID == conv.ID).delete()
            db.delete(conv)
            db.commit()

    def cleanup_expired(self, ttl_days: int) -> int:
        """删除超过 ttl_days 未更新的会话及其消息，返回清理的会话数"""
        if ttl_days <= 0:
            return 0
        cutoff = datetime.now() - timedelta(days=ttl_days)
        with self.session() as db:
            expired = db.query(AGENTCONVERSATION.ID).filter(AGENTCONVERSATION.UPDATED_AT < cutoff).all()
            ids = [c[0] for c in expired]
            if not ids:
                return 0
            db.query(AGENTMESSAGE).filter(AGENTMESSAGE.CONVERSATION_ID.in_(ids)).delete(synchronize_session=False)
            deleted = (
                db.query(AGENTCONVERSATION).filter(AGENTCONVERSATION.ID.in_(ids)).delete(synchronize_session=False)
            )
            db.commit()
            return deleted
