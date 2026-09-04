"""对话端口 — services 层消费、agent 层实现（依赖倒置）"""

from typing import Protocol


class ChatPort(Protocol):
    """对话能力端口（带工具调用的多轮对话）"""

    @property
    def ready(self) -> bool:
        """对话能力是否可用"""
        ...

    def chat_with_tools(
        self,
        question: str,
        session_id: str = "",
        channel: str = "web",
        user_id: str = "",
        user_permissions: list[str] | None = None,
    ) -> str:
        """带工具调用的对话（channel/user_permissions 由调用方按渠道语义传入）"""
        ...
