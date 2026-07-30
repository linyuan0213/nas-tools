"""分辨率提取规则"""

from __future__ import annotations

import re

from .base import ExtractionRule

RULES: list[ExtractionRule] = [
    ExtractionRule(
        name="4k_uhd",
        pattern=re.compile(r"\b(2160[pP]|4[Kk]|UHD|Ultra\s?HD)\b", re.IGNORECASE),
        category="resolution",
        priority=90,
        confidence=0.95,
        _extract_fn=lambda m, _: {"resolution": "2160p"},
    ),
    ExtractionRule(
        name="1080p",
        pattern=re.compile(r"\b(1080[pP]|FHD|Full\s?HD|1080[iI])\b", re.IGNORECASE),
        category="resolution",
        priority=85,
        confidence=0.95,
        _extract_fn=lambda m, _: {"resolution": "1080p"},
    ),
    ExtractionRule(
        name="720p",
        pattern=re.compile(r"\b720[pP]\b|\b(?<![-])HD\b", re.IGNORECASE),
        category="resolution",
        priority=80,
        confidence=0.95,
        _extract_fn=lambda m, _: {"resolution": "720p"},
    ),
    ExtractionRule(
        name="480p",
        pattern=re.compile(r"\b(480[pP]|SD)\b", re.IGNORECASE),
        category="resolution",
        priority=75,
        confidence=0.9,
        _extract_fn=lambda m, _: {"resolution": "480p"},
    ),
    ExtractionRule(
        name="pixel_format",
        pattern=re.compile(r"\b(\d{3,4})[xX](\d{3,4})\b"),
        category="resolution",
        priority=70,
        confidence=0.9,
        _extract_fn=lambda m, _: {"resolution": f"{m.group(2)}p"},
    ),
]
