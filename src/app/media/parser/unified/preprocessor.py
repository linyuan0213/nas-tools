"""统一预处理 — 合并 anime/prepare.py 与 video/ 预处理逻辑"""

from __future__ import annotations

import re

from app.utils import StringUtils

_META_CHARS = set("粤日英简繁国台港双多单语字幕音轨频内嵌封挂压效硬软中外体转载自搬运")

_RE_SITE_TAG = re.compile(
    r"^[【\[]?(?:[动漫画纪录片电影视连续剧集日美韩中港台海外华语综艺原盘高清]{2,}|TV|Animation|Movie|Documentar|Anime|完结][】\]]?|★\d+月新番★)",
    re.IGNORECASE,
)
_RE_FILESIZE = re.compile(r"[0-9.]+\s*[MGT]i?B(?![A-Z]+)", re.IGNORECASE)
_RE_TV_NUMBER = re.compile(r"\[TV\s+(\d{1,4})", re.IGNORECASE)
_RE_4K = re.compile(r"\[4[Kk]]", re.IGNORECASE)
_RE_KANA_TITLE = re.compile(r"[぀-ヿ]+")
# 常见站点/发布站顶级域（用于识别裸域名水印，避开 mkv/mp4 等容器与 web.dl 等元数据）
_SITE_TLDS = (
    r"com|net|org|tv|cc|me|io|to|st|sx|la|ws|xyz|top|club|info|pw"
    r"|co|in|biz|su|ru|eu|se|de|fr|it|pl|es|nl|be|at|ch|pt|cz|ua|ro"
)
# 站点/发布站标记：方括号域名、www 前缀、空白分隔的裸域名
_RE_SITE_MARKER = re.compile(
    rf"\[[\w.-]+\.(?:{_SITE_TLDS})\]"                      # [EZTVx.to] / [rarbg.to]
    rf"|\bwww\.[\w-]+(?:\.[A-Za-z]{{2,6}})?"                # www.UIndex.org
    rf"|(?:^|\s)[\w-]+\.(?:{_SITE_TLDS})(?=\s|$)",          # 裸站点域名（空白分隔）
    re.IGNORECASE,
)
_RE_BRACKET_GROUP = re.compile(r"^\[[^\]]+]$")
_RE_AUDIO_BITRATE = re.compile(r"\b\d{2,4}(\.\d+)?\s*(kHz|kbps|bit|bits)\b", re.IGNORECASE)
_RE_AUDIO_FORMAT = re.compile(r"\b(FLAC|ALAC|APE|WAV|AIFF|DSD|DTS|MP3|AAC|OGG|WMA|M4A|Opus)\b", re.IGNORECASE)
_RE_FPS_HZ = re.compile(r"\d+\s*(FPS|HZ)\b", re.IGNORECASE)
_RE_DATE = re.compile(r"\d{4}[\s._-]\d{1,2}[\s._-]\d{1,2}")
_RE_YEAR_RANGE = re.compile(r"([\s.]+)(\d{4})-(\d{4})")
_RE_LEADING_BRACKET = re.compile(r"^[\[【](.+?)[\]】]")
# 语言/字幕/制作/类别标记 — 出现在方括号中时应视为标签而非标题
_LANGUAGE_SUBTITLE_RE = re.compile(
    r"[粤粵][语語]|[国國][语語]|日[语語]|繁[体體]|简[体體]|外挂|内嵌|内封|多[语語]|双[语語]"
    r"|[无無]字|生肉|熟肉|中字|繁中|简[中裡]|多国|[国國]漫|日漫|美漫|[动動]漫|[动動]画"
    r"|合成|[压壓]制|配音|二次|字幕|搬[运運]|转载|整理|补档|重发|新番|完结|连载"
    r"|Hi[- ]?Res|USB|From|Share&PD|无损",
    re.IGNORECASE,
)


def prepare_title(title: str) -> str:
    """统一标题预处理"""
    if not title:
        return title
    title = title.replace("[", "[").replace("]", "]").strip()
    # 剥离站点/发布站标记（[EZTVx.to]、www.UIndex.org、裸域名水印）
    title = _RE_SITE_MARKER.sub(" ", title)
    title = re.sub(r"\s+", " ", title).strip()
    # 剥掉水印后遗留的前导分隔符（如 "www.UIndex.org - FBI" → "FBI"）
    title = re.sub(r"^\s*-\s+", "", title)
    title = _RE_FPS_HZ.sub("", title)
    title = _RE_SITE_TAG.sub("", title).strip()
    title = _RE_FILESIZE.sub("", title)
    title = _RE_TV_NUMBER.sub(r"[\1", title)
    title = _RE_4K.sub("2160p", title)
    title = _RE_AUDIO_BITRATE.sub("", title)
    title = _RE_DATE.sub("", title)
    title = _RE_YEAR_RANGE.sub(r"\1\2", title)
    # 下划线转空格（保留 SAC_2045、x265_10bit 等字母数字间有意义连接，其余拆开）
    title = re.sub(r"(?<![A-Za-z])_|_(?!\d)", " ", title)

    # 移除前缀标签（搬运/合成/粤语等标记性方括号）— 循环移除连续前缀
    for _ in range(3):
        m = _RE_LEADING_BRACKET.match(title)
        if not m:
            break
        inner = m.group(1)
        # 纯数字集数标记 → 保留
        if re.fullmatch(r"\d{1,4}([vV]\d+)?", inner):
            break
        # 语言/字幕/制作标记 → 移除
        if _LANGUAGE_SUBTITLE_RE.search(inner):
            title = title[m.end() :]
            continue
        # 发布组标记 → 移除
        has_cjk = bool(re.search(r"[぀-ヿ㐀-䶿一-鿿가-힯豈-﫿]", inner))
        looks_like_group = bool(
            re.search(
                r"字幕|压制|制作组|发布组|字幕社|工作室|论坛|奶茶屋|茶屋"
                r"|字幕组|汉化|翻译|搬运|资源组|分享组"
                r"|www\.|\.(?:com|net|cc|org|tv)",
                inner,
                re.IGNORECASE,
            )
        )
        is_short_group_name = (
            not has_cjk and " " not in inner and len(inner) < 30 and re.fullmatch(r"[A-Za-z0-9\-_@.&+³]+", inner)
        )
        # 多组联合发布（A&B）或含字幕组特征词的带空格组名（如 Studio GreenTea&LoliHouse、Nekomoe kissaten）
        is_spaced_group_name = (
            not has_cjk
            and len(inner) < 40
            and re.fullmatch(r"[A-Za-z0-9\-_@.&+³ ]+", inner)
            and ("&" in inner or re.search(r"(?i)fansub|raws|kissaten", inner))
        )
        if looks_like_group or is_short_group_name or is_spaced_group_name:
            title = title[m.end() :]
            continue
        break

    # 处理方括号分隔的多段名称（dmhy/mikan格式）
    # 只有当方括号内不含斜杠时才拆分 — 避免破坏 "中文 / English" 格式
    if "/" not in title:
        names = title.split("]")
        if len(names) > 1 and title.find("- ") == -1:
            titles: list[str] = []
            for name in names:
                if not name:
                    continue
                left_char = ""
                if name.startswith("["):
                    left_char = "["
                    name = name[1:]
                if name:
                    if StringUtils.is_chinese(name) and not StringUtils.is_all_chinese(name):
                        if not re.search(r"\[\d+", name, re.IGNORECASE):
                            name = re.sub(r"(?<!\d)[|#:：\-()（）](?!\d)", "", name).strip()
                        if not name or name.strip().isdigit():
                            continue
                        if all(c in _META_CHARS for c in name):
                            continue
                    elif StringUtils.is_all_chinese(name) and all(c in _META_CHARS for c in name):
                        continue
                    if _RE_BRACKET_GROUP.match(name):
                        titles.append(name.strip())
                    else:
                        titles.append(f"{left_char}{name.strip()}")
            return "]".join(titles)
    return title


def extract_japanese_title(title: str) -> str | None:
    """从 dmhy/mikan 格式中提取日文罗马音标题"""
    if not title:
        return None
    parts = re.split(r"[/／]", title)
    for part in parts:
        part = part.strip()
        if _RE_KANA_TITLE.search(part):
            continue
        if re.search(r"[a-zA-Z]{3,}", part) and not re.search(r"[一-鿿]", part):
            return part.strip()
    return None
