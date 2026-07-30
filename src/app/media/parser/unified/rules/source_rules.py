"""来源提取规则 — 覆盖 PT/BT 常见来源格式"""

from __future__ import annotations

import re

from .base import ExtractionRule

RULES: list[ExtractionRule] = [
    ExtractionRule(
        name="webdl",
        pattern=re.compile(r"\b(WEB[-\s.]?DL|WEB[-\s.]?RIP|WEB[-\s.]?DLRip|WEB[-\s.]?DLMux)\b", re.IGNORECASE),
        category="source",
        priority=95,
        confidence=0.9,
        _extract_fn=lambda m, _: {"source": "WEB-DL"},
    ),
    ExtractionRule(
        name="bluray_full",
        pattern=re.compile(r"\b(Blu[-\s.]?Ray|BD[-\s.]?Rip|BDRip|BDMV|BD25|BD50|BD66|BD100)\b", re.IGNORECASE),
        category="source",
        priority=92,
        confidence=0.9,
        _extract_fn=lambda m, _: {"source": "BluRay"},
    ),
    ExtractionRule(
        name="uhd_bluray",
        pattern=re.compile(r"\b(UHD[-\s.]?BluRay|UHD[-\s.]?BD|4K[-\s.]?UHD|4K[-\s.]?BluRay)\b", re.IGNORECASE),
        category="source",
        priority=91,
        confidence=0.9,
        _extract_fn=lambda m, _: {"source": "BluRay"},
    ),
    ExtractionRule(
        name="remux",
        pattern=re.compile(r"\b(REMUX|BD[-\s.]?Remux)\b", re.IGNORECASE),
        category="source",
        priority=88,
        confidence=0.9,
        _extract_fn=lambda m, _: {"source": "REMUX"},
    ),
    ExtractionRule(
        name="hdtv",
        pattern=re.compile(r"\b(HDTV|UHDTV|PDTV|DSR|DSRip|TVRip|SAT[-\s]?Rip|STV)\b", re.IGNORECASE),
        category="source",
        priority=85,
        confidence=0.9,
        _extract_fn=lambda m, _: {"source": "HDTV"},
    ),
    ExtractionRule(
        name="dvd",
        pattern=re.compile(
            r"\b(DVD[-\s.]?Rip|DVDRip|DVD[-\s.]?R\b|DVD[-\s.]?9|DVD5|DVDSCR|DVD[-\s.]?Screener)\b",
            re.IGNORECASE,
        ),
        category="source",
        priority=80,
        confidence=0.9,
        _extract_fn=lambda m, _: _dvd_normalize(m),
    ),
    ExtractionRule(
        name="theater_rip",
        pattern=re.compile(
            r"\b(HDTC|TC|TELESYNC|TeleSync|TELECINE|TeleCine|CAM|Camera|R5|R6|Screener|SCR)\b",
            re.IGNORECASE,
        ),
        category="source",
        priority=75,
        confidence=0.8,
        _extract_fn=lambda m, _: _theater_normalize(m),
    ),
    ExtractionRule(
        name="hddvd",
        pattern=re.compile(r"\b(HD[-]?DVD)\b", re.IGNORECASE),
        category="source",
        priority=78,
        confidence=0.9,
    ),
    ExtractionRule(
        name="bd",
        pattern=re.compile(r"\b(BD)\b(?![-]?(?:25|50|66|100|Rip|MV|Remux))"),
        category="source",
        priority=70,
        confidence=0.8,
        _extract_fn=lambda m, _: {"source": "BluRay"},
    ),
    ExtractionRule(
        name="webcast",
        pattern=re.compile(r"\b(WEB[-\s.]?Cast|WEB[-\s.]?TV)\b", re.IGNORECASE),
        category="source",
        priority=68,
        confidence=0.85,
        _extract_fn=lambda m, _: {"source": "WEB-DL"},
    ),
    ExtractionRule(
        name="streaming_sites",
        pattern=re.compile(r"\b(BILIBILI|Baha|B-Global|Crunchyroll|Funimation|Netflix|NF|AMZN|HMAX|DSNP|iQIYI|Tencent|YOUKU|friDay|LINETV|CATCHPLAY)\b", re.IGNORECASE),
        category="source",
        priority=66,
        confidence=0.85,
        _extract_fn=lambda m, _: {"source": "WEB-DL"},
    ),
]


def _dvd_normalize(m: re.Match[str]) -> dict[str, str]:
    val = m.group(0).upper().replace(" ", "").replace("-", "")
    if "SCR" in val or "SCREENER" in val:
        return {"source": "DVDScr"}
    return {"source": "DVDRip"}


def _theater_normalize(m: re.Match[str]) -> dict[str, str]:
    val = m.group(0).upper().replace(" ", "").replace("-", "")
    if "TC" in val and "HD" in val:
        return {"source": "HD-TC"}
    if "TC" in val or "TELESYNC" in val:
        return {"source": "TC"}
    if "TELECINE" in val:
        return {"source": "TeleCine"}
    if "SCR" in val or "SCREENER" in val:
        return {"source": "Screener"}
    if "CAM" in val:
        return {"source": "CAM"}
    if "R5" in val or "R6" in val:
        return {"source": "R5"}
    return {"source": val}
