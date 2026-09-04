"""Plugin Market Source Repository — 市场源表持久化（实现 PluginMarketStore 契约）"""

from app.db.models import PLUGINMARKETSOURCE
from app.db.repositories.base_repository import BaseRepository
from app.services.plugin_market_service import MarketSource, PluginMarketStore


class PluginMarketRepository(BaseRepository, PluginMarketStore):
    """市场源仓储（DB 实现）"""

    @staticmethod
    def _to_source(row: PLUGINMARKETSOURCE) -> MarketSource:
        return MarketSource(
            name=row.NAME or "",
            url=row.URL or "",
            enabled=bool(row.ENABLED),
            auto_update=bool(row.AUTO_UPDATE),
            public_key=row.PUBLIC_KEY or "",
            last_sync_at=row.LAST_SYNC_AT or "",
            last_error=row.LAST_ERROR or "",
            source_id=row.SOURCE_ID or "",
        )

    def list(self) -> list[MarketSource]:
        with self.session() as db:
            rows = db.query(PLUGINMARKETSOURCE).order_by(PLUGINMARKETSOURCE.ID.asc()).all()
            return [self._to_source(r) for r in rows]

    def add(self, source: MarketSource) -> MarketSource:
        with self.session() as db:
            db.add(
                PLUGINMARKETSOURCE(
                    SOURCE_ID=source.source_id,
                    NAME=source.name,
                    URL=source.url,
                    PUBLIC_KEY=source.public_key,
                    ENABLED=1 if source.enabled else 0,
                    AUTO_UPDATE=1 if source.auto_update else 0,
                    LAST_SYNC_AT=source.last_sync_at,
                    LAST_ERROR=source.last_error,
                )
            )
            return source

    def update(self, source: MarketSource) -> MarketSource:
        with self.session() as db:
            row = db.query(PLUGINMARKETSOURCE).filter(PLUGINMARKETSOURCE.SOURCE_ID == source.source_id).first()
            if not row:
                raise ValueError(f"市场源不存在: {source.source_id}")
            row.NAME = source.name
            row.URL = source.url
            row.PUBLIC_KEY = source.public_key
            row.ENABLED = 1 if source.enabled else 0
            row.AUTO_UPDATE = 1 if source.auto_update else 0
            row.LAST_SYNC_AT = source.last_sync_at
            row.LAST_ERROR = source.last_error
            return source

    def delete(self, source_id: str) -> bool:
        with self.session() as db:
            row = db.query(PLUGINMARKETSOURCE).filter(PLUGINMARKETSOURCE.SOURCE_ID == source_id).first()
            if not row:
                return False
            db.delete(row)
            return True
