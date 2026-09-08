"""站点解析健康领域 Repository 接口."""

from typing import Protocol

from app.domain.entities.site_parse_health import SiteParseHealthEntity


class ISiteParseHealthRepository(Protocol):
    """站点解析健康仓储接口."""

    def upsert(self, site_id: int, check_date: str, data: dict) -> None: ...
    def latest(self, site_id: int) -> SiteParseHealthEntity | None: ...
    def latest_all(self) -> list[SiteParseHealthEntity]: ...
    def history(self, site_id: int, limit: int = 30) -> list[SiteParseHealthEntity]: ...
