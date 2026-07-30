"""搜索上下文类型 — 避免 search_service 与 search_orchestrator 之间的循环导入."""

from dataclasses import dataclass
from typing import Any

from app.domain.enums import SearchType
from app.domain.mediatypes import MediaType


@dataclass
class SearchContext:
    keyword: str
    session_id: str
    search_type: SearchType
    match_media: Any | None = None
    media_type: MediaType | None = None
    ident_flag: bool = True
    filter_args: dict | None = None
    auto_download: bool = False
    persist: bool = True
    user_name: str | None = None
    no_exists: dict | None = None
    notify_progress: bool = False
    ttl_hours: int = 24
    user_id: str | None = None
