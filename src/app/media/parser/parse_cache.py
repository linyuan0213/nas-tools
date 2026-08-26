"""
标题解析缓存（性能优化）

meta_info() 是纯函数（标题+副标题 → MediaInfo），同一批种子在
多次搜索中高度重复 —— 缓存解析结果，重复搜索免去 anitopy/regex
全量解析开销。

调用方会修改返回对象（补 cn_name/year 等），命中时返回独立
反序列化副本，避免共享污染。
"""

import log
from app.domain.mediatypes import MediaType
from app.infrastructure.cache_system import get_cache_manager
from app.media.models import MediaInfo
from app.media.parser._metainfo import meta_info
from app.utils import StringUtils

_TTL = 24 * 3600

# 解析规则版本：规则变更（如集号/季号提取修复）时 +1，使旧缓存自动失效
_PARSER_VERSION = 4


class ParseCache:
    def __init__(self):
        self._cache = get_cache_manager().get_or_create("parse_cache", "tiered", memory_maxsize=5000, ttl=_TTL)

    @staticmethod
    def _key(title: str, subtitle: str | None, mtype: MediaType | None) -> str:
        raw = f"{title}\x00{subtitle or ''}\x00{mtype.value if mtype else ''}"
        return f"parse:v{_PARSER_VERSION}:{StringUtils.md5_hash(raw)}"

    def parse(self, title: str, subtitle: str | None = None, mtype: MediaType | None = None) -> MediaInfo:
        """带缓存的 meta_info：命中返回独立副本，未命中解析后写缓存"""
        key = self._key(title, subtitle, mtype)
        cached = self._cache.get(key)
        if cached is not None:
            return MediaInfo.model_validate_json(cached)
        info = meta_info(title=title, subtitle=subtitle, mtype=mtype)
        try:
            self._cache.set(key, info.model_dump_json(), ttl=_TTL)
        except Exception as e:
            log.debug(f"[ParseCache]写入失败: {e}")
        return info


_parse_cache: ParseCache | None = None


def get_parse_cache() -> ParseCache:
    global _parse_cache
    if _parse_cache is None:
        _parse_cache = ParseCache()
    return _parse_cache


def cached_meta_info(title: str, subtitle: str | None = None, mtype: MediaType | None = None) -> MediaInfo:
    return get_parse_cache().parse(title, subtitle, mtype)
