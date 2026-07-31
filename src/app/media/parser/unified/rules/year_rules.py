"""年份提取规则 — 含多候选消歧"""

from __future__ import annotations

import re

from .base import ExtractionRule

_R_YEAR = r"19\d{2}|20[0-2]\d|2030"

RULES: list[ExtractionRule] = [
    ExtractionRule(
        name="bracket_year",
        pattern=re.compile(rf"\[({_R_YEAR})\]"),
        category="year",
        priority=90,
        confidence=0.9,
    ),
    ExtractionRule(
        name="paren_year",
        pattern=re.compile(rf"\(({_R_YEAR})\)"),
        category="year",
        priority=85,
        confidence=0.9,
    ),
    ExtractionRule(
        name="bare_year_after_title",
        pattern=re.compile(r"(?<=[a-zA-Z)%])[.\s]+(" + _R_YEAR + r")\b"),
        category="year",
        priority=60,
        confidence=0.8,
    ),
    ExtractionRule(
        name="bare_year",
        pattern=re.compile(r"\b(" + _R_YEAR + r")\b"),
        category="year",
        priority=55,
        confidence=0.7,
    ),
]
