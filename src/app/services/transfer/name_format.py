"""重命名格式：占位符目录、解析校验与渲染.

提供统一的字段目录（供前端构建器参考）、格式串校验与渲染，
其中渲染支持「可选片段」语法，避免空字段残留多余分隔符。

可选片段语法: ``{field:模板}`` —— 当 field 为空时整段消失，
否则把 field 的值代入 ``模板`` 内其余占位符渲染。

示例::

    "{title} ({year})/{title} - {season_episode}"
    "{en_title: {en_title} ({year})}"   # en_title 为空时整个消失
    "{season_episode: - {season_episode}}"  # 无季集时不残留 " - "
"""

from __future__ import annotations

import re

# 字段目录：key -> (中文名, 说明, 适用类型, 是否依赖 media_service)
# 适用类型: "both" | "movie" | "tv"
_FIELDS: list[tuple[str, str, str, str, bool]] = [
    ("title", "主标题", "主标题（中文优先）", "both", False),
    ("en_title", "英文标题", "英文标题，需媒体服务取 TMDB", "both", True),
    ("original_name", "原名文件", "原名（去扩展名）", "both", False),
    ("rev_name", "识别词后名", "识别词处理后的文件名", "both", False),
    ("original_title", "原始标题", "识别前的原始标题", "both", False),
    ("name", "名称", "get_name() 名称", "both", False),
    ("year", "年份", "上映/首播年份", "both", False),
    ("edition", "版本", "版本说明（含年份/分辨率等）", "both", False),
    ("videoFormat", "分辨率", "如 1080p / 2160p", "both", False),
    ("source", "片源", "如 WEB-DL / BluRay", "both", False),
    ("releaseGroup", "发布组", "发布组名", "both", False),
    ("customization", "自定义", "自定义标识", "both", False),
    ("effect", "特效", "特效说明（HDR 等）", "both", False),
    ("videoCodec", "视频编码", "如 H.264 / H.265", "both", False),
    ("audioCodec", "音频编码", "如 AAC / DTS", "both", False),
    ("tmdbid", "TMDB ID", "TMDB 编号", "both", False),
    ("imdbid", "IMDB ID", "IMDB 编号", "both", False),
    ("media_type", "媒体类型", "movie / tv / anime", "both", False),
    ("category", "分类", "分类名称", "both", False),
    ("season", "季号", "季数（电影为空）", "tv", False),
    ("episode", "集号", "集数（电影为空）", "tv", False),
    ("episode_title", "集标题", "集标题，需媒体服务取 TMDB", "tv", True),
    ("season_episode", "季集", "如 S08E07", "tv", False),
    ("part", "分集", "分集部分标识", "both", False),
]

FIELD_CATALOG = [dict(zip(("key", "label", "desc", "applies", "requires_ms"), f)) for f in _FIELDS]
NAME_FORMAT_FIELDS = frozenset(f["key"] for f in FIELD_CATALOG)

_KEY_RE = re.compile(r"\{([A-Za-z0-9_]+)")


def _find_conds(fmt: str) -> list[tuple[int, int, str, str]]:
    """扫描格式串，返回条件段 ``{key:payload}`` 列表 [(start, end, key, payload)]."""
    out: list[tuple[int, int, str, str]] = []
    i, n = 0, len(fmt)
    while i < n:
        if fmt[i] != "{":
            i += 1
            continue
        m = _KEY_RE.match(fmt, i)
        if not m:
            i += 1
            continue
        end_key = m.end()
        if end_key < n and fmt[end_key] == ":":
            # {key: ... } 条件段，用括号深度匹配闭合
            depth = 1
            k = end_key + 1
            closed = -1
            while k < n:
                if fmt[k] == "{":
                    depth += 1
                elif fmt[k] == "}":
                    depth -= 1
                    if depth == 0:
                        closed = k
                        break
                k += 1
            if closed != -1:
                out.append((i, closed + 1, m.group(1), fmt[end_key + 1 : closed]))
                i = closed + 1
                continue
            i += 1
            continue
        # 普通字段 {key}
        close = fmt.find("}", i)
        i = close + 1 if close != -1 else n
    return out


def parse_fields(fmt: str) -> list[str]:
    """提取格式串中出现过的全部字段 key（含可选片段内部）。"""
    if not fmt:
        return []
    keys: set[str] = set(_KEY_RE.findall(fmt))
    return sorted(keys)


def validate(fmt: str) -> dict:
    """校验格式串，返回 ``{ok, problems}``。"""
    problems: list[str] = []
    if fmt and fmt.count("{") != fmt.count("}"):
        problems.append("花括号未闭合")
    for start, end, key, payload in _find_conds(fmt):
        if payload.count("{") != payload.count("}"):
            problems.append(f"条件段 {{{key}:...}} 内部花括号不匹配")
    for key in parse_fields(fmt):
        if key not in NAME_FORMAT_FIELDS:
            problems.append(f"未知字段: {{{key}}}")
    return {"ok": not problems, "problems": problems}


def render(fmt: str, fmt_dict: dict) -> str:
    """渲染格式串：先处理可选片段，再替换普通字段并清理空值残留。"""
    if not fmt:
        return ""
    out = fmt
    for start, end, key, payload in sorted(_find_conds(fmt), reverse=True):
        val = fmt_dict.get(key)
        if val is None or val == "\t" or val == "":
            out = out[:start] + out[end:]
        else:
            try:
                inner = payload.format(**fmt_dict)
            except (KeyError, ValueError):
                inner = payload
            out = out[:start] + inner + out[end:]
    try:
        out = out.format(**fmt_dict)
    except (KeyError, ValueError):
        pass
    return re.sub(r"[-_\s.]*\t", "", out)


def split_format(fmt: str, media_type: str) -> dict:
    """按 ``/`` 把整条格式串拆分为路径段.

    电影: 目录/文件名；剧集: 目录/季目录/文件名。
    """
    if media_type == "movie":
        parts = fmt.rsplit("/", 1)
        return {"dir": parts[0], "file": parts[1] if len(parts) > 1 else ""}
    parts = fmt.rsplit("/", 2)
    if len(parts) >= 3:
        return {"dir": parts[0], "season": parts[1], "file": parts[2]}
    if len(parts) == 2:
        return {"dir": parts[0], "season": "", "file": parts[1]}
    return {"dir": parts[0], "season": "", "file": ""}


def _sentinel(values: dict) -> dict:
    """空值替换为 \\t 哨兵，与 get_format_dict 保持一致。"""
    out = dict(values)
    for k, v in out.items():
        if v is None or v == "":
            out[k] = "\t"
    return out


def render_path(fmt: str, media_type: str, values: dict) -> dict:
    """渲染完整路径，返回 ``{dir, season, file}``。"""
    segments = split_format(fmt, media_type)
    fmt_dict = _sentinel(values)
    return {key: render(seg, fmt_dict) for key, seg in segments.items()}


def field_groups() -> list[dict]:
    """按用途分组返回字段目录，供前端构建器渲染按钮。"""
    groups = [
        ("标题", ["title", "en_title", "original_title", "original_name", "rev_name", "name"]),
        ("季集", ["season", "episode", "season_episode", "episode_title", "part"]),
        ("年份媒体信息", ["year", "edition", "videoFormat", "source", "videoCodec", "audioCodec", "releaseGroup"]),
        ("标识", ["tmdbid", "imdbid", "media_type", "category", "customization", "effect"]),
    ]
    by_key = {f["key"]: f for f in FIELD_CATALOG}
    return [{"group": gname, "fields": [by_key[k] for k in keys if k in by_key]} for gname, keys in groups]
