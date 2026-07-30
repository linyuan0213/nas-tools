"""提取规则基类与编排器"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any, Callable, Pattern

from ..types import ExtractedElement, ParseContext


@dataclass
class ExtractionRule:
    """元数据提取规则"""

    name: str
    pattern: Pattern[str]
    category: str
    priority: int = 50
    consumes: bool = True
    confidence: float = 0.9
    stop: bool = False
    _extract_fn: Callable[[re.Match[str], str], dict[str, Any] | None] | None = field(
        default=None, repr=False
    )

    def extract(self, match: re.Match[str], text: str) -> dict[str, Any] | None:
        if self._extract_fn:
            return self._extract_fn(match, text)
        groups = match.groups()
        if len(groups) == 1:
            return {self.category: int(groups[0]) if groups[0].isdigit() else groups[0]}
        return {self.category: match.group(0)}


@dataclass
class RuleEngine:
    """规则引擎：按优先级顺序应用规则，管理文本消费"""

    rules: list[ExtractionRule] = field(default_factory=list)

    def add_rule(self, rule: ExtractionRule) -> None:
        self.rules.append(rule)
        self.rules.sort(key=lambda r: r.priority, reverse=True)

    def extract_all(self, text: str) -> list[ExtractedElement]:
        elements: list[ExtractedElement] = []
        consumed: list[tuple[int, int]] = []
        category_stop: set[str] = set()
        for rule in self.rules:
            if rule.category in category_stop:
                continue
            match = rule.pattern.search(text)
            if not match:
                continue
            start, end = match.span()
            if any(start < c_end and end > c_start for c_start, c_end in consumed):
                continue
            extracted = rule.extract(match, text)
            if not extracted:
                continue
            for key, value in extracted.items():
                elem = ExtractedElement(
                    category=key,
                    value=value,
                    confidence=rule.confidence,
                    rule_name=rule.name,
                    span=(start, end),
                    consumed=rule.consumes,
                )
                elements.append(elem)
            if rule.consumes:
                consumed.append((start, end))
            if rule.stop:
                category_stop.add(rule.category)
        return elements

    def apply(self, ctx: ParseContext) -> ParseContext:
        for elem in self.extract_all(ctx.text):
            ctx.add_element(elem)
            if elem.category == "episode":
                ctx.episode = elem.value
            elif elem.category == "season":
                ctx.season = elem.value
            elif elem.category == "year":
                ctx.year = str(elem.value)
            elif elem.category == "resolution":
                ctx.resolution = elem.value
            elif elem.category == "source":
                ctx.source = elem.value
            elif elem.category == "video_codec":
                ctx.video_codec = elem.value
            elif elem.category == "audio_codec":
                ctx.audio_codec = elem.value
            elif elem.category == "resource_team":
                ctx.resource_team = elem.value
            elif elem.category == "episode_title":
                ctx.episode_title = elem.value
            elif elem.category == "release_group":
                ctx.release_group = elem.value
        return ctx


def get_rule_engine() -> RuleEngine:
    from . import codec_rules, episode_rules, resolution_rules, season_rules, source_rules, year_rules

    engine = RuleEngine()
    for rule in season_rules.RULES:
        engine.add_rule(rule)
    for rule in episode_rules.RULES:
        engine.add_rule(rule)
    for rule in year_rules.RULES:
        engine.add_rule(rule)
    for rule in resolution_rules.RULES:
        engine.add_rule(rule)
    for rule in codec_rules.RULES:
        engine.add_rule(rule)
    for rule in source_rules.RULES:
        engine.add_rule(rule)
    return engine
