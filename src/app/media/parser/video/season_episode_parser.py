"""
影视标题解析 — 年份、季、集解析
"""

import re

from app.domain.mediatypes import MediaType
from app.media.parser.video.constants import _episode_re, _season_re


def init_year(info, token):
    """解析年份 token"""
    if not info.get_name():
        return
    if not token.isdigit() or len(token) != 4:
        return
    if not 1900 < int(token) < 2050:
        return
    if info.year:
        if info.en_name:
            info.en_name = f"{info.en_name.strip()} {info.year}"
        elif info.cn_name:
            info.cn_name = f"{info.cn_name} {info.year}"
    elif info.en_name and re.search(r"SEASON$", info.en_name, re.IGNORECASE):
        info.en_name += " "
    info.year = token
    info._last_token_type = "year"
    info._continue_flag = False
    info._stop_name_flag = True


def init_season(info, token):
    """解析季号 token"""
    re_res = re.findall(rf"{_season_re}", token, re.IGNORECASE)
    if re_res:
        info._last_token_type = "season"
        info.type = MediaType.TV
        info._stop_name_flag = True
        info._continue_flag = True
        for se in re_res:
            if isinstance(se, tuple):
                se_t = None
                for se_i in se:
                    if se_i and str(se_i).isdigit():
                        se_t = se_i
                        break
                if se_t:
                    se = int(se_t)
                else:
                    break
            else:
                se = int(se)
            if info.begin_season is None:
                info.begin_season = se
                info.total_seasons = 1
            else:
                if se > info.begin_season:
                    info.end_season = se
                    info.total_seasons = (info.end_season - info.begin_season) + 1
                    if info.fileflag and info.total_seasons > 1:
                        info.end_season = None
                        info.total_seasons = 1
    elif token.isdigit():
        try:
            int(token)
        except ValueError:
            return
        if info._last_token_type == "SEASON" and info.begin_season is None and len(token) < 3:
            info.begin_season = int(token)
            info.total_seasons = 1
            info._last_token_type = "season"
            info._stop_name_flag = True
            info._continue_flag = False
            info.type = MediaType.TV
    elif token.upper() == "SEASON" and info.begin_season is None:
        info._last_token_type = "SEASON"


def init_episode(info, token):
    """解析集号 token"""
    if re.search(r"^\d+bit$", token, re.IGNORECASE):
        return
    re_res = re.findall(rf"{_episode_re}", token, re.IGNORECASE)
    if re_res:
        info._last_token_type = "episode"
        info._continue_flag = False
        info._stop_name_flag = True
        info.type = MediaType.TV
        for se in re_res:
            if isinstance(se, tuple):
                se_t = None
                for se_i in se:
                    if se_i and str(se_i).isdigit():
                        se_t = se_i
                        break
                if se_t:
                    se = int(se_t)
                else:
                    break
            else:
                se = int(se)
            if info.begin_episode is None:
                info.begin_episode = se
                info.total_episodes = 1
            else:
                if se > info.begin_episode:
                    info.end_episode = se
                    info.total_episodes = (info.end_episode - info.begin_episode) + 1
                    if info.fileflag and info.total_episodes > 2:
                        info.end_episode = None
                        info.total_episodes = 1
    elif token.isdigit():
        try:
            int(token)
        except ValueError:
            return
        if (
            info.begin_episode is not None
            and info.end_episode is None
            and len(token) < 5
            and int(token) > info.begin_episode
            and info._last_token_type == "episode"
        ):
            info.end_episode = int(token)
            info.total_episodes = (info.end_episode - info.begin_episode) + 1
            if info.fileflag and info.total_episodes > 2:
                info.end_episode = None
                info.total_episodes = 1
            info._continue_flag = False
            info.type = MediaType.TV
        elif (
            info.begin_episode is None
            and 1 < len(token) < 4
            and info._last_token_type != "year"
            and info._last_token_type != "videoencode"
            and info._last_token_type != "audioencode"
            and token != info._unknown_name_str
            or info._last_token_type == "EPISODE"
            and info.begin_episode is None
            and len(token) < 5
        ):
            info.begin_episode = int(token)
            info.total_episodes = 1
            info._last_token_type = "episode"
            info._continue_flag = False
            info._stop_name_flag = True
            info.type = MediaType.TV
    elif re.match(r"^(\d{1,3})(\(|（|[a-zA-Z\u4e00-\u9fff])", token):
        if re.search(r"季|字幕", token) or re.match(r"\d+(?:st|nd|rd|th)\b", token, re.IGNORECASE):
            return
        # token 以数字开头后跟字母或中文（如 24TV全集, 05v2）
        m = re.match(r"^(\d{1,3})", token)
        if m:
            num_str = m.group(1)
            num = int(num_str)
            # 作为 end_episode（如果 begin_episode 已存在且数字更大）
            if (
                info.begin_episode is not None
                and info.end_episode is None
                and len(num_str) < 5
                and num > info.begin_episode
                and info._last_token_type == "episode"
            ):
                info.end_episode = num
                info.total_episodes = (info.end_episode - info.begin_episode) + 1
                if info.fileflag and info.total_episodes > 2:
                    info.end_episode = None
                    info.total_episodes = 1
                info._continue_flag = False
                info.type = MediaType.TV
            # 作为 begin_episode（如果尚未设置且数字长度合适）
            elif (
                info.begin_episode is None
                and 0 < len(num_str) < 4
                and info._last_token_type != "year"
                and info._last_token_type != "videoencode"
                and info._last_token_type != "audioencode"
            ):
                info.begin_episode = num
                info.total_episodes = 1
                info._last_token_type = "episode"
                info._continue_flag = False
                info._stop_name_flag = True
                info.type = MediaType.TV
    elif token.upper() == "EPISODE":
        info._last_token_type = "EPISODE"
