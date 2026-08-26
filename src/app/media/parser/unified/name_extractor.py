"""统一名称提取器 — 五层优先级"""

from __future__ import annotations

import re

from app.media.parser.unified.constants import _ANIME_NO_WORDS, _NAME_CLEANUP_RE, _NAME_NOSTRING_RE
from app.utils import StringUtils
from app.utils.chinese_utils import to_simplified

from .types import ParseContext

_CHINESE_META_CLEAN = frozenset("粤日英简繁国台港双多单语字幕音轨频内嵌封挂压效硬软中外体转载自搬运")

# 集标题区域内的元数据词（拒绝将此类词作为集标题）
_EP_TITLE_META_RE = re.compile(
    r"(?i)\b(?:mkv|mp4|avi|ts|m2ts|1080p|2160p|720p|480p|web-?dl|webrip|bluray|bdrip|hdtv|"
    r"h\.?26[45]|x\.?26[45]|hevc|avc|av1|aac|ac3|ddp?\d*\.?\d*|dts|flac|atmos|truehd|hdr\d*|"
    r"dv|sdr|hlg|remux|repack|proper|internal|extended|uncut|theatrical|unrated|rerelease|"
    r"remastered|upscaled|ep\d*|s\d{1,2})\b"
)


def _split_episode_title(ctx: ParseContext) -> str | None:
    """季集号（SxxExx）后的内容切分为集标题，返回季集号之前的主标题剩余文本。

    例: Medalist.S02E09.It.Begins.1080p → 标题 Medalist，集标题 It Begins
    """
    sxx = next((e for e in ctx.elements if e.rule_name == "sxxexx"), None)
    if not sxx:
        return None
    bound = len(ctx.text)
    for e in ctx.elements:
        if e.span[0] >= sxx.span[1] and e.span[0] < bound:
            bound = e.span[0]
    ep_raw = ctx.text[sxx.span[1] : bound]
    ep_title = re.sub(r"\.(?:mkv|mp4|avi|ts|m2ts)$", "", ep_raw, flags=re.IGNORECASE)
    ep_title = re.sub(r"[._\-]+", " ", ep_title).strip()
    if ep_title and not _EP_TITLE_META_RE.search(ep_title):
        ctx.episode_title = ep_title
    return ctx.remaining_text_until(sxx.span[0])


# ---- PT/BT 站点常见元数据 token ----
# 这些 token 出现在英文标题的单词位置时不应被视为片名的一部分
# 格式: 全部小写，使用 (?i) 模式匹配，^...$ 全词匹配
_META_TOKEN_RE = re.compile(
    r"(?i)^("
    # --- 分辨率 ---
    r"\d+p|\d{3,4}x\d{3,4}|[uU]?[hH][dD]|[fF][hH][dD]|[qQ][hH][dD]|[sS][dD]"
    r"|4[Kk]|8[Kk]|uhd|muhd|2160p|1440p|1080[ipIP]|720p|480p|360p"
    # --- 视频编码 ---
    r"|hevc[-\d]*|[hH]\.?265|x\.?265|h265|x265"
    r"|avc|[hH]\.?264|x\.?264|h264|x264"
    r"|(?:hevc|avc|h\.?26[45]|x\.?26[45])[-\d]*bit?"
    r"|av1|vp[89]|mpeg[-]?2|vc[-]?1|wmv[hd]?|xvid|divx|realvideo"
    # --- 音频编码 ---
    r"|aac\d*|ac[-]?3|e[-]?ac[-]?3|ddp?\d*(\.\d+)?|dd\+"
    r"|flac|alac|ape|wav|wavpack|dsd"
    r"|dts[-]?(hd[-]?ma|hd|x)?|truehd|atmos"
    r"|mp3|mp2|opus|ogg|vorbis|wma"
    r"|lpcm|pcm|dolby[-\s]?digital"
    # --- HDR/色彩 ---
    r"|hdr\d*|hdr10\+?|dv|sdr|10[-]?bit|8[-]?bit|hi10p"
    # --- 来源/平台 ---
    r"|web[-]?(dl|rip|dlr|dlmux|dlrip)?|webcast|webtv"
    r"|blu[-]?ray|bluray|bd(rip|mv|remux|iso|25|50|66|100)?|bd[-]?rip|bdmv"
    r"|uhd[-]?bluray|4k[-]?uhd"
    r"|remux|bdremux|hddvd|hd[-]?dvd"
    r"|dvd(rip|r|screener|scr|5|9)?|dvd[-]?rip|dvd[-]?r|dvdscr"
    r"|hdtv|uhdtv|pdtv|dsr|dsrip|tvrip|stv"
    r"|hd[-]?tc|tc|telesync|telecine|cam|camera|r5|r6|screener|scr"
    r"|amzn|amazon|nf|netflix|hulu|dsnp|disney|atvp|apple|hmax|hbomax|max"
    r"|pcok|peacock|pmtp|paramount|shdr|showtime|appletv|vudu|fandango"
    r"|mubi|criterion|shoutfactory|arrow|radiance|capelight|kino|cocp|eureka|bfi"
    r"|baha|cr|crunchyroll|abema|ani-one|ani|b-global|bilibili|viutv|myvideo"
    r"|friday|kktv|linetv|catchplay|iqiyi|youku|tencent|mgtv|wetv|galaxy|gimy"
    # --- 地区代码 ---
    r"|eur|gbr|ger|kor|jpn|usa|fra|ita|esp|deu|aus|can|chn|hkg|twn|sgp|ind|tha|nld|bel|dnk|swe|nor|fin|prt|bra|mex|arg"
    # --- 发布组 ---
    r"|rarbg|yts|yify|eztv|ettv|etrg|gtm|fgt|cmrg|evo|ntg|pse|tgx|galaxyrg|hive|ctrlhd"
    r"|audies|adweb|nest|runrun|dramas|fhdx|xpost|tigole|joybell|utr|qman|psa|rmteam"
    r"|mteam|beitai|ourbits|hdsky|hdc|chd|ttg|pter|keepfrds|frds|hds|hdfans"
    # --- 版本/内容标签 ---
    r"|diy|repack|proper|rerip|internal|int"
    r"|limited|extended|uncut|unrated|directors?[-]?cut|dc"
    r"|theatrical|remastered|anniversary|special[-]?edition"
    r"|imax|open[-]?matte|widescreen|letterbox"
    r"|uncensored|censored|decensored"
    # --- 音轨/字幕 ---
    r"|dual[-]?audio|multi[-]?audio|multi[-]?subs?|2[-]?audio|3[-]?audio|dual|multi"
    r"|dub(bed)?|sub(bed)?|hard[-]?sub|soft[-]?sub|eng[-]?sub"
    r"|ch[st]|chs|cht|jpsc|jptc|jps|jpt|srt|srtx?\d*|assx?\d*|ssax?\d*|idx|sup|pgs"
    r"|gb|big5"
    # --- 剧集标记 ---
    r"|complete|season|batch|collection|pack|trilogy|quadrilogy"
    r"|mini[-]?series|mini|ova\d*|special|ova|ond[ae]s?|sp\d*"
    r"|ep(isode)?\d*|part\d*|chapter\d*|vol(ume)?\d*"
    r"|final|end|fin|the[-]?end"
    # --- 频道 ---
    r"|bbc|itv|channel\s*[45]|cnn|fox|abc|nbc|cbs|hbo|starz|showtime|amc|tnt|tbs|fx|syfy"
    # --- 附加片段 ---
    r"|plus|extra|bonus|deleted|featurette|behind[-]?the[-]?scenes|making[-]?of|gag[-]?reel|trailer|teaser"
    r"|shot|game|interview|preview|sneak[-]?peek|recap|highlights"
    # --- 容器 ---
    r"|mp4|mkv|avi|ts|m2ts|mov|wmv|flv|rmvb|iso|img"
    # --- 其他 ---
    r"|x\.?\d{2,4}|h\.?\d{2,4}|h26[345]|rev\d*|v\d"
    r"|jav|fhd|hq|fixed|nuked|proper"
    r"|nvenc|qsv|amf|vce|x26[45]"
    r"|s\d{2,4}"
    # --- 类型/杂项标签 ---
    r"|from|share|pd|disc|hi[-]?res|usb"
    r"|se\d{1,2}"
    r"|@\w+"
    r"|[0-9a-fA-F]{8}"
    r"|\d+[-]?bit"
    r"|movie([+&]?\w+)?|tv[+&]?\w*"
    r")$"
)

_GROUP_KEYWORDS_RE = re.compile(
    r"字幕|压制|制作组|发布组|字幕社|工作室|论坛|奶茶屋|茶屋|字幕组|汉化|翻译|搬运|资源组|分享组",
    re.IGNORECASE,
)
_RE_KANA_TITLE = re.compile(r"[぀-ヿ]+")


def extract_name(ctx: ParseContext, original_text: str) -> None:
    """从剩余文本中提取名称，填充 ctx 的 cn_name / en_name / jp_title"""
    remaining = ctx.remaining_text()
    if not remaining.strip():
        return

    # 清理剩余文本中的元数据方括号
    remaining = _clean_metadata_brackets(remaining)
    if not remaining.strip():
        return

    # 切分季集号后的集标题（Medalist.S02E09.It.Begins → 标题 Medalist + 集标题 It Begins）
    if not ctx.episode_title:
        _title_remaining = _split_episode_title(ctx)
        if _title_remaining:
            remaining = _title_remaining

    # 剩余文本中的点号为文件名分隔符 → 转空格以便名称提取
    remaining = remaining.replace(".", " ")

    # 从原始标题中提取被预处理移除的发布组（在所有 name layer 前执行）
    _extract_group_from_original(ctx, ctx.text, original_text)

    # Layer 2: 斜杠分隔格式
    if "/" in remaining:
        _extract_slash_name(ctx, remaining)
        if ctx.cn_name or ctx.en_name:
            return

    # Layer 3: 方括号内容分析（使用预处理后的文本，避免重复识别已移除的发布组）
    _extract_bracket_name(ctx, ctx.text, original_text)
    if ctx.cn_name and ctx.en_name:
        return

    # Layer 4: 自由文本分析
    _extract_free_text(ctx, remaining)
    if ctx.cn_name or ctx.en_name:
        return

    # Layer 5: 降级恢复 — 从原始标题恢复
    _recover_from_original(ctx, original_text)


def _clean_metadata_brackets(text: str) -> str:
    """移除方括号中的元数据内容（保留非元数据内容）"""

    def replace_bracket(m: re.Match[str]) -> str:
        inner = m.group(1).strip()
        if not inner:
            return ""
        if _is_metadata(inner) or _GROUP_KEYWORDS_RE.search(inner):
            return ""
        if re.fullmatch(r"[\s\-_\.]*", inner):
            return ""
        return m.group(0)

    return re.sub(r"\[([^\]]+)\]", replace_bracket, text)


def _is_chinese_title(text: str) -> bool:
    """判断文本是否为中文标题（含全角标点）"""
    if not text:
        return False
    cleaned = re.sub(r"[！？：；，。、（）《》〈〉【】「」『』～·]", "", text)
    return StringUtils.is_all_chinese(cleaned) if cleaned else False


def _extract_slash_name(ctx: ParseContext, text: str) -> None:
    """处理 '中文 / English / 日文' 格式"""
    bracket_contents = re.findall(r"\[([^\]]+)\]", ctx.text)
    for bc in bracket_contents:
        if "/" not in bc:
            continue
        parts = [p.strip() for p in bc.split("/") if p.strip()]
        if len(parts) < 2:
            continue
        if _is_metadata(parts[0]) or _is_metadata(parts[-1]):
            continue
        cn_parts = [p for p in parts if _is_chinese_title(p)]
        en_parts = [p for p in parts if not StringUtils.is_chinese(p) and not _RE_KANA_TITLE.search(p)]
        if cn_parts:
            cn = re.sub(r"\s*\([^)]*\)\s*", " ", cn_parts[0]).strip()
            cn = re.sub(r"\s*第\s*\d+\s*季\s*$", "", cn).strip()
            ctx.cn_name = cn
        if en_parts:
            ctx.en_name = en_parts[-1]
        if ctx.cn_name or ctx.en_name:
            return

    parts = [p.strip() for p in text.split("/") if p.strip()]
    if len(parts) < 2:
        return
    left = _clean_cn_part(parts[0])
    right = parts[-1]
    if StringUtils.is_chinese(left) and not _is_chinese_title(right):
        ctx.cn_name = left
        ctx.en_name = right
    elif _is_chinese_title(right) and not StringUtils.is_chinese(left):
        ctx.en_name = left
        ctx.cn_name = _clean_cn_part(right)
    elif not StringUtils.is_chinese(right) or len(parts) > 1:
        ctx.en_name = right if not _is_chinese_title(right) else left


def _clean_cn_part(text: str) -> str:
    """清理中文名称段：移除括号别名、季数标记、尾部集数"""
    text = re.sub(r"\s*\([^)]*\)\s*", " ", text).strip()
    text = re.sub(r"\s*第\s*\d+\s*季\s*$", "", text).strip()
    text = re.sub(r"\s+-\s*\d+\s*$", "", text).strip()
    return text


def _extract_group_from_original(ctx: ParseContext, prepared_text: str, original_text: str) -> None:
    """从原始标题中提取被预处理移除的发布组括号（在所有 name 提取层之前执行）"""
    if ctx.release_group or original_text == prepared_text:
        return
    for m in re.finditer(r"\[([^\]]+)\]", original_text):
        inner = m.group(1).strip()
        if _GROUP_KEYWORDS_RE.search(inner) and not all(c in _CHINESE_META_CLEAN for c in inner):
            ctx.release_group = inner
            break


def _extract_bracket_name(ctx: ParseContext, prepared_text: str, original_text: str) -> None:
    """从方括号内容中提取名称（含 bracket 前的文本）"""
    release_group = str(ctx.release_group or "").strip()

    for m in re.finditer(r"\[([^\]]+)\]", prepared_text):
        bc_clean = m.group(1).strip().replace("_", " ").strip()
        if not bc_clean or len(bc_clean) < 2:
            continue
        if _is_metadata(bc_clean):
            continue
        if re.fullmatch(r"\d{1,3}", bc_clean):
            # 纯数字括号是集号/文件号标记（如 [13]、[01]），不是标题
            continue
        if release_group and bc_clean.upper() == release_group.upper():
            continue
        if _GROUP_KEYWORDS_RE.search(bc_clean):
            if not ctx.release_group:
                ctx.release_group = bc_clean
            continue

        # 提取 bracket 前的文本作为潜在中文名
        prefix = prepared_text[: m.start()].strip()
        cn_in_prefix = _extract_cn_from_prefix(prefix)
        if cn_in_prefix and not ctx.cn_name:
            ctx.cn_name = cn_in_prefix

        if StringUtils.is_chinese(bc_clean):
            ctx.cn_name = ctx.cn_name or bc_clean
        else:
            ctx.en_name = ctx.en_name or bc_clean
        if ctx.cn_name or ctx.en_name:
            return

    # fallback: 搜索中文名候选
    if not ctx.cn_name:
        bracket_contents = re.findall(r"\[([^\]]+)\]", prepared_text)
        for bc in bracket_contents:
            bc_clean = bc.strip().replace("_", " ").strip()
            if release_group and bc_clean.upper() == release_group.upper():
                continue
            if _GROUP_KEYWORDS_RE.search(bc_clean):
                continue
            if StringUtils.is_chinese(bc_clean) and len(bc_clean) >= 4:
                if all(c in _CHINESE_META_CLEAN for c in bc_clean):
                    continue
                ctx.cn_name = bc_clean
                break


def _extract_cn_from_prefix(text: str) -> str | None:
    """从 bracket 前的文本中提取中文名（处理 攻殻機動隊[Ghost 格式）"""
    if not text:
        return None
    # 取最后一个中文片段
    cn_match = re.search(r"[\u4e00-\u9fff\u3000-\u303F\uFF00-\uFFEF]+$", text)
    if cn_match:
        word = cn_match.group(0).strip()
        if _is_metadata(word):
            return None
        return word
    return None


def _extract_free_text(ctx: ParseContext, text: str) -> None:
    """从自由文本中提取名称"""
    text = re.sub(r"\[[^\]]*\]", "", text).strip()
    text = re.sub(r"「[^」]*」", " ", text).strip()  # 日文括号→空格防粘连
    text = re.sub(r"\[\s*\]", "", text).strip()
    text = re.sub(r"[\[\]]", "", text).strip()  # 残留单边括号
    text = re.sub(r"\([^)]*\)", "", text).strip()
    text = re.sub(r"\s*第\s*\d+\s*季\s*$", "", text)
    text = re.sub(r"\s+S\d{1,2}\s*$", "", text, flags=re.IGNORECASE)
    text = re.sub(r"\s+-\s*\d+\s*$", "", text)
    text = re.sub(r"-[^-]{1,10}-(?=\s|$)", "", text).strip()

    # ~...~ 为日文副标题标记 → 提取为 episode_title，不参与名称
    sub_match = re.search(r"~([^~]+)~", text)
    if sub_match:
        ctx.episode_title = sub_match.group(1).strip() or ctx.episode_title
        text = text.replace(sub_match.group(0), " ").strip()

    # 【...】CJK 全角方括号标签（生/附日字/字幕/内嵌等）→ 元数据，移除
    text = re.sub(r"【[^】]*(?:生|附日字|字幕|熟肉|生肉|内嵌|内封|外挂|日字|简繁|多语|双语)[^】]*】", " ", text).strip()

    # 提取发布组后缀 (空格-Name 格式)
    team_match = re.search(r"\s-\s*([A-Za-z][A-Za-z0-9]*)\s*$", text)
    if team_match:
        ctx.release_group = team_match.group(1)
        text = text[: team_match.start()].strip()

    # 替换非数字间的点为分隔符（含数字后的末尾点如 2045.）
    text = re.sub(r"(?<!\d)\.(?!\d)|(?<=\d)\.(?!\d)", " ", text)
    text = re.sub(r"\s+", " ", text).strip()
    # 剥离附加集标记（+SPx1、SP01、+OVA、OAD01 等）
    text = re.sub(r"\+?\s*(?:SP|OVA|OAD)\s*x?\s*\d+", "", text, flags=re.IGNORECASE).strip()

    # 移除十进制版本号
    text = re.sub(r"\b\d+\.\d+\b", "", text).strip()

    # 清理尾部方括号（追踪器标签如 [rartv]、[ettv] 等）
    text = re.sub(r"(?i)\[[a-z0-9]+\]\s*$", "", text).strip()

    # 清理尾部容器格式（.mkv .mp4 等），避免阻塞发布组提取
    text = re.sub(r"(?i)\b(mkv|mp4|avi|ts|m2ts|mov|wmv|flv|rmvb|iso|img)\s*$", "", text).strip()

    # 提取发布组后缀 (-DIy@Group / -GROUP / -Group@Site 格式)
    group_match = re.search(r"-([A-Za-z][A-Za-z0-9]*(?:@\w+)?)\s*$", text)
    if group_match:
        ctx.release_group = group_match.group(1)
        text = text[: group_match.start()].strip()

    # 通用后缀剥词：剥离尾部短词（语种缩写、质量标签等）
    while True:
        m = re.search(r"([A-Za-z0-9_]+)[!?。，,;；：:\s]*$", text)
        if not m or _is_likely_title_word(m.group(1)):
            break
        stripped = text[: m.start()].strip()
        if not stripped:
            break
        # 只剩 1-2 个词时视为标题，不再剥离
        if len(stripped.split()) <= 2:
            break
        text = stripped

    # 再次清理残留的点号
    text = re.sub(r"(?<!\d)\.(?!\d)|(?<=\d)\.(?!\d)", " ", text)
    text = re.sub(r"\s+", " ", text).strip()

    if not text or text in _ANIME_NO_WORDS:
        return
    if len(text) < 3 and not StringUtils.is_chinese(text):
        return

    words = text.split()
    if not words:
        return

    cn_parts: list[str] = []
    en_parts: list[str] = []
    for idx, word in enumerate(words):
        word = word.removesuffix("]")
        if not word:
            continue
        if _META_TOKEN_RE.match(word):
            continue
        if len(word) <= 2 and word.lower() in ("h", "x", "e", "ac", "dd", "he", "av"):
            continue
        if word.isdigit():
            # 纯数字词：位于名称中部（后面还有字母词）的是标题本体数字（The 100 Girlfriends），
            # 末尾孤立数字视为解析残留丢弃
            if any(w[:1].isalpha() for w in words[idx + 1 :]):
                en_parts.append(word)
            continue
        elif StringUtils.is_chinese(word):
            # 过滤纯元数据的汉字词（如 日语中字、新番、连载等）
            if _is_metadata(word):
                continue
            cn_parts.append(word)
        else:
            en_parts.append(word)

    # 仅填充缺失的名称，避免覆盖方括号层已提取的更可靠 cn/en 名
    if cn_parts and not ctx.cn_name:
        ctx.cn_name = " ".join(cn_parts)
    if en_parts and not ctx.en_name:
        ctx.en_name = " ".join(en_parts)


def _recover_from_original(ctx: ParseContext, original_text: str) -> None:
    """从原始标题恢复名称"""
    if "/" in original_text:
        for part in original_text.split("/"):
            part = part.strip()
            if StringUtils.is_all_chinese(part) and len(part) >= 2:
                ctx.cn_name = part
                break

    if not ctx.jp_title:
        parts = re.split(r"[/／]", original_text)
        for part in parts:
            part = part.strip()
            if _RE_KANA_TITLE.search(part):
                continue
            if re.search(r"[a-zA-Z]{3,}", part) and not re.search(r"[一-鿿]", part):
                ctx.jp_title = part.strip()
                break


_HIGH_FREQ_TITLE_WORDS = frozenset(
    {
        "the",
        "and",
        "for",
        "our",
        "you",
        "are",
        "not",
        "but",
        "all",
        "one",
        "of",
        "in",
        "to",
        "is",
        "it",
        "on",
        "at",
        "we",
        "no",
        "so",
        "be",
        "me",
        "my",
        "mr",
        "mrs",
        "ms",
        "dr",
        "st",
        "vs",
        "or",
    }
)


def _is_likely_title_word(word: str) -> bool:
    """常见标题词汇（非发布组）"""
    return word.lower() in _HIGH_FREQ_TITLE_WORDS or len(word) > 2


def _is_metadata(text: str) -> bool:
    """检测文本是否为元数据（非名称）"""
    if _META_TOKEN_RE.match(text):
        return True
    if all(c in _CHINESE_META_CLEAN for c in text):
        return True
    # 点分隔的多词元数据（如 WEB.1080p.AV1）
    dot_tokens = text.replace(".", " ").split()
    if len(dot_tokens) >= 2 and all(_META_TOKEN_RE.match(tk) for tk in dot_tokens):
        return True
    tokens = text.split()
    if len(tokens) >= 2 and all(_META_TOKEN_RE.match(tk) for tk in tokens):
        return True
    if len(tokens) >= 2 and all(all(c in _CHINESE_META_CLEAN for c in tk) for tk in tokens):
        return True
    if len(tokens) >= 2 and any(_META_TOKEN_RE.match(tk) for tk in tokens):
        non_meta = [tk for tk in tokens if not _META_TOKEN_RE.match(tk)]
        if all(all(c in _CHINESE_META_CLEAN for c in tk) for tk in non_meta):
            return True
    return False


def clean_names(ctx: ParseContext) -> None:
    """清理并标准化提取到的名称"""
    if ctx.cn_name:
        _, ctx.cn_name, _, _, _, _ = StringUtils.get_keyword_from_string(ctx.cn_name)
        if ctx.cn_name:
            ctx.cn_name = re.sub(rf"{_NAME_NOSTRING_RE}", "", ctx.cn_name, flags=re.IGNORECASE).strip()
            ctx.cn_name = re.sub(_NAME_CLEANUP_RE, "", ctx.cn_name, flags=re.IGNORECASE).strip()
            ctx.cn_name = to_simplified(ctx.cn_name)
    if ctx.en_name:
        ctx.en_name = re.sub(rf"{_NAME_NOSTRING_RE}", "", ctx.en_name, flags=re.IGNORECASE).strip()
        ctx.en_name = re.sub(_NAME_CLEANUP_RE, "", ctx.en_name, flags=re.IGNORECASE).strip()
        ctx.en_name = ctx.en_name.title()
