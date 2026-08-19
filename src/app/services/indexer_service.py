"""
IndexerService - 索引器业务服务层
将 app/indexer/ 中散落的业务逻辑收口为可独立测试的 Service。
职责：
- 索引器站点查询与管理
- 搜索委托给 SearchService/Searcher（避免重复）
- 资源列表获取
- 索引器统计
"""

from typing import Any

from app.core.system_config import SystemConfig
from app.db.repositories.download_repo_adapter import IndexerStatisticsRepositoryAdapter
from app.db.repositories.indexer_config_repo_adapter import IndexerConfigRepositoryAdapter
from app.db.repositories.indexer_site_config_repo_adapter import IndexerSiteConfigRepositoryAdapter
from app.domain.enums import SystemConfigKey
from app.indexer import Indexer
from app.indexer.client import BuiltinIndexer
from app.indexer.configuration import IndexerHelper
from app.schemas.download import IndexerStatisticsDTO
from app.schemas.indexer import (
    IndexerClientInfoDTO,
    IndexerHashDTO,
    IndexerResourcesResultDTO,
    UserIndexerDTO,
)
from app.sites.engine import SiteEngine
from app.sites.site_cache import SiteCache
from app.utils import ExceptionUtils
from app.utils.submodule_loader import SubmoduleLoader


class IndexerService:
    """
    索引器业务服务
    不直接操作 HTTP 请求，接收/返回显式 DTO，依赖通过构造函数注入。
    """

    def __init__(
        self,
        indexer: Indexer,
        indexer_helper: IndexerHelper,
        site_cache: SiteCache,
        site_engine: SiteEngine,
        indexer_statistics_repo: IndexerStatisticsRepositoryAdapter,
        string_utils: Any,
        site_config_repo: IndexerSiteConfigRepositoryAdapter | None = None,
        idx_config_repo: IndexerConfigRepositoryAdapter | None = None,
    ):
        self._indexer = indexer
        self._indexer_helper = indexer_helper
        self._site_cache = site_cache
        self._site_engine = site_engine
        self._string_utils = string_utils
        self._indexer_statistics_repo = indexer_statistics_repo
        self._site_config_repo = site_config_repo or IndexerSiteConfigRepositoryAdapter()
        self._idx_config_repo = idx_config_repo or IndexerConfigRepositoryAdapter()

    @property
    def indexer(self) -> Indexer:
        return self._indexer

    # ------------------------------------------------------------------
    # 站点管理
    # ------------------------------------------------------------------

    def get_user_indexers(self) -> list[UserIndexerDTO]:
        """
        获取用户已经选择的索引器列表
        """
        return [UserIndexerDTO(id=index.id, name=index.name) for index in self._indexer.get_indexers(check=True)]

    def get_all_user_indexers(self) -> list[UserIndexerDTO]:
        """
        获取所有索引器的已启用站点（builtin + 第三方，过滤禁用索引器的站点）
        """
        seen = set()
        result: list[UserIndexerDTO] = []
        for indexer in self._indexer.get_indexers(check=True):
            key = indexer.name.lower()
            if key not in seen:
                seen.add(key)
                result.append(UserIndexerDTO(id=str(indexer.id), name=indexer.name))
        rows = self._site_config_repo.list_all(enabled=True, source_ne="builtin")
        for row in rows:
            key = row.site_name.lower()
            if key in seen:
                continue
            entity = self._idx_config_repo.get_by_client_id(row.source)
            if entity and not entity.enabled:
                continue
            seen.add(key)
            result.append(UserIndexerDTO(id=str(row.id or 0), name=row.site_name))
        return result

    def get_third_party_sites(self) -> list[dict]:
        """
        获取所有第三方索引器站点配置（过滤禁用索引器的站点）
        """
        rows = self._site_config_repo.list_all(source_ne="builtin")
        result = []
        for row in rows:
            entity = self._idx_config_repo.get_by_client_id(row.source)
            if entity and not entity.enabled:
                continue
            result.append(
                {
                    "id": row.id,
                    "site_name": row.site_name,
                    "source": row.source,
                    "download_setting": row.download_setting,
                    "enabled": row.enabled,
                    "public": row.public,
                }
            )
        return result

    def update_site_enabled(self, site_name: str, enabled: bool) -> None:
        """更新第三方站点启用状态"""
        self._site_config_repo.update_enabled(site_name=site_name, enabled=enabled)

    def update_site_download_setting(self, site_name: str, download_setting: int | None) -> None:
        """更新第三方站点下载设置"""
        self._site_config_repo.update_download_setting(site_name=site_name, download_setting=download_setting)

    def update_site_default_settings(self, site_name: str, default_settings: dict | None) -> None:
        """更新站点默认设置"""
        self._site_config_repo.update_default_settings(site_name=site_name, default_settings=default_settings)

    def sync_third_party_sites(self, client_id: str) -> bool:
        """手动同步指定第三方索引器的站点列表"""
        try:
            config = self._get_indexer_config(client_id)
            if not config:
                # 未配置该索引器，视为无需同步
                return True
            schemas = SubmoduleLoader.import_submodules(
                "app.indexer.client", filter_func=lambda _, obj: hasattr(obj, "client_id")
            )
            for schema in schemas:
                if schema.match(client_id):
                    client = schema(config)
                    indexers = client.get_indexers(check=False)
                    for indexer in indexers or []:
                        self._site_config_repo.upsert_site(
                            site_name=indexer.name,
                            source=client_id,
                            public=getattr(indexer, "public", False),
                        )
                    return True
            return False
        except Exception as e:
            ExceptionUtils.exception_traceback(e)
            return False

    def _get_indexer_config(self, client_id: str) -> dict:
        """获取指定索引器的配置"""
        indexer_config = SystemConfig().get(SystemConfigKey.IndexerConfig) or {}
        return indexer_config.get(client_id) or {}

    def get_indexer_hash_dict(self) -> dict[str, IndexerHashDTO]:
        """
        获取全部索引器的 Hash 字典（用于前端快速查找）
        """
        result: dict[str, IndexerHashDTO] = {}
        for item in self._indexer.get_indexers() or []:
            key = self._string_utils.md5_hash(item.name)
            result[key] = IndexerHashDTO(id=item.id, name=item.name, public=item.public, builtin=item.builtin)
        return result

    def get_user_indexer_names(self) -> list[str]:
        """获取当前用户可用的索引器站点名称（不触发第三方 HTTP 连通性检查）."""
        names: list[str] = []
        seen: set[str] = set()

        builtin_cfg = self._idx_config_repo.get_by_client_id("builtin")
        if builtin_cfg is None or builtin_cfg.enabled:
            for name in self._site_config_repo.list_enabled_names(source="builtin"):
                key = name.lower()
                if key not in seen:
                    seen.add(key)
                    names.append(name)

        third_party_rows = self._site_config_repo.list_all(enabled=True, source_ne="builtin")
        disabled_sources: set[str] = set()
        for row in third_party_rows:
            if row.source not in disabled_sources:
                entity = self._idx_config_repo.get_by_client_id(row.source)
                if entity and not entity.enabled:
                    disabled_sources.add(row.source)
            if row.source in disabled_sources:
                continue
            key = row.site_name.lower()
            if key not in seen:
                seen.add(key)
                names.append(row.site_name)

        return names

    # ------------------------------------------------------------------
    # 内置索引器（兼容旧调用）
    # ------------------------------------------------------------------

    def get_builtin_indexers(self, check: bool = True, indexer_id: str | None = None) -> Any:
        """
        获取内置索引器的索引站点
        :param check: 是否过滤用户选中
        :param indexer_id: 指定站点ID
        """
        return BuiltinIndexer(
            indexer_helper=self._indexer_helper,
            site_cache=self._site_cache,
            site_engine=self._site_engine,
        ).get_indexers(check=check, indexer_id=indexer_id)

    def get_builtin_user_indexers(self) -> list[UserIndexerDTO]:
        builtin = self._indexer.get_builtin_indexers(check=True)
        return [UserIndexerDTO(id=i.id, name=i.name) for i in builtin]

    # ------------------------------------------------------------------
    # 资源列表
    # ------------------------------------------------------------------

    def list_resources(
        self, index_id: str, page: int = 0, page_size: int = 100, keyword: str | None = None
    ) -> IndexerResourcesResultDTO:
        """
        获取内置索引器的资源列表
        :param index_id: 内置站点ID
        :param page: 页码
        :param page_size: 每页数量
        :param keyword: 搜索关键字
        """
        if not index_id:
            return IndexerResourcesResultDTO(success=True, data=[])
        resources = self._indexer.list_resources(index_id=index_id, page=page, page_size=page_size, keyword=keyword)
        if resources is None:
            return IndexerResourcesResultDTO(success=False, msg="获取站点资源出现错误，无法连接到站点！")
        return IndexerResourcesResultDTO(success=True, data=resources)

    # ------------------------------------------------------------------
    # 客户端信息
    # ------------------------------------------------------------------

    def get_client_info(self) -> IndexerClientInfoDTO:
        """
        获取当前索引器客户端信息
        """
        client = self._indexer.get_client()
        client_type = self._indexer.get_client_type()
        return IndexerClientInfoDTO(
            client_id=getattr(client, "client_id", "") if client else "",
            client_type=getattr(client_type, "value", "") if client_type else "",
            client_name=getattr(client, "client_name", "") if client else "",
        )

    def get_client(self) -> Any:
        """
        获取当前索引器客户端实例（低层兼容）
        """
        return self._indexer.get_client()

    def get_client_type(self) -> Any:
        """
        获取当前索引器类型（低层兼容）
        """
        return self._indexer.get_client_type()

    def search_by_keyword(self, key_word, filter_args, match_media=None, in_from=None):
        """
        根据关键字搜索（代理到底层 Indexer）
        """
        return self._indexer.search_by_keyword(
            key_word=key_word, filter_args=filter_args, match_media=match_media, in_from=in_from
        )

    def get_indexers(self, check: bool = False):
        """
        获取索引器列表（低层兼容）
        """
        return self._indexer.get_indexers(check=check)

    # ------------------------------------------------------------------
    # 统计
    # ------------------------------------------------------------------

    def get_indexer_statistics(self) -> tuple[list[IndexerStatisticsDTO], list[list]]:
        """
        获取索引器统计数据及图表 dataset
        :return: (统计数据列表, 图表数据集)
        """
        result = self._indexer.get_indexer_statistics()
        dataset = [["indexer", "avg"]]
        stats: list[IndexerStatisticsDTO] = []
        for row in result:
            avg = round(row.get("avg", 0) or 0, 1)
            stats.append(
                IndexerStatisticsDTO(
                    name=row.get("indexer", ""),
                    total=row.get("total", 0),
                    fail=row.get("fail", 0),
                    success=row.get("success", 0),
                    avg=avg,
                )
            )
            dataset.append([row.get("indexer", ""), str(avg)])
        return stats, dataset
