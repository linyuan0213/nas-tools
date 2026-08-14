"""
索引器管理模块

职责：
1. 管理所有索引器客户端（Builtin、Prowlarr、Jackett）
2. 并发调度多站点搜索
3. 收集所有原始结果后，统一调用 SearchPipeline 进行批量识别和过滤
"""

import datetime
import threading
import time
from concurrent.futures import FIRST_COMPLETED, ThreadPoolExecutor, wait

import log
from app.core.system_config import SystemConfig
from app.db.repositories.download_repository import DownloadRepository
from app.db.repositories.indexer_config_repo_adapter import IndexerConfigRepositoryAdapter
from app.db.repositories.indexer_site_config_repo_adapter import IndexerSiteConfigRepositoryAdapter
from app.domain.enums import ProgressKey, SearchType, SystemConfigKey
from app.indexer.client._base import _IIndexClient
from app.indexer.configuration import IndexerHelper
from app.indexer.core.pipeline import SearchPipeline
from app.indexer.registry import get_all_clients, get_client_class
from app.infrastructure.cache_system import get_cache_manager
from app.infrastructure.progress import ProgressTracker
from app.sites.engine import SiteEngine
from app.sites.site_cache import SiteCache
from app.utils import ExceptionUtils, StringUtils

# 站点级搜索超时上下限（秒）：按历史延迟在区间内自适应
_SITE_TIMEOUT_MIN = 10.0
_SITE_TIMEOUT_MAX = 30.0


class SiteLatencyTracker:
    """站点搜索延迟跟踪：按最近样本 p95 × 1.5 自适应超时，慢站不拖垮每次搜索"""

    _KEEP = 20
    _TTL = 7 * 24 * 3600

    def __init__(self):
        self._cache = get_cache_manager().get_or_create("site_latency", "tiered", memory_maxsize=300, ttl=self._TTL)

    def timeout_for(self, indexer) -> float:
        samples = self._cache.get(f"lat:{indexer.name}") or []
        if len(samples) < 3:
            return _SITE_TIMEOUT_MAX
        ordered = sorted(samples)
        p95 = ordered[max(0, int(len(ordered) * 0.95) - 1)]
        return min(_SITE_TIMEOUT_MAX, max(_SITE_TIMEOUT_MIN, round(p95 * 1.5, 1)))

    def record(self, indexer, seconds: float) -> None:
        key = f"lat:{indexer.name}"
        samples = self._cache.get(key) or []
        samples.append(round(seconds, 2))
        self._cache.set(key, samples[-self._KEEP :], ttl=self._TTL)


_tracker: SiteLatencyTracker | None = None


def get_site_latency_tracker() -> SiteLatencyTracker:
    global _tracker
    if _tracker is None:
        _tracker = SiteLatencyTracker()
    return _tracker


def collect_search_results(futures: dict, timeout_for, on_advance=None) -> list:
    """
    带站点级超时的并发结果收集。

    :param futures: {Future: (client, indexer)}
    :param timeout_for: 按站点返回超时秒数的回调，超时放弃等待（线程由 HTTP 层自然终结）
    :param on_advance: 每完成/超时一个站点的回调
        (completed, total, indexer, timed_out, elapsed, site_status)
        site_status: {"name", "status": ok/error/timeout, "count", "error"}
    """
    pending = dict(futures)
    started = {f: time.monotonic() for f in futures}
    total = len(futures)
    completed = 0
    results: list = []
    while pending:
        done, _ = wait(list(pending), timeout=0.5, return_when=FIRST_COMPLETED)
        for future in done:
            client, indexer = pending.pop(future)
            completed += 1
            elapsed = time.monotonic() - started[future]
            site_status = {"name": indexer.name, "status": "ok", "count": 0, "error": ""}
            try:
                result = future.result()
                if result:
                    results.extend(result)
                    site_status["count"] = len(result)
            except Exception:
                site_status["status"] = "error"
                site_status["error"] = getattr(client, "last_error", "") or "执行异常"
                log.error(f"[Indexer]{client.client_id} 搜索 {indexer.name} 失败")
            else:
                err = getattr(client, "last_error", "")
                if not result and err:
                    site_status["status"] = "error"
                    site_status["error"] = err
            if on_advance:
                on_advance(completed, total, indexer, False, elapsed, site_status)
        now = time.monotonic()
        for future, (client, indexer) in list(pending.items()):
            limit = timeout_for(indexer)
            if now - started[future] > limit:
                pending.pop(future)
                completed += 1
                elapsed = now - started[future]
                log.warn(f"[Indexer]{indexer.name} 搜索超时({limit}s)，跳过")
                if on_advance:
                    on_advance(
                        completed,
                        total,
                        indexer,
                        True,
                        elapsed,
                        {"name": indexer.name, "status": "timeout", "count": 0, "error": f"超过 {limit}s"},
                    )
    return results


class Indexer:
    """索引器管理.

    搜索流程：
    1. 获取所有可用站点
    2. 并发搜索每个站点，收集原始结果（dict 列表）
    3. 将所有原始结果传入 SearchPipeline，统一批量识别和过滤
    4. 返回最终结果（meta_info 列表）
    """

    def __init__(
        self,
        search_pipeline: SearchPipeline,
        indexer_helper: IndexerHelper,
        site_cache: SiteCache,
        site_engine: SiteEngine,
        progress_helper: ProgressTracker | None = None,
        download_repo: DownloadRepository | None = None,
        system_config: SystemConfig | None = None,
        site_config_repo: IndexerSiteConfigRepositoryAdapter | None = None,
        idx_config_repo: IndexerConfigRepositoryAdapter | None = None,
    ):
        self.progress = progress_helper or ProgressTracker()
        self.download_repo = download_repo or DownloadRepository()
        self._pipeline = search_pipeline
        self._system_config = system_config or SystemConfig()
        self._indexer_helper = indexer_helper
        self._site_cache = site_cache
        self._site_engine = site_engine
        self._site_config_repo = site_config_repo or IndexerSiteConfigRepositoryAdapter()
        self._idx_config_repo = idx_config_repo or IndexerConfigRepositoryAdapter()
        self._client = None
        self._client_type = None
        self._clients: dict[str, _IIndexClient] = {}
        self._clients_lock = threading.Lock()

    def _ensure_client(self) -> None:
        """延迟加载 builtin 索引器客户端（兼容旧调用）"""
        if self._client is not None:
            return
        self._client = self.__get_client("builtin")
        self._client_type = self._client.get_type() if self._client else None

    def _ensure_clients(self) -> None:
        """延迟加载所有已配置的索引器客户端"""
        with self._clients_lock:
            if self._clients:
                return
            clients: dict[str, _IIndexClient] = {}
            builtin_cfg = self._idx_config_repo.get_by_client_id("builtin")
            if builtin_cfg is None or builtin_cfg.enabled:
                builtin = self.__get_client("builtin")
                if builtin:
                    clients["builtin"] = builtin
            for ctype in ("jackett", "prowlarr"):
                entity = self._idx_config_repo.get_by_client_id(ctype)
                if entity is None or not entity.config:
                    continue
                cfg = entity.config
                if not cfg.get("host") or not cfg.get("api_key"):
                    continue
                if not entity.enabled:
                    continue
                client = self.__get_client(ctype, cfg)
                if client:
                    clients[ctype] = client
            self._clients = clients

    def __build_class(self, ctype, conf=None):
        ctype_str = ctype.value if hasattr(ctype, "value") else ctype
        for cls in get_all_clients():
            try:
                if cls.match(ctype_str):
                    if ctype_str == "builtin":
                        return cls(
                            conf,
                            indexer_helper=self._indexer_helper,
                            site_cache=self._site_cache,
                            site_engine=self._site_engine,
                            download_repo=self.download_repo,
                            idx_config_repo=self._idx_config_repo,
                        )
                    return cls(conf, download_repo=self.download_repo)
            except Exception as e:
                ExceptionUtils.exception_traceback(e)
        return None

    def __get_client(self, ctype, conf=None):
        return self.__build_class(ctype=ctype, conf=conf)

    def _refresh(self):
        """重置客户端缓存，下次访问时重新加载"""
        self._client = None
        self._client_type = None
        self._clients = {}

    def get_client(self):
        self._ensure_client()
        return self._client

    def get_client_type(self):
        self._ensure_client()
        return self._client_type

    def get_indexers(self, check=False):
        """获取默认搜索索引器的站点列表（兼容旧调用）"""
        self._ensure_client()
        if not self._client:
            return []
        return self._client.get_indexers(check=check)

    def get_all_search_indexers(self, check=True):
        """获取所有已启用索引器的站点列表"""
        self._ensure_clients()
        indexers = []
        for client in self._clients.values():
            indexers.extend(self._filter_indexers(client, check=check))
        return indexers

    def _filter_indexers(self, client, check=True, filter_args=None):
        if not getattr(client, "is_enabled", lambda: True)():
            return []
        indexers = client.get_indexers(check=check)
        # 第三方索引器需要再用 DB 中的 enabled 状态过滤一次
        if client.get_client_id() != "builtin":
            enabled_names = set(self._site_config_repo.list_enabled_names(source=client.get_client_id()))
            indexers = [i for i in indexers if i.name in enabled_names]
        if filter_args and filter_args.get("site") is not None:
            # site 为 None → 不限制（WEB 搜索默认全部）
            # site 为空列表 → 订阅未配置站点，搜索零站点（不搜全站）
            site_filter = filter_args.get("site")
            indexers = [i for i in indexers if i.name in site_filter]
        return indexers

    def get_user_indexer_dict(self):
        return [{"id": index.id, "name": index.name} for index in self.get_indexers(check=True)]

    def get_indexer_hash_dict(self):
        indexer_dict = {}
        for item in self.get_indexers() or []:
            indexer_dict[StringUtils.md5_hash(item.name)] = {
                "id": item.id,
                "name": item.name,
                "public": item.public,
                "builtin": item.builtin,
            }
        return indexer_dict

    def get_user_indexer_names(self):
        return [indexer.name for indexer in self.get_indexers(check=True)]

    def get_builtin_indexers(self, check=True, indexer_id=None):
        cls = get_client_class("builtin")
        if cls:
            return cls(
                indexer_helper=self._indexer_helper,
                site_cache=self._site_cache,
                site_engine=self._site_engine,
                download_repo=self.download_repo,
            ).get_indexers(check=check, indexer_id=indexer_id)
        return []

    def list_resources(self, index_id, page=0, keyword=None):
        if not index_id:
            return []
        builtin_cls = get_client_class("builtin")
        if builtin_cls:
            result = builtin_cls(
                indexer_helper=self._indexer_helper,
                site_cache=self._site_cache,
                site_engine=self._site_engine,
                download_repo=self.download_repo,
            ).list(index_id=index_id, page=page, keyword=keyword)
            if result is not None:
                return result
        site_config = self._site_config_repo.get_by_id(index_id)
        if site_config:
            if site_config.source == "builtin" and builtin_cls:
                result = builtin_cls(
                    indexer_helper=self._indexer_helper,
                    site_cache=self._site_cache,
                    site_engine=self._site_engine,
                    download_repo=self.download_repo,
                ).list(index_id=site_config.site_name, page=page, keyword=keyword)
                if result is not None:
                    return result
            elif site_config.source and site_config.source != "builtin":
                self._ensure_clients()
                idx_config = self._system_config.get(SystemConfigKey.IndexerConfig) or {}
                cfg = idx_config.get(site_config.source, {})
                client = self._clients.get(site_config.source) or self.__get_client(site_config.source, cfg)
                if client:
                    result = client.list(index_id=site_config.site_name, page=page, keyword=keyword)
                    if result is not None:
                        return result
        return None

    def search_by_keyword(self, key_word, filter_args: dict, match_media=None, in_from: SearchType | None = None):
        """
        根据关键字调用所有已配置索引器并发搜索

        :param key_word: 搜索关键词
        :param filter_args: 过滤条件
        :param match_media: 需要匹配的媒体信息
        :param in_from: 搜索渠道
        :return: 命中的资源媒体信息列表
        """
        if not key_word:
            return []

        # 优先使用调用方传入的 per-session progress key（WEB 搜索按会话隔离进度）
        progress_key = filter_args.get("progress_key") or (
            ProgressKey.SubscribeSearch if in_from == SearchType.SUBSCRIBE else ProgressKey.Search
        )
        self._ensure_clients()
        if not self._clients:
            log.error("没有配置索引器，无法搜索！")
            return []

        # 扁平化所有 (client, indexer) 工作项
        work_items = []
        for client in self._clients.values():
            indexers = self._filter_indexers(client, check=True, filter_args=filter_args)
            for indexer in indexers:
                order_seq = 100 - int(getattr(indexer, "pri", 0))
                work_items.append((client, indexer, order_seq))

        # 同域名索引器去重：内置优先，跳过被内置覆盖的第三方(如 jackett)重复站点
        builtin_domains = {
            StringUtils.get_url_domain(getattr(indexer, "domain", "") or "")
            for client, indexer, _ in work_items
            if client.get_client_id() == "builtin"
        }
        builtin_domains.discard("")
        if builtin_domains:
            filtered_items = []
            for client, indexer, order_seq in work_items:
                if client.get_client_id() != "builtin":
                    dom = StringUtils.get_url_domain(getattr(indexer, "domain", "") or "")
                    if dom and dom in builtin_domains:
                        log.info(f"[Indexer]跳过第三方重复站点 {indexer.name}（内置已覆盖 {dom}）")
                        continue
                filtered_items.append((client, indexer, order_seq))
            work_items = filtered_items

        if not work_items:
            log.error("没有可用索引器站点，无法搜索！")
            return []

        start_time = datetime.datetime.now()
        max_workers = min(len(work_items), 15)

        if filter_args and filter_args.get("site"):
            log.info("开始搜索 %s，站点：%s，并发数：%s ..." % (key_word, filter_args.get("site"), max_workers))
            self.progress.update(
                ptype=progress_key, text="开始搜索 {}，站点：{} ...".format(key_word, filter_args.get("site"))
            )
        else:
            log.info("开始并行搜索 %s，工作项：%s，并发数：%s ..." % (key_word, len(work_items), max_workers))
            self.progress.update(ptype=progress_key, text=f"开始并行搜索 {key_word}，站点数：{len(work_items)} ...")

        # ---------- 阶段1：单层并发搜索，站点级超时熔断 ----------
        executor = ThreadPoolExecutor(max_workers=max_workers)
        try:
            futures = {
                executor.submit(client.search, order_seq, indexer, key_word, filter_args, match_media, in_from): (
                    client,
                    indexer,
                )
                for client, indexer, order_seq in work_items
            }

            tracker = get_site_latency_tracker()
            site_statuses: list[dict] = []

            def _on_advance(completed, total, indexer, timed_out, elapsed, site_status=None):
                tracker.record(indexer, elapsed)
                pct = 10 + round(50 * (completed / total))
                tag = "超时跳过" if timed_out else "完成"
                text = f"站点搜索 {completed}/{total} {tag}（{indexer.name}）"
                if site_status:
                    if site_status.get("status") == "ok":
                        text += f"：{site_status['count']} 条"
                    elif site_status.get("error"):
                        text += f"：{site_status['error']}"
                self.progress.update_max(ptype=progress_key, value=pct, text=text)
                if site_status:
                    site_statuses.append(site_status)
                    detail = self.progress.get_process(progress_key)
                    if detail is not None:
                        detail["sites"] = list(site_statuses)

            all_raw_results = collect_search_results(futures, timeout_for=tracker.timeout_for, on_advance=_on_advance)
        finally:
            executor.shutdown(wait=False)

        # ---------- 阶段2：去重 + 统一批量识别和过滤 ----------
        pipeline_result = self._pipeline.process(
            all_results=self._dedup(all_raw_results),
            filter_args=filter_args,
            match_media=match_media,
            in_from=in_from,
            progress_key=progress_key,
            search_name=key_word,
        )

        end_time = datetime.datetime.now()
        failed_sites = [s for s in site_statuses if s.get("status") in ("error", "timeout")]
        failed_summary = ""
        if failed_sites:
            failed_summary = "；失败站点：" + "、".join(
                f"{s['name']}({s.get('error') or s['status']})" for s in failed_sites
            )
        log.info(
            f"搜索关键词 {key_word} 所有站点完成，"
            f"原始结果 {len(all_raw_results)} 条，有效资源数：{len(pipeline_result.results)}，"
            f"总耗时 {(end_time - start_time).seconds} 秒{failed_summary}"
        )
        self.progress.update(
            ptype=progress_key,
            text=(
                f"搜索关键词 {key_word} 所有站点完成，"
                f"有效资源数：{len(pipeline_result.results)}，"
                f"总耗时 {(end_time - start_time).seconds} 秒{failed_summary}"
            ),
        )

        return pipeline_result.results

    @staticmethod
    def _dedup(results: list[dict]) -> list[dict]:
        """按 (title, size) 去重；builtin 来源优先，同来源 order_seq 大者（pri 小=主站）优先"""
        ordered = sorted(
            results,
            key=lambda r: (0 if r.get("_indexer_source") == "builtin" else 1, -r.get("_indexer_order", 0)),
        )
        seen: set[tuple] = set()
        deduped: list[dict] = []
        for r in ordered:
            key = (r.get("title", ""), r.get("size", ""))
            if key not in seen:
                seen.add(key)
                deduped.append(r)
        return deduped

    def get_indexer_statistics(self):
        """获取所有索引器统计信息"""
        self._ensure_clients()
        log.warn(f"[Indexer]统计：已加载客户端 {list(self._clients.keys())}")
        stats = []
        for client in self._clients.values():
            rows = self.download_repo.get_indexer_statistics(client.get_client_id())
            for row in rows:
                stats.append(
                    {
                        "indexer": row[0],
                        "total": row[1],
                        "fail": row[2],
                        "success": row[3],
                        "avg": row[4] or 0,
                    }
                )
        return stats
