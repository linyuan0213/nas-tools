"""媒体类型推断器"""

from __future__ import annotations

from app.domain.mediatypes import MediaType

from .types import ParseContext


def infer_type(ctx: ParseContext) -> MediaType:
    """基于解析结果推断媒体类型"""
    # 命名模式库命中时直接返回
    if ctx.has("media_type"):
        for elem in ctx.get_elements("media_type"):
            if isinstance(elem.value, MediaType):
                return elem.value

    # SxxExx 格式 → TV
    if ctx.season and ctx.episode:
        return MediaType.TV

    # 有季数但无集数 → TV（如 S04 季度包）
    if ctx.season and not ctx.episode:
        return MediaType.TV

    # 有集数但无季数
    if ctx.episode and not ctx.season:
        if _is_anime_pattern(ctx):
            return MediaType.ANIME
        return MediaType.TV

    # 无集数 + 有年份 → MOVIE（无论是否有分辨率）
    if ctx.year and not ctx.episode and not ctx.season:
        return MediaType.MOVIE

    # 无集数 + 有来源 (BluRay/WEB-DL 等) → MOVIE
    if ctx.source and not ctx.episode and not ctx.season:
        return MediaType.MOVIE

    # 默认 TV
    return MediaType.TV


def _is_anime_pattern(ctx: ParseContext) -> bool:
    """判断是否为动漫命名模式"""
    # 中文名称 + 无 SxxExx 格式 → 动漫
    if ctx.cn_name and not _has_sxxexx_pattern(ctx):
        return True
    # 有制作组标记 + 有集数 → 动漫
    if ctx.release_group and ctx.episode:
        return True
    # 日文假名标题存在 → 动漫
    if ctx.jp_title:
        return True
    return False


def _has_sxxexx_pattern(ctx: ParseContext) -> bool:
    """检查是否有 SxxExx 格式标记"""
    for elem in ctx.elements:
        if elem.rule_name in ("sxxexx", "season_ep_keyword"):
            return True
    return False
