"""统一解析引擎内部类型定义"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class ExtractedElement:
    """从标题中提取的元数据元素"""

    category: str
    value: Any
    confidence: float = 0.9
    rule_name: str = ""
    span: tuple[int, int] = (0, 0)
    consumed: bool = False


@dataclass
class ParseContext:
    """解析过程中的可变上下文"""

    text: str
    elements: list[ExtractedElement] = field(default_factory=list)
    consumed_spans: list[tuple[int, int]] = field(default_factory=list)
    episode: int | list[int] | None = None
    season: int | list[int] | None = None
    year: str | None = None
    resolution: str | None = None
    source: str | None = None
    video_codec: str | None = None
    audio_codec: str | None = None
    resource_team: str | None = None
    episode_title: str | None = None
    release_group: str | None = None
    cn_name: str | None = None
    en_name: str | None = None
    jp_title: str | None = None

    def add_element(self, elem: ExtractedElement) -> None:
        self.elements.append(elem)
        if elem.consumed and elem.span != (0, 0):
            self.consumed_spans.append(elem.span)

    def get_elements(self, category: str) -> list[ExtractedElement]:
        return [e for e in self.elements if e.category == category]

    def has(self, category: str) -> bool:
        return any(e.category == category for e in self.elements)

    def remaining_text(self) -> str:
        if not self.consumed_spans:
            return self.text
        spans = sorted(self.consumed_spans)
        parts: list[str] = []
        prev_end = 0
        for start, end in spans:
            if start > prev_end:
                parts.append(self.text[prev_end:start])
            prev_end = max(prev_end, end)
        if prev_end < len(self.text):
            parts.append(self.text[prev_end:])
        return " ".join(p for p in parts if p.strip())

    def remaining_text_until(self, position: int) -> str:
        """返回 position 之前未消耗的剩余文本（用于季集号前的主标题切分）"""
        if position <= 0:
            return ""
        if not self.consumed_spans:
            return self.text[:position]
        spans = sorted(s for s in self.consumed_spans if s[0] < position)
        parts: list[str] = []
        prev_end = 0
        for start, end in spans:
            if start > prev_end:
                parts.append(self.text[prev_end:start])
            prev_end = max(prev_end, end)
        if prev_end < position:
            parts.append(self.text[prev_end:position])
        return " ".join(p for p in parts if p.strip())


@dataclass
class ExtractionResult:
    """单次提取规则的结果"""

    matched: bool
    value: Any = None
    confidence: float = 0.9
    span: tuple[int, int] = (0, 0)
    remaining: str = ""
