"""
动漫标题解析 — 名称解析
"""

import re

import anitopy  # type: ignore

from app.media.parser.anime.constants import _ANIME_NO_WORDS, _NAME_CLEANUP_RE, _NAME_NOSTRING_RE
from app.utils import StringUtils
from app.utils.chinese_utils import to_simplified

_CHINESE_META_CLEAN = frozenset("粤日英简繁国台港双多单语字幕音轨频内嵌封挂压效硬软中外体转载自搬运")


def extract_name(info, anitopy_info, title):
    """从 anitopy 结果中提取名称"""
    name = anitopy_info.get("anime_title")
    if name and name.find("/") != -1:
        parts = [p.strip() for p in name.split("/")]
        left = parts[0]
        right = parts[-1]
        if StringUtils.is_chinese(left) and not StringUtils.is_all_chinese(right):
            info.cn_name = left
            name = right
        elif StringUtils.is_all_chinese(right) and not StringUtils.is_chinese(left):
            # 英文/罗马字在前、中文在后（如 ANi 格式）
            info.cn_name = right
            name = left
        elif not StringUtils.is_chinese(right) or len(parts) > 1:
            name = right if not StringUtils.is_all_chinese(right) else left
    if not name or name in _ANIME_NO_WORDS or (len(name) < 5 and not StringUtils.is_chinese(name)):
        anitopy_info = anitopy.parse("[ANIME]" + title)
        if anitopy_info:
            name = anitopy_info.get("anime_title")
    if not name or name in _ANIME_NO_WORDS or (len(name) < 5 and not StringUtils.is_chinese(name)):
        name_match = re.search(r"\[(.+?)]", title)
        if name_match and name_match.group(1):
            name = name_match.group(1).strip()
    if name and not StringUtils.is_chinese(name):
        _supp_name = _supplement_bracket_content(name, anitopy_info, title)
        bracket_contents = re.findall(r"\[([^\]]+)\]", title)
        release_group = str((anitopy_info or {}).get("release_group") or "").strip()
        cn_found = None
        if not info.cn_name:
            for bc in bracket_contents:
                bc_clean = bc.strip().replace("_", " ").strip()
                # 字幕组名不能当中文名
                if release_group and bc_clean.upper() == release_group.upper():
                    continue
                if StringUtils.is_chinese(bc_clean) and len(bc_clean) >= 4:
                    if all(c in _CHINESE_META_CLEAN for c in bc_clean):
                        continue
                    cn_found = bc_clean
                    break
        name = cn_found or _supp_name
    elif name and len(name) <= 6 and StringUtils.is_chinese(name):
        supp = _supplement_bracket_content(name, anitopy_info, title)
        if supp != name:
            name = supp
        # anitopy 把区分词拆到 episode_title 时补回
        ep_title = anitopy_info.get("episode_title") if anitopy_info else None
        if ep_title and ep_title not in name:
            name = f"{name} {ep_title}"
    return name


def _supplement_bracket_content(name, anitopy_info, title):
    """回收 anitopy 未消费的方括号内容"""
    name_clean = re.sub(r"\s+", " ", name.replace("_", " ").replace(".", " ")).strip().upper()

    consumed = {name_clean}
    for key in (
        "release_group",
        "source",
        "video_resolution",
        "video_codec",
        "audio_codec",
        "audio_term",
        "video_term",
        "file_extension",
    ):
        val = anitopy_info.get(key)
        if val:
            for v in val if isinstance(val, list) else [val]:
                consumed.add(str(v).upper().replace("_", " ").replace(".", " ").strip())

    _META_TOKEN_RE = re.compile(
        r"(?i)^\d+p$|^x?\d{2,4}p?$|^h\d{3}(p\d+)?$|^aac\d*$|^flac\d*$|^ddp?\d*$|^hevc[-\d]*|^avc$|^xvid$|^divx$"
        r"|^srt\d*$|^srtx\d*$|^ass$|^subs?$|^ch[st]$|^10bit$|^web[-]?(dl|rip)$|^bd(rip)?$|^blu[-]?ray$"
        r"|^dvd(rip)?$|^remux$|^complete$|^fin$|^batch$|^v\d$|^rev\d*$|^jav$"
        r"|^x\.?\d{2,4}$|^h\.?\d{2,4}$|^h26[345]$|^aac$|^eac3$|^opus$|^dts$|^truehd$"
        r"|^hdr\d*$|^dv$|^sdr$"
        r"|^(?:baha|cr|abema|nf|hulu|dsnp|friday|linetv|catchplay|kktv|b-global)$"
        r"|^(?:mp4|mkv|avi|ts|m2ts|wmv|flv)$"
        r"|^movie([+&]?\w+)?$|^tv[+&]?\w*$|^ova([+&]?\w+)?$|^sp\w*$"
    )

    _CHINESE_META_CHARS = set("粤日英简繁国台港双多单语字幕音轨频内嵌封挂压效硬软中外体转载自搬运")

    bracket_contents = re.findall(r"\[([^\]]+)\]", title)
    remaining = []
    for bc in bracket_contents:
        bc_clean = bc.strip().replace("_", " ").strip()
        bc_upper = bc_clean.upper()
        if bc_upper == name_clean or bc_upper in consumed:
            continue
        if bool(re.match(r"^[a-fA-F0-9]{8}$", bc_clean)):
            continue
        if len(bc_clean) < 2 or "," in bc_clean:
            continue
        if _META_TOKEN_RE.match(bc_clean):
            continue
        if all(c in _CHINESE_META_CHARS for c in bc_clean):
            continue
        tokens = bc_clean.split()
        if len(tokens) >= 2 and (
            all(_META_TOKEN_RE.match(tk) for tk in tokens)
            or all(all(c in _CHINESE_META_CHARS for c in tk) for tk in tokens)
        ):
            continue
        remaining.append(bc.replace("_", " "))

    if remaining:
        return f"{name} {' '.join(remaining)}"
    return name


def recover_cn_name(info, origin_anime_title, release_group=None):
    """
    回收中文名 — prepare_title 可能丢弃斜杠前的中文段，
    从预处理前的 anitopy 结果中恢复；同时清除字幕组名的误标。
    """
    rg = (release_group or "").strip()
    if info.cn_name and (not rg or info.cn_name.strip().upper() != rg.upper()):
        return
    raw = str(origin_anime_title or "")
    if "/" not in raw:
        # 字幕组名被误当中文名时清除
        if info.cn_name and rg and info.cn_name.strip().upper() == rg.upper():
            info.cn_name = None
        return
    for part in raw.split("/"):
        part = part.strip()
        if StringUtils.is_all_chinese(part) and len(part) >= 2:
            info.cn_name = part
            return


def parse_name(info, name):
    """拆份中英文名称"""
    if not name:
        return
    lastword_type = ""
    for word in name.split():
        if not word:
            continue
        word = word.removesuffix("]")
        if word.isdigit():
            if lastword_type == "cn":
                info.cn_name = "{} {}".format(info.cn_name or "", word)
            elif lastword_type == "en":
                info.en_name = "{} {}".format(info.en_name or "", word)
        elif StringUtils.is_chinese(word):
            info.cn_name = "{} {}".format(info.cn_name or "", word)
            lastword_type = "cn"
        else:
            info.en_name = "{} {}".format(info.en_name or "", word)
            lastword_type = "en"


def clean_name(info):
    """清理并标准化名称"""
    if info.cn_name:
        _, info.cn_name, _, _, _, _ = StringUtils.get_keyword_from_string(info.cn_name)
        if info.cn_name:
            info.cn_name = re.sub(rf"{_NAME_NOSTRING_RE}", "", info.cn_name, flags=re.IGNORECASE).strip()
            info.cn_name = re.sub(_NAME_CLEANUP_RE, "", info.cn_name, flags=re.IGNORECASE).strip()
            info.cn_name = to_simplified(info.cn_name)
    if info.en_name:
        info.en_name = re.sub(rf"{_NAME_NOSTRING_RE}", "", info.en_name, flags=re.IGNORECASE).strip()
        info.en_name = re.sub(_NAME_CLEANUP_RE, "", info.en_name, flags=re.IGNORECASE).strip()
        info.en_name = info.en_name.title()
        info._name = StringUtils.str_title(info.en_name)
