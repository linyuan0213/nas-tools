import os

import regex as re

import log
from app.domain.mediatypes import MediaType
from app.domain.word_processor import get_words_info, process_title
from app.media.models import MediaInfo
from app.media.parser.unified import UnifiedParser


def meta_info(title: str, subtitle: str | None = None, mtype: MediaType | None = None) -> MediaInfo:
    org_title = title
    if title:
        # 路径 → 取文件名；裸数字文件名(1.mp4) → 父目录作标题
        # 区分真路径（含目录层级）和标题中的 " / " 分隔符
        is_path = ("/" in title or "\\" in title) and bool(
            re.search(r"[/\\](?:[^/\\]+[/\\])", title) or title.startswith("/")
        )
        if is_path:
            parent = os.path.basename(os.path.dirname(title)).strip()
            title = os.path.basename(title)
            if parent and re.fullmatch(r"\d+\.\w+", title, re.IGNORECASE):
                subtitle = title
                title = parent
            elif parent and parent not in (".", "/", ""):
                subtitle = subtitle or parent
        title = re.sub(r"\|\d+(\|\d+)?$", "", title)
        cleaned = re.sub(
            r"(?i)\b(?:www\s+\w+|\w+\.(?:com|net|org|tv|cc|me|io)\b|pthdtv|qqhdtv|剧集网发布)\b",
            "",
            title,
        )
        cleaned = re.sub(r"\s+", " ", cleaned).strip()
        if cleaned != title:
            title = cleaned

    words = get_words_info()
    rev_title, msg, used_info = process_title(words, title)
    if subtitle:
        subtitle, _, _ = process_title(words, subtitle)

    if msg:
        for msg_item in msg:
            log.warn(f"[Meta]{msg_item}")

    parser = UnifiedParser()
    parsed = parser.parse(rev_title, subtitle or "")
    if parsed:
        if mtype == MediaType.ANIME:
            parsed.type = MediaType.ANIME
        media_info = MediaInfo.from_parser(parsed)
    else:
        media_info = MediaInfo()

    if subtitle:
        media_info.init_subtitle(subtitle)
        media_info.subtitle = subtitle

    media_info.org_string = org_title
    media_info.rev_string = rev_title
    media_info.ignored_words = used_info.get("ignored")
    media_info.replaced_words = used_info.get("replaced")
    media_info.offset_words = used_info.get("offset")

    if media_info.begin_episode and org_title:
        if re.search(rf"{media_info.begin_episode}\s*(FPS|HZ)", org_title, re.IGNORECASE):
            media_info.begin_episode = None
            media_info.end_episode = None
            media_info.total_episodes = 0

    if not media_info.year:
        for source in (subtitle, org_title):
            if source:
                year_match = re.search(r"(?<![_\d])(19\d{2}|20[0-4]\d)(?!\d)", str(source))
                if year_match:
                    media_info.year = year_match.group(1)
                    break

    # 音频文件识别：无季集 + 标题含音频特征 → 非影视内容，不参与匹配
    if (
        not media_info.begin_episode
        and not media_info.begin_season
        and re.search(
            r"(?i)\b(?:flac|wav|mp3|aac|ape|dsd|dts|alac|ogg|wma|opus)\b"
            r"|(?:Hi[-\s]?Res|24\s*bit|96\s*kHz|192\s*kHz|lossless|无损|音频|音乐专辑)"
            r"|USB.*(?:FLAC|WAV|変換|convert)",
            org_title,
        )
    ):
        media_info.cn_name = None
        media_info.en_name = None
        media_info.type = MediaType.UNKNOWN

    return media_info
