"""搜索意图端口 — 统一意图模型与解析器协议

全系统唯一的搜索意图表示，规则解析与 LLM 解析都归一到此模型。
由 services 层消费、agent 层实现（依赖倒置）。
"""

from typing import Protocol

from pydantic import BaseModel


class SearchIntent(BaseModel):
    """统一搜索意图模型"""

    keywords: str = ""
    media_type: str | None = None  # movie / tv / anime
    year: int | None = None
    season: int | None = None
    episode: int | None = None
    raw_text: str = ""
    is_specific: bool = False


class IntentResolver(Protocol):
    """意图解析端口"""

    def resolve(self, text: str) -> SearchIntent:
        """解析自然语言查询为统一意图模型"""
        ...
