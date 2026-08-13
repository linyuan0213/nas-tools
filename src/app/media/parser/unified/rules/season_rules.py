"""季数提取规则"""

from __future__ import annotations

import re

import cn2an

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
        name="roman_season",
        # 动漫常见季标：Unicode 罗马数字（Ⅲ）或拉丁罗马数字（III/IV 等），排除单个 I/V/X
        pattern=re.compile(r"\b([ⅠⅡⅢⅣⅤⅥⅦⅧⅨⅩⅪⅫ]|[IVX]{2,5})\b(?!\s*[-~]\s*[SsEe]\s*\d)"),
        category="season",
        priority=72,
        confidence=0.7,
        stop=True,
        _extract_fn=lambda m, _: {"season": _roman2num(m.group(1))},
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

    try:
        val = int(cn2an.cn2an(match.group(1), mode="smart"))
        return {"season": val}
    except Exception:
        return None


def _roman2num(s: str) -> int | None:
    """罗马数字转整数（Unicode Ⅰ-Ⅻ 或拉丁 IVX），无效返回 None."""
    unicode_map = {
        "Ⅰ": 1,
        "Ⅱ": 2,
        "Ⅲ": 3,
        "Ⅳ": 4,
        "Ⅴ": 5,
        "Ⅵ": 6,
        "Ⅶ": 7,
        "Ⅷ": 8,
        "Ⅸ": 9,
        "Ⅹ": 10,
        "Ⅺ": 11,
        "Ⅻ": 12,
    }
    if s in unicode_map:
        return unicode_map[s]
    table = {"I": 1, "V": 5, "X": 10, "L": 50, "C": 100}
    total, prev = 0, 0
    for ch in reversed(s.upper()):
        if ch not in table:
            return None
        v = table[ch]
        total += -v if v < prev else v
        prev = v
    return total if total > 0 else None
