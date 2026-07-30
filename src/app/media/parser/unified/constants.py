"""统一解析引擎 — 常量定义"""

_ANIME_NO_WORDS = ["CHS&CHT", "MP4", "GB MP4", "WEB-DL"]
_NAME_NOSTRING_RE = r"S\d{2}\s*-\s*S\d{2}|S\d{2}|\s+S\d{1,2}|EP?\d{2,4}\s*-\s*EP?\d{2,4}|EP?\d{2,4}|\s+EP?\d{1,4}"
_NAME_CLEANUP_RE = r"\b(?:19\d{2}|20[0-2]\d|2030)\b|\b(C(?:omplete|OMPLETE)|全集|合集|Season\s+\d+)\b"
