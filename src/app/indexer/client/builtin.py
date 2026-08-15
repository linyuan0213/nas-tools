"""
内置索引器客户端

职责：管理用户配置的站点，调用各站点爬虫执行搜索，返回原始结果。
所有过滤和识别逻辑已迁移到 app.indexer.core.SearchPipeline。
"""

import copy
import datetime
from threading import Lock

import log
from app.core.system_config import SystemConfig
from app.db.repositories.download_repository import DownloadRepository
from app.db.repositories.indexer_config_repo_adapter import IndexerConfigRepositoryAdapter
from app.db.repositories.indexer_site_config_repo_adapter import IndexerSiteConfigRepositoryAdapter
from app.domain.enums import ProgressKey, SearchType, SystemConfigKey
from app.indexer.client._base import _IIndexClient
from app.indexer.configuration import IndexerHelper
from app.indexer.schema import IndexerConfigSchema
from app.infrastructure.progress import ProgressTracker
from app.sites.engine import SiteEngine
from app.sites.searcher_factory import create_searcher
from app.sites.site_cache import SiteCache
from app.utils import StringUtils
from app.utils.config_tools import get_ua
from app.utils.json_utils import JsonUtils

_STATS_LOCK = Lock()

# 关键字搜索时的最大翻页数（安全上限，防止站点异常时无限翻页）
_MAX_SEARCH_PAGES = 5


class BuiltinIndexer(_IIndexClient):
    """
    内置索引器

    聚合所有用户配置的 PT/BT 站点，通过对应爬虫执行搜索。
    """

    client_id = "builtin"
    client_type = "builtin"
    client_name = "内置索引器"
    config_schema = IndexerConfigSchema(
        name="内置索引器",
        icon_url="/static/img/indexer/indexer.jpg",
        fields=[],
    )

    _client_config = {}
    _show_more_sites = False

    def __init__(
        self,
        config=None,
        *,
        indexer_helper: IndexerHelper,
        site_cache: SiteCache,
        site_engine: SiteEngine,
        progress_helper: ProgressTracker | None = None,
        download_repo: DownloadRepository | None = None,
        system_config: SystemConfig | None = None,
        site_config_repo: IndexerSiteConfigRepositoryAdapter | None = None,
        idx_config_repo: IndexerConfigRepositoryAdapter | None = None,
    ):
        self._client_config = config or {}
        self._indexer_helper = indexer_helper
        self._site_cache = site_cache
        self._progress = progress_helper or ProgressTracker()
        self._download_repo = download_repo or DownloadRepository()
        self._system_config = system_config or SystemConfig()
        self._site_engine = site_engine
        self._site_config_repo = site_config_repo or IndexerSiteConfigRepositoryAdapter()
        self._idx_config_repo = idx_config_repo or IndexerConfigRepositoryAdapter()
        # 站点级失败原因透传（list() 等不经 search() 的路径也会在 __search_via_engine 读取）
        self.last_error: str = ""

    @classmethod
    def match(cls, ctype):
        return ctype in [cls.client_id, cls.client_type, cls.client_name]

    def get_type(self):
        return self.client_type

    def get_client_id(self):
        return self.client_id

    def is_enabled(self) -> bool:
        entity = self._idx_config_repo.get_by_client_id("builtin")
        if entity is not None:
            return entity.enabled
        val = self._system_config.get(SystemConfigKey.BuiltinIndexerEnabled)
        return str(val or "1") != "0"

    def get_status(self):
        return True

    def get_indexers(self, check=True, indexer_id=None, public=True):
        """获取当前索引器的索引站点"""
        ret_indexers = []
        enabled_names = set(n.lower() for n in self._site_config_repo.list_enabled_names())
        _indexer_domains = []

        engine_sites = []
        for s in self._site_engine.all_sites():
            if s.html:
                engine_sites.append(
                    {
                        "id": s.id,
                        "name": s.name,
                        "domain": s.domain,
                        "domain_aliases": getattr(s, "domain_aliases", []),
                        "public": s.public,
                        "search": s.html.search,
                        "torrents": s.html.torrents,
                        "category": s.html.category,
                        "browse": s.html.browse,
                        "language": s.language,
                    }
                )
            elif s.api:
                engine_sites.append(
                    {
                        "id": s.id,
                        "name": s.name,
                        "domain": s.domain,
                        "domain_aliases": getattr(s, "domain_aliases", []),
                        "public": s.public,
                        "language": s.language,
                    }
                )
        self._indexer_helper.set_indexers(engine_sites)

        for site in self._site_cache.get_sites(public=True):
            url = site.get("signurl") or site.get("rssurl")
            cookie = site.get("cookie")
            headers = site.get("headers")
            is_public = site.get("public", False)

            if not url:
                continue
            has_auth = (
                cookie or headers or site.get("api_key") or site.get("bearer_token") or site.get("api_key_header")
            )
            if not is_public and not has_auth:
                continue

            render = bool(site.get("chrome"))
            indexer = self._indexer_helper.get_indexer(
                url=url,
                siteid=site.get("id"),
                cookie=cookie,
                ua=site.get("ua"),
                headers=site.get("headers"),
                api_key=site.get("api_key"),
                bearer_token=site.get("bearer_token"),
                name=site.get("name"),
                rule=site.get("rule"),
                pri=site.get("pri"),
                public=is_public,
                proxy=bool(site.get("proxy")),
                render=render,
                chrome=site.get("chrome"),
                browser_render=site.get("browser_render"),
            )
            if indexer:
                if indexer_id and (str(indexer.id) == str(indexer_id) or site.get("name") == indexer_id):
                    return indexer
                if check and indexer.name.lower() not in enabled_names:
                    continue
                if indexer.domain not in _indexer_domains:
                    _indexer_domains.append(indexer.domain)
                    indexer.name = site.get("name")
                    ret_indexers.append(indexer)

        return None if indexer_id else ret_indexers

    def search(self, order_seq, indexer, key_word, filter_args: dict, match_media, in_from: SearchType):
        """
        根据关键字搜索单个站点，返回原始结果（dict 列表）

        原始结果会自动注入站点元信息字段：
        - _indexer_name
        - _indexer_order
        - _indexer_public
        """
        progress_key = ProgressKey.SubscribeSearch if in_from == SearchType.SUBSCRIBE else ProgressKey.Search
        if not indexer or not key_word:
            return []

        # 站点流控
        if self._site_cache.check_ratelimit(indexer.siteid):
            self._progress.update(ptype=progress_key, text=f"{indexer.name} 触发站点流控，跳过 ...")
            return []

        if filter_args is None:
            _filter_args = {}
        else:
            _filter_args = copy.deepcopy(filter_args)

        if _filter_args.get("site") and indexer.name not in _filter_args.get("site"):
            return []

        if not _filter_args.get("rule") and indexer.rule:
            _filter_args.update({"rule": indexer.rule})

        start_time = datetime.datetime.now()
        log.info(f"[{self.client_name}]开始搜索Indexer：{indexer.name} ...")

        search_word = StringUtils.handler_special_chars(text=key_word, replace_word=" ", allow_space=True)
        if indexer.language == "en" and StringUtils.is_chinese(search_word):
            log.warn(f"[{self.client_name}]{indexer.name} 无法使用中文名搜索")
            return []

        result_array = []
        error_flag = False
        self.last_error = ""
        mtype = match_media.type if (match_media and match_media.tmdb_info) else None
        try:
            error_flag, result_array = self.__search_via_engine(
                search_word=search_word, indexer=indexer, mtype=mtype, paginate=True
            )
        except Exception as err:
            error_flag = True
            log.warn(f"[{self.client_name}]{indexer.name} 搜索失败: {err}")

        seconds = round((datetime.datetime.now() - start_time).seconds, 1)

        # 索引统计
        with _STATS_LOCK:
            self._download_repo.insert_indexer_statistics(
                indexer=indexer.name, itype=self.client_id, seconds=seconds, result="N" if error_flag else "Y"
            )

        if len(result_array) == 0:
            log.warn(f"[{self.client_name}]{indexer.name} 关键词 {key_word} 未搜索到数据")
            self._progress.update(ptype=progress_key, text=f"{indexer.name} 关键词 {key_word} 未搜索到数据")
            return []
        else:
            log.warn(f"[{self.client_name}]{indexer.name} 关键词 {key_word} 返回数据：{len(result_array)}")
            self._progress.update(
                ptype=progress_key, text=f"{indexer.name} 关键词 {key_word} 返回 {len(result_array)} 条数据"
            )

        # 注入站点元信息
        for item in result_array:
            item["_indexer_name"] = indexer.name
            item["_indexer_order"] = order_seq
            item["_indexer_public"] = getattr(indexer, "public", False)
            item["_indexer_source"] = self.client_type or self.client_id

        return result_array

    def list(self, index_id, page=0, keyword=None):
        """
        根据站点ID搜索站点首页资源
        """
        if not index_id:
            return None
        indexer = self.get_indexers(indexer_id=index_id)
        if not indexer:
            log.warn(f"[BuiltinIndexer]list 未找到站点: {index_id}")
            return None

        log.warn(f"[BuiltinIndexer]list 找到站点: {indexer.name} (id={indexer.id}, domain={indexer.domain})")  # type: ignore[union-attr]
        start_time = datetime.datetime.now()

        error_flag, result_array = self.__search_via_engine(search_word=keyword, indexer=indexer, page=page)

        seconds = round((datetime.datetime.now() - start_time).seconds, 1)
        with _STATS_LOCK:
            self._download_repo.insert_indexer_statistics(
                indexer=indexer.name,  # type: ignore[union-attr]
                itype=self.client_id,
                seconds=seconds,
                result="N" if error_flag else "Y",  # type: ignore[union-attr]
            )
        return result_array

    def __search_via_engine(self, search_word, indexer, mtype=None, page=0, paginate=False):
        engine = self._site_engine
        site_def = engine.get_by_id(str(indexer.id)) or engine.get_by_url(indexer.domain or "")
        if not site_def or not (site_def.api or site_def.html):
            return True, []
        user_config = self._build_user_config(indexer)
        searcher = create_searcher(indexer.domain, site_engine=self._site_engine, user_config=user_config)
        if not searcher:
            return True, []

        # 分页拉取：关键字搜索时循环翻页直到无更多结果，避免海贼王等长剧集只取到首页
        result_array = []
        try:
            if not paginate:
                result_array = searcher.search(keyword=search_word, page=page, mtype=mtype)
            else:
                seen: set = set()
                first_page_count = None
                cur_page = page
                while cur_page - page < _MAX_SEARCH_PAGES:
                    batch = searcher.search(keyword=search_word, page=cur_page, mtype=mtype)
                    if not batch:
                        break
                    new_count = 0
                    for it in batch:
                        key = (it.get("title", ""), it.get("enclosure", "") or it.get("size", ""))
                        if key in seen:
                            continue
                        seen.add(key)
                        result_array.append(it)
                        new_count += 1
                    # 站点忽略翻页参数返回重复数据，停止
                    if new_count == 0:
                        break
                    if first_page_count is None:
                        first_page_count = len(batch)
                    if len(batch) < first_page_count:
                        break
                    cur_page += 1
        finally:
            # 站点级失败原因（HTTP 状态码 / 异常类型）透传给上层，用于搜索状态展示
            self.last_error = getattr(searcher, "last_error", "") or self.last_error

        for item in result_array:
            if "indexer" not in item:
                item["indexer"] = indexer.id or indexer.siteid
            if site_def.api and "page_url" not in item:
                tid = ""
                dl_url = item.get("enclosure", "")
                if dl_url:
                    tid = engine._extract_tid(dl_url, site_def) or ""
                if site_def.detail_page_url and tid:
                    detail = site_def.detail_page_url.format(tid=tid)
                    if detail.startswith("/"):
                        # 详情页地址优先使用用户配置的站点域名（签到域名/别名），回退站点规范域名
                        base = (getattr(indexer, "domain", "") or "").rstrip("/")
                        if not base and site_def.domain:
                            base = (
                                site_def.domain if site_def.domain.startswith("http") else f"https://{site_def.domain}"
                            )
                        detail = f"{base}{detail}" if base else detail
                    item["page_url"] = detail
        return False, result_array

    @staticmethod
    def _build_user_config(indexer):
        user_config = {
            "cookie": getattr(indexer, "cookie", "") or "",
            "ua": getattr(indexer, "ua", "") or get_ua(),
            "proxy": getattr(indexer, "proxy", False),
            "headers": getattr(indexer, "headers", {}) or {},
            "domain": getattr(indexer, "domain", "") or "",
            "api_key": getattr(indexer, "api_key", "") or "",
            "bearer_token": getattr(indexer, "bearer_token", "") or "",
            "chrome": getattr(indexer, "chrome", False),
            "browser_render": getattr(indexer, "browser_render", False),
        }
        if indexer.headers and not user_config.get("api_key") and not user_config.get("bearer_token"):
            try:
                h = JsonUtils.loads(indexer.headers) if isinstance(indexer.headers, str) else indexer.headers
                auth_val = (h or {}).get("Authorization") or (h or {}).get("authorization") or ""
                if auth_val.startswith("Bearer "):
                    user_config["api_key"] = auth_val[len("Bearer ") :]
            except Exception as e:  # noqa: BLE001
                log.debug(f"[BuiltinIndexer]解析 headers 失败: {e}")
        return user_config
