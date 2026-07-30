"""季数提取规则"""

from __future__ import annotations

import re

from .base import ExtractionRule

RULES: list[ExtractionRule] = [
    ExtractionRule(
        name="s_dash_s",
        pattern=re.compile(r"[Ss][Ee]?\s*(\d{1,2})\s*[-~]\s*[Ss][Ee]?\s*(\d{1,2})"),
        category="season",
        priority=95,
        confidence=0.9,
        stop=True,
        _extract_fn=lambda m, _: {"season": [int(m.group(1)), int(m.group(2))]},
    ),
    ExtractionRule(
        name="ordinal_season",
        pattern=re.compile(r"\b(\d+)(?:st|nd|rd|th)\s+Season\b", re.IGNORECASE),
        category="season",
        priority=94,
        confidence=0.9,
        stop=True,
    ),
    ExtractionRule(
        name="sxx_format",
        pattern=re.compile(r"\b[Ss](\d{1,2})\b(?!\s*[-~]\s*[SsEe]\s*\d)"),
        category="season",
        priority=90,
        confidence=0.9,
        stop=True,
    ),
    ExtractionRule(
        name="season_keyword",
        pattern=re.compile(r"\bSeason\s*(\d+)\b", re.IGNORECASE),
        category="season",
        priority=85,
        confidence=0.9,
        stop=True,
    ),
    ExtractionRule(
        name="chinese_season_range",
        pattern=re.compile(r"第\s*(\d+)\s*[-~]\s*(\d+)\s*季"),
        category="season",
        priority=82,
        confidence=0.85,
        stop=True,
        _extract_fn=lambda m, _: {"season": [int(m.group(1)), int(m.group(2))]},
    ),
    ExtractionRule(
        name="chinese_season",
        pattern=re.compile(r"第\s*(\d+)\s*季"),
        category="season",
        priority=80,
        confidence=0.85,
        stop=True,
    ),
    ExtractionRule(
        name="chinese_number_season",
        pattern=re.compile(r"第([一二三四五六七八九十百]+)季"),
        category="season",
        priority=75,
        confidence=0.85,
        stop=True,
        _extract_fn=lambda m, _: _cn2an_season(m),
    ),
    ExtractionRule(
        name="choume_season",
        pattern=re.compile(r"\b(\d)\s*[-~]?\s*(?:丁目|丁目|[Cc]houme)\b"),
        category="season",
        priority=78,
        confidence=0.85,
        stop=True,
    ),
    ExtractionRule(
        name="season_range",
        pattern=re.compile(r"[Ss](\d{1,2})[-~][Ss](\d{1,2})"),
        category="season",
        priority=70,
        confidence=0.85,
        _extract_fn=lambda m, _: {"season": [int(m.group(1)), int(m.group(2))]},
    ),
]


def _cn2an_season(match: re.Match[str]) -> dict[str, int] | None:
    import cn2an

    try:
        val = int(cn2an.cn2an(match.group(1), mode="smart"))
        return {"season": val}
    except Exception:
        return None
