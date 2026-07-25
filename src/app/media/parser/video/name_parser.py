"""
影视标题解析 — 名称与季集相关解析
"""

import re

from app.media.parser.video.constants import (
    _episode_re,
    _name_no_chinese_re,
    _name_nostring_re,
    _name_se_words,
    _resources_pix_re,
    _resources_type_re,
    _roman_numerals,
    _season_re,
)
from app.utils import StringUtils


def init_name(info, token):
    """解析名称 token"""
    if not token:
        return
    if info._unknown_name_str:
        if not info.cn_name:
            if not info.en_name:
                info.en_name = info._unknown_name_str
            elif info._unknown_name_str != info.year:
                info.en_name = f"{info.en_name} {info._unknown_name_str}"
            info._last_token_type = "enname"
        info._unknown_name_str = ""
    if info._stop_name_flag:
        return
    if token.upper() == "AKA":
        # 跳过 AKA 本身但继续解析 —— 后续 token 可能含区分信息（如 Stand Alone Complex）
        # 或其他语言别名；直接停止会把它们连同名称一起丢弃
        return
    if token in _name_se_words:
        info._last_token_type = "name_se_words"
        return
    if StringUtils.is_chinese(token):
        info._last_token_type = "cnname"
        if not info.cn_name:
            info.cn_name = token
        elif not info._stop_cnname_flag:
            # 已有名称较长时不再追加，避免把外传名+主系列名拼接
            if len(info.cn_name) >= 15:
                info._stop_cnname_flag = True
                return
            if not re.search(f"{_name_no_chinese_re}", token, flags=re.IGNORECASE) and not re.search(
                f"{_name_se_words}", token, flags=re.IGNORECASE
            ):
                info.cn_name = f"{info.cn_name} {token}"
    else:
        is_roman_digit = re.search(_roman_numerals, token)
        if token.isdigit() or is_roman_digit:
            # 跳过预提取的 episode 数字（如 "Title - 72 [tags]" 中的 72）
            if info.begin_episode and token.isdigit() and int(token) == info.begin_episode:
                info._continue_flag = False
                return
            if info._last_token_type == "name_se_words":
                return
            if info.get_name():
                if token.startswith("0"):
                    return
                if token.isdigit():
                    try:
                        int(token)
                    except ValueError:
                        return
                if not is_roman_digit and info._last_token_type == "cnname" and int(token) < 1900:
                    return
                if (token.isdigit() and len(token) < 4) or is_roman_digit:
                    if info._last_token_type == "cnname":
                        info.cn_name = f"{info.cn_name} {token}"
                    elif info._last_token_type == "enname":
                        info.en_name = f"{info.en_name} {token}"
                    info._continue_flag = False
                elif token.isdigit() and len(token) == 4:
                    if not info._unknown_name_str:
                        info._unknown_name_str = token
            else:
                if not info._unknown_name_str:
                    info._unknown_name_str = token
        elif re.search(rf"{_season_re}", token, re.IGNORECASE):
            if info.en_name and re.search(r"SEASON$", info.en_name, re.IGNORECASE):
                info.en_name += " "
            info._stop_name_flag = True
            return
        elif (
            re.search(rf"{_episode_re}", token, re.IGNORECASE)
            or re.search(rf"({_resources_type_re})", token, re.IGNORECASE)
            or re.search(rf"{_resources_pix_re}", token, re.IGNORECASE)
        ):
            info._stop_name_flag = True
            return
        else:
            from app.core.constants import RMT_MEDIAEXT

            if ".%s".lower() % token in RMT_MEDIAEXT:
                return
            if info.en_name:
                info.en_name = f"{info.en_name} {token}"
            else:
                info.en_name = token
            info._last_token_type = "enname"


def fix_name(info, name):
    """清理名称中的干扰字符"""
    if not name:
        return name
    name = re.sub(rf"{_name_nostring_re}", "", name, flags=re.IGNORECASE).strip()
    name = re.sub(r"\s+", " ", name)
    if (
        name.isdigit()
        and int(name) < 1800
        and not info.year
        and not info.begin_season
        and not info.resource_pix
        and not info.resource_type
        and not info.audio_encode
        and not info.video_encode
    ):
        if info.begin_episode is None:
            info.begin_episode = int(name)
            name = None
        elif info.is_in_episode(int(name)) and not info.begin_season:
            name = None
    return name
