"""媒体标题领域校验器 — 过滤无效/垃圾标题，避免无意义的 TMDB 查询."""

import re

# 常见垃圾词黑名单（仅当标题完全由这些词组成时过滤）
_JUNK_WORDS = frozenset(
    [
        "www",
        "com",
        "net",
        "org",
        "tv",
        "download",
        "torrent",
        "magnet",
        "ddl",
        "free",
        "xxx",
        "porn",
        "adult",
        "sex",
        "hentai",
        "r18",
    ]
)

# 成人内容关键词（标题中包含任一即过滤）
_ADULT_PATTERNS = re.compile(
    r"\b(?:"
    r"sex|porn|adult|xxx|hentai|jav|無码|r18|erito|brazzers|realitykings|naughtyamerica|"
    r"bangbros|digitalplayground|teamskeet|mofos|fakehub|blacked|tushy|vixen|danejones|"
    r"bangbus|castingcouch|publicagent|massagerooms|lesbea|momxxx|femaleagent|"
    r"private\.com|privatecasting|legalporno|kink\.com|devianthardcore|"
    r"boundgangbangs|sexandsubmission|hogtied|whippedass|devicebondage|"
    r"obedient|collared|slut|whore|bitch|cumshot|blowjob|anal|threesome|gangbang|"
    r"interracial|milf|teen|mature|stepmom|stepsis|stepbro|stepdad|"
    r"alison tyler|ava addams|lisa ann|riley reid|mia khalifa|kimmy granger|"
    r"lena paul|abella danger|kendra lust|brandi love|jordi|johnny sins"
    r")\b",
    re.IGNORECASE,
)

# 垃圾模式：纯网址类、无意义组合
_GARBAGE_PATTERNS = re.compile(
    r"^(?:www\s+\w+|\w+\s+(?:com|net|org|tv|cc|io)\b(?!\.?\w)|"
    r"\w+\s+\.(?:me)\b|"
    r"(?:pthdtv|qqhdtv|hdtv|hd|4k|1080p|720p)\s*$|"
    r"^\w{1,3}\s+(?:hd|tv|com)$)"
    r"|\b(?:pthdtv|qqhdtv)\b",
    re.IGNORECASE,
)


def is_valid_media_title(name: str | None) -> bool:
    """
    校验解析后的媒体标题是否有效。

    规则：
    1. 不能为空
    2. 有效字符长度 >= 2
    3. 不能全部是垃圾词
    4. 不能包含成人内容关键词
    5. 不能是网址类垃圾组合

    :param name: 解析出的标题（en_name 或 cn_name）
    :return: 是否有效
    """
    if not name:
        return False
    cleaned = re.sub(r"[^\w\u4e00-\u9fff]", "", name.lower().strip())
    if len(cleaned) < 2:
        return False
    if cleaned in _JUNK_WORDS:
        return False
    if _ADULT_PATTERNS.search(name):
        return False
    if _GARBAGE_PATTERNS.search(name):
        return False
    return True
