"""
IndexerSiteConfig Repository
直接操作 INDEXER_SITE_CONFIG 表，封装 dialect 无关 upsert。
"""

from datetime import datetime

from sqlalchemy import delete, insert, inspect, select, update
from sqlalchemy.dialects.mysql import insert as mysql_insert
from sqlalchemy.dialects.postgresql import insert as postgresql_insert
from sqlalchemy.dialects.sqlite import insert as sqlite_insert

from app.db.models import INDEXERSITECONFIG
from app.db.repositories.base_repository import BaseRepository
from app.utils.json_utils import JsonUtils


class IndexerSiteConfigRepository(BaseRepository):
    """索引器站点配置原始仓储"""

    def upsert_site(
        self,
        site_name: str,
        source: str,
        public: bool | None = None,
        enabled: bool | None = None,
        download_setting: int | None = None,
        default_settings: dict | None = None,
    ) -> None:
        """插入或更新站点配置；首次写入后不再覆盖 source。"""
        now = datetime.now()
        values: dict = {
            "SITE_NAME": site_name,
            "SOURCE": source,
            "UPDATED_AT": now,
        }
        if public is not None:
            values["PUBLIC"] = 1 if public else 0
        if enabled is not None:
            values["ENABLED"] = 1 if enabled else 0
        if download_setting is not None:
            values["DOWNLOAD_SETTING"] = download_setting
        if default_settings is not None:
            values["DEFAULT_SETTINGS"] = JsonUtils.dumps(default_settings)

        dialect = self._dialect_name()
        if dialect == "sqlite":
            self._upsert_sqlite(values)
        elif dialect == "postgresql":
            self._upsert_postgresql(values)
        elif dialect == "mysql":
            self._upsert_mysql(values)
        else:
            self._upsert_fallback(values)

    def _dialect_name(self) -> str:
        with self.session() as db:
            return inspect(db.bind).dialect.name

    def _upsert_sqlite(self, values: dict) -> None:
        stmt = sqlite_insert(INDEXERSITECONFIG).values(values)
        set_ = {
            "UPDATED_AT": stmt.excluded.UPDATED_AT,
        }
        if "PUBLIC" in values:
            set_["PUBLIC"] = stmt.excluded.PUBLIC
        if "ENABLED" in values:
            set_["ENABLED"] = stmt.excluded.ENABLED
        if "DOWNLOAD_SETTING" in values:
            set_["DOWNLOAD_SETTING"] = stmt.excluded.DOWNLOAD_SETTING
        if "DEFAULT_SETTINGS" in values:
            set_["DEFAULT_SETTINGS"] = stmt.excluded.DEFAULT_SETTINGS
        stmt = stmt.on_conflict_do_update(
            index_elements=["SITE_NAME"],
            set_=set_,
        )
        with self.session() as db:
            db.execute(stmt)

    def _upsert_postgresql(self, values: dict) -> None:
        stmt = postgresql_insert(INDEXERSITECONFIG).values(values)
        set_ = {
            "UPDATED_AT": stmt.excluded.UPDATED_AT,
        }
        if "PUBLIC" in values:
            set_["PUBLIC"] = stmt.excluded.PUBLIC
        if "ENABLED" in values:
            set_["ENABLED"] = stmt.excluded.ENABLED
        if "DOWNLOAD_SETTING" in values:
            set_["DOWNLOAD_SETTING"] = stmt.excluded.DOWNLOAD_SETTING
        if "DEFAULT_SETTINGS" in values:
            set_["DEFAULT_SETTINGS"] = stmt.excluded.DEFAULT_SETTINGS
        stmt = stmt.on_conflict_do_update(
            index_elements=["SITE_NAME"],
            set_=set_,
        )
        with self.session() as db:
            db.execute(stmt)

    def _upsert_mysql(self, values: dict) -> None:

        stmt = mysql_insert(INDEXERSITECONFIG).values(values)
        update = {
            "UPDATED_AT": stmt.inserted.UPDATED_AT,
        }
        if "PUBLIC" in values:
            update["PUBLIC"] = stmt.inserted.PUBLIC
        if "ENABLED" in values:
            update["ENABLED"] = stmt.inserted.ENABLED
        if "DOWNLOAD_SETTING" in values:
            update["DOWNLOAD_SETTING"] = stmt.inserted.DOWNLOAD_SETTING
        if "DEFAULT_SETTINGS" in values:
            update["DEFAULT_SETTINGS"] = stmt.inserted.DEFAULT_SETTINGS
        stmt = stmt.on_duplicate_key_update(**update)
        with self.session() as db:
            db.execute(stmt)

    def _upsert_fallback(self, values: dict) -> None:
        site_name = values["SITE_NAME"]
        with self.session() as db:
            existing = db.execute(
                select(INDEXERSITECONFIG).where(INDEXERSITECONFIG.SITE_NAME == site_name)
            ).scalar_one_or_none()
            if existing:
                update_values = {k: v for k, v in values.items() if k not in ("SITE_NAME", "SOURCE")}
                if update_values:
                    db.execute(
                        update(INDEXERSITECONFIG).where(INDEXERSITECONFIG.SITE_NAME == site_name).values(update_values)
                    )
            else:
                values.setdefault("CREATED_AT", datetime.now())
                db.execute(insert(INDEXERSITECONFIG).values(values))

    def get_by_name(self, site_name: str):
        with self.session() as db:
            return db.execute(
                select(INDEXERSITECONFIG).where(INDEXERSITECONFIG.SITE_NAME == site_name)
            ).scalar_one_or_none()

    def get_by_id(self, id: int | str):
        with self.session() as db:
            return db.execute(select(INDEXERSITECONFIG).where(INDEXERSITECONFIG.ID == int(id))).scalar_one_or_none()

    def list_all(
        self, source: str | None = None, source_ne: str | None = None, enabled: bool | None = None
    ) -> list[INDEXERSITECONFIG]:
        with self.session() as db:
            query = select(INDEXERSITECONFIG)
            if source is not None:
                query = query.where(INDEXERSITECONFIG.SOURCE == source)
            if source_ne is not None:
                query = query.where(INDEXERSITECONFIG.SOURCE != source_ne)
            if enabled is not None:
                query = query.where(INDEXERSITECONFIG.ENABLED == (1 if enabled else 0))
            return list(db.execute(query).scalars().all())

    def list_enabled_names(self, source: str | None = None) -> list[str]:
        with self.session() as db:
            query = select(INDEXERSITECONFIG.SITE_NAME).where(INDEXERSITECONFIG.ENABLED == 1)
            if source is not None:
                query = query.where(INDEXERSITECONFIG.SOURCE == source)
            return [row[0] for row in db.execute(query).all()]

    def update_enabled(self, site_name: str, enabled: bool) -> None:
        with self.session() as db:
            db.execute(
                update(INDEXERSITECONFIG)
                .where(INDEXERSITECONFIG.SITE_NAME == site_name)
                .values(ENABLED=1 if enabled else 0, UPDATED_AT=datetime.now())
            )

    def update_download_setting(self, site_name: str, download_setting: int | None) -> None:
        with self.session() as db:
            db.execute(
                update(INDEXERSITECONFIG)
                .where(INDEXERSITECONFIG.SITE_NAME == site_name)
                .values(DOWNLOAD_SETTING=download_setting, UPDATED_AT=datetime.now())
            )

    def update_default_settings(self, site_name: str, default_settings: dict | None) -> None:
        with self.session() as db:
            db.execute(
                update(INDEXERSITECONFIG)
                .where(INDEXERSITECONFIG.SITE_NAME == site_name)
                .values(
                    DEFAULT_SETTINGS=JsonUtils.dumps(default_settings) if default_settings else None,
                    UPDATED_AT=datetime.now(),
                )
            )

    def migrate_from_user_indexer_sites(self, user_indexer_sites: list[int], site_name_by_id: dict[int, str]) -> None:
        """从 UserIndexerSites 迁移启用状态。"""
        enabled_names = {site_name_by_id[sid] for sid in user_indexer_sites if sid in site_name_by_id}
        for sid, name in site_name_by_id.items():
            self.upsert_site(
                site_name=name,
                source="builtin",
                enabled=name in enabled_names,
            )

    def delete_by_name(self, site_name: str) -> None:
        with self.session() as db:
            db.execute(delete(INDEXERSITECONFIG).where(INDEXERSITECONFIG.SITE_NAME == site_name))
