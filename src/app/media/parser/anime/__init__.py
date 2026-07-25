"""
动漫标题解析 — 主入口
将 MetaAnime 类拆分为纯函数模块
"""

import re

import anitopy  # type: ignore

from app.domain.mediatypes import MediaType
from app.media.models import MediaInfo
from app.media.parser._customization import CustomizationMatcher
from app.media.parser.anime.name_parser import clean_name, extract_name, parse_name, recover_cn_name
from app.media.parser.anime.prepare import extract_japanese_title, prepare_title
from app.media.parser.anime.resource_parser import (
    parse_customization,
    parse_encode,
    parse_resource_pix,
    parse_team,
)
from app.media.parser.anime.season_episode_parser import (
    parse_episode,
    parse_season,
    parse_type,
    parse_year,
)
from app.media.parser.naming_patterns import apply_hit_to_info, get_naming_patterns
from app.utils import ExceptionUtils, StringUtils


def parse_anime_title(
    title,
    subtitle=None,
    fileflag=False,
    customization_matcher: CustomizationMatcher | None = None,
) -> MediaInfo:
    """解析动漫文件名，返回 MediaInfo"""
    info = MediaInfo()
    if not title:
        return info
    info.org_string = title
    info.subtitle = subtitle
    info.fileflag = fileflag
    try:
        original_title = title
        # 命名模式库优先：命中即获得权威名称，跳过脆弱的启发式抽取
        pattern_hit = get_naming_patterns().apply(original_title)
        title = re.sub(r"(\d+\.\d+)\s+", r"\1", title)
        anitopy_info_origin = anitopy.parse(title)
        title = prepare_title(title)
        anitopy_info = anitopy.parse(title)
        if anitopy_info:
            if pattern_hit and (pattern_hit.get("cn_name") or pattern_hit.get("en_name")):
                info.cn_name = pattern_hit.get("cn_name")
                info.en_name = pattern_hit.get("en_name")
            else:
                name = extract_name(info, anitopy_info, title)
                parse_name(info, name)
                recover_cn_name(
                    info,
                    anitopy_info_origin.get("anime_title") if anitopy_info_origin else None,
                    anitopy_info.get("release_group"),
                )
            clean_name(info)
            if not info.en_name:
                raw_title = anitopy_info.get("anime_title")
                if raw_title and not StringUtils.is_chinese(str(raw_title)):
                    info.en_name = str(raw_title)
            parse_year(info, anitopy_info)
            parse_season(info, anitopy_info)
            parse_episode(info, anitopy_info)
            if pattern_hit:
                apply_hit_to_info(info, pattern_hit)
            parse_type(info, anitopy_info)
            parse_resource_pix(info, anitopy_info)
            parse_team(info, original_title, anitopy_info_origin)
            parse_customization(info, original_title, customization_matcher)
            parse_encode(info, anitopy_info)
            # 提取资源来源（WEB-DL / BluRay / HDTV 等）
            source_match = re.search(
                r"(WEB[\s.-]?DL|WEB[\s.-]?RIP|Blu[\s.-]?Ray|HDTV|UHDTV|HDRip|BDRip|DVDRip|HDDVD|BD[\s.-]?Rip)",
                original_title,
                re.IGNORECASE,
            )
            if source_match:
                info.resource_type = source_match.group(1).upper().replace(" ", "-").replace(".", "-")
            info.init_subtitle(info.org_string)
            if info.subtitle:
                info.init_subtitle(info.subtitle)
        if not info.type:
            info.type = MediaType.TV
        jp_title = extract_japanese_title(original_title)
        if jp_title and not info.en_name:
            info.en_name = jp_title
    except Exception as e:
        ExceptionUtils.exception_traceback(e)
    return info
