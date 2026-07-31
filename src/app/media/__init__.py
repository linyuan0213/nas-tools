"""app.media — 媒体处理模块

重构后架构:
  - MediaService     — 文件名识别门面
  - MediaCache       — TMDB 详情缓存
  - MediaInfo        — pydantic 数据模型
  - parser/          — 文件名解析层
  - lookup/          — 外部数据库查询层
  - scraper/         — 元数据刮削层（NFO / 图片）
  - external/        — 第三方 API 客户端（豆瓣、Bangumi）
  - batch/           — 批量处理
  - cache/           — 缓存层
"""

from .batch import BatchProcessor
from .cache import MediaCache
from .external import Bangumi, DouBan
from .factory import get_media_cache
from .lookup import (
    BangumiLookup,
    BaseLookup,
    DoubanLookup,
    LookupResult,
    TmdbLookup,
)
from .models import MediaInfo
from .parser import (
    BaseParser,
    ParserResult,
    RegexParser,
    TokenAdapter,
)
from .parser._customization import CustomizationMatcher
from .parser._metainfo import meta_info
from .parser._release_groups import ReleaseGroupsMatcher
from .scraper import Scraper
from .service import MediaService

__all__ = [
    "MediaService",
    "MediaCache",
    "MediaInfo",
    "BatchProcessor",
    "BaseParser",
    "ParserResult",
    "RegexParser",
    "TokenAdapter",
    "BaseLookup",
    "LookupResult",
    "TmdbLookup",
    "DoubanLookup",
    "BangumiLookup",
    "DouBan",
    "Bangumi",
    "Scraper",
]
