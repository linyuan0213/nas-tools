"""Web 消息 Repository 适配器 — 实现领域接口，包装原始仓储"""

from app.db.repositories.web_message_repository import WebMessageRepository
from app.domain.interfaces.web_message_repo import IWebMessageRepository


class WebMessageRepositoryAdapter(IWebMessageRepository):
    """内置消息流持久化适配器"""

    def __init__(self, repo: WebMessageRepository | None = None):
        self._repo = repo or WebMessageRepository()

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
        return self._repo.add_message(user_id, kind, title, content, image, url, items)

    def history(self, user_id: str, limit: int = 50) -> list[dict]:
        return self._repo.history(user_id, limit)

    def unread_list(self, user_id: str, limit: int = 50) -> list[dict]:
        return self._repo.unread_list(user_id, limit)

    def after(self, cursor: int, user_id: str, limit: int = 50) -> list[dict]:
        return self._repo.after(cursor, user_id, limit)

    def max_cursor(self) -> int:
        return self._repo.max_cursor()

    def unread_count(self, user_id: str) -> int:
        return self._repo.unread_count(user_id)

    def mark_read(self, user_id: str, ids: list[int] | None = None) -> int:
        return self._repo.mark_read(user_id, ids)
