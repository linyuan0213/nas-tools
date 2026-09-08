"""站点解析健康领域 Repository 适配器."""

from app.db.repositories.site_parse_health_repository import SiteParseHealthRepository
from app.domain.entities.site_parse_health import SiteParseHealthEntity
from app.domain.interfaces.site_parse_health_repo import ISiteParseHealthRepository


class SiteParseHealthRepositoryAdapter(ISiteParseHealthRepository):
    """站点解析健康仓储适配器."""

    def __init__(self, repo: SiteParseHealthRepository | None = None):
        self._repo = repo or SiteParseHealthRepository()

    def upsert(self, site_id: int, check_date: str, data: dict) -> None:
        self._repo.upsert(site_id=site_id, check_date=check_date, data=data)

    def latest(self, site_id: int) -> SiteParseHealthEntity | None:
        return SiteParseHealthEntity.from_orm(self._repo.latest(site_id))

    def latest_all(self) -> list[SiteParseHealthEntity]:
        rows = self._repo.latest_all()
        return [e for e in (SiteParseHealthEntity.from_orm(r) for r in rows) if e is not None]

    def history(self, site_id: int, limit: int = 30) -> list[SiteParseHealthEntity]:
        rows = self._repo.history(site_id, limit)
        return [e for e in (SiteParseHealthEntity.from_orm(r) for r in rows) if e is not None]
