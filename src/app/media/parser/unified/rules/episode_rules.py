"""集数提取规则"""

from __future__ import annotations

import re

import cn2an

from .base import ExtractionRule

RULES: list[ExtractionRule] = [
    ExtractionRule(
        name="sxxexx_resolution_tight",
        # 集号与分辨率粘连（S01E071080p = S01E07 + 1080p）：非贪婪集号 + 前瞻分辨率截断，
        # 避免 \d+ 贪婪把 07+1080 全当集号
        pattern=re.compile(r"[Ss](\d+)[Ee](\d+?)(?=(?:2160|1080|720|480|576)[pPiI]\b)", re.IGNORECASE),
        category="episode",
        priority=101,
        confidence=0.95,
        stop=True,
        _extract_fn=lambda m, _: {
            "season": int(m.group(1)),
            "episode": int(m.group(2)),
        },
    ),
    ExtractionRule(
        name="sxxexx_range",
        pattern=re.compile(r"[Ss](\d+)[Ee](\d+)[-~][Ee](\d+)", re.IGNORECASE),
        category="episode",
        priority=102,
        confidence=0.95,
        stop=True,
        _extract_fn=lambda m, _: {
            "season": int(m.group(1)),
            "episode": [int(m.group(2)), int(m.group(3))],
        },
    ),
    ExtractionRule(
        name="sxxexx",
        pattern=re.compile(r"[Ss](\d+)[Ee](\d+)", re.IGNORECASE),
        category="episode",
        priority=100,
        confidence=0.95,
        stop=True,
        _extract_fn=lambda m, _: {
            "season": int(m.group(1)),
            "episode": int(m.group(2)),
        },
    ),
    ExtractionRule(
        name="season_ep_keyword",
        pattern=re.compile(r"Season\s*(\d+)\s*Episode\s*(\d+)", re.IGNORECASE),
        category="episode",
        priority=95,
        confidence=0.95,
        stop=True,
        _extract_fn=lambda m, _: {
            "season": int(m.group(1)),
            "episode": int(m.group(2)),
        },
    ),
    ExtractionRule(
        name="bracket_range",
        pattern=re.compile(r"\[(\d{1,4})[-~](\d{1,4})\]"),
        category="episode",
        priority=90,
        confidence=0.9,
        stop=True,
        _extract_fn=lambda m, _: {"episode": [int(m.group(1)), int(m.group(2))]},
    ),
    ExtractionRule(
        name="e_dash_e_range",
        pattern=re.compile(r"\b[Ee](\d{1,4})[-~][Ee](\d{1,4})\b"),
        category="episode",
        priority=88,
        confidence=0.85,
        stop=True,
        _extract_fn=lambda m, _: {"episode": [int(m.group(1)), int(m.group(2))]},
    ),
    ExtractionRule(
        name="ep_dash_num_range",
        pattern=re.compile(r"\bEP?(\d{1,4})[-~](\d{1,4})\b", re.IGNORECASE),
        category="episode",
        priority=87,
        confidence=0.85,
        stop=True,
        _extract_fn=lambda m, _: {"episode": [int(m.group(1)), int(m.group(2))]},
    ),
    ExtractionRule(
        name="dash_ep_range",
        pattern=re.compile(r"\b(\d{1,4})[-~](\d{1,4})\b(?![pP])"),
        category="episode",
        priority=85,
        confidence=0.85,
        stop=True,
        _extract_fn=lambda m, _: {"episode": [int(m.group(1)), int(m.group(2))]},
    ),
    ExtractionRule(
        name="bracket_ep",
        pattern=re.compile(r"\[(\d{1,4})(?:[vV]\d+)?\]"),
        category="episode",
        priority=80,
        confidence=0.9,
        stop=True,
    ),
    ExtractionRule(
        name="ep_prefix",
        pattern=re.compile(r"\bEP?(\d{1,4})\b", re.IGNORECASE),
        category="episode",
        priority=75,
        confidence=0.85,
        stop=True,
    ),
    ExtractionRule(
        name="chinese_ep_range",
        pattern=re.compile(r"第\s*(\d+)\s*[-~]\s*(\d+)\s*[集话話期]"),
        category="episode",
        priority=72,
        confidence=0.85,
        stop=True,
        _extract_fn=lambda m, _: {"episode": [int(m.group(1)), int(m.group(2))]},
    ),
    ExtractionRule(
        name="chinese_ep",
        pattern=re.compile(r"第\s*(\d+)\s*[集话話期]"),
        category="episode",
        priority=70,
        confidence=0.85,
        stop=True,
    ),
    ExtractionRule(
        name="chinese_number_ep",
        pattern=re.compile(r"第([一二三四五六七八九十百]+)集"),
        category="episode",
        priority=65,
        confidence=0.85,
        stop=True,
        _extract_fn=lambda m, _: _cn2an_extract(m),
    ),
    ExtractionRule(
        name="dash_ep",
        pattern=re.compile(r"\s[-~]\s*(\d{1,4})\b"),
        category="episode",
        priority=60,
        confidence=0.75,
        stop=True,
    ),
    ExtractionRule(
        name="pipe_ep",
        pattern=re.compile(r"\|(\d{1,4})\b"),
        category="episode",
        priority=58,
        confidence=0.7,
        stop=True,
    ),
    ExtractionRule(
        name="trailing_ep",
        pattern=re.compile(r"(\d{1,4})\s+[繁简]"),
        category="episode",
        priority=56,
        confidence=0.65,
        stop=True,
    ),
    ExtractionRule(
        name="hash_ep",
        pattern=re.compile(r"#(\d{1,4})\b"),
        category="episode",
        priority=55,
        confidence=0.7,
        stop=True,
    ),
    ExtractionRule(
        name="bare_episode",
        # 数字后紧跟连字符+字母（100-nin）或普通单词（The 100 Girlfriends）属于标题词，不是集号；
        # 裸集号后面应紧跟技术信息起点（括号/点/连字符/数字）或标题结尾
        pattern=re.compile(
            r"(?<![.\d\-×xX/])\b(0?[1-9]\d{0,2})\b(?!\s*[pP]\b)(?!\.\d)(?![-~][a-zA-Z])(?=\s*(?:[\[\]()._\-]|\d|$))"
        ),
        category="episode",
        priority=50,
        confidence=0.5,
        stop=True,
    ),
]


def _cn2an_extract(match: re.Match[str]) -> dict[str, int] | None:

    try:
        val = int(cn2an.cn2an(match.group(1), mode="smart"))
        return {"episode": val}
    except Exception:
        return None
