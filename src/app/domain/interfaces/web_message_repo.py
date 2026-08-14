"""Web 消息 Repository 接口（Python Protocol）

定义内置消息流持久化契约：通知/回复写入与按游标/用户读取。
"""

from typing import Protocol


class IWebMessageRepository(Protocol):
    """Web 消息仓储接口"""

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
        """写入一条消息，返回游标（自增 ID）"""
        ...

    def history(self, user_id: str, limit: int = 50) -> list[dict]:
        """最近通知历史（全局 + 本人），刷新恢复用"""
        ...

    def unread_list(self, user_id: str, limit: int = 50) -> list[dict]:
        """当前用户未读消息列表（通知栏下拉，轻量）"""
        ...

    def after(self, cursor: int, user_id: str, limit: int = 50) -> list[dict]:
        """游标之后的消息（按用户过滤），增量读取用"""
        ...

    def max_cursor(self) -> int:
        """当前最大游标（fallback 序号接续基线）"""
        ...
