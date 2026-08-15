from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Any, cast

import log
from app.core.exceptions import DomainError, RepositoryError, ServiceError  # noqa: F401
from app.db.repositories.indexer_config_repo_adapter import IndexerConfigRepositoryAdapter
from app.db.repositories.indexer_site_config_repo_adapter import IndexerSiteConfigRepositoryAdapter
from app.db.repositories.site_repository import SiteRepository
from app.domain.entities.site import SiteEntity
from app.domain.enums import SiteUseType
from app.domain.interfaces.site_repo import ISiteRepository
from app.media import meta_info
from app.schemas.site import (
    SiteActivityDTO,
    SiteAttrDTO,
    SiteDefinitionDTO,
    SiteDetailDTO,
    SiteHistoryDTO,
    SiteResourcesResultDTO,
    SiteSeedingDTO,
    SiteTestResultDTO,
    SiteUpdateResultDTO,
)
from app.services.indexer_service import IndexerService
from app.sites import SiteConf, SiteCookie
from app.sites.engine import SiteEngine
from app.sites.site_cache import SiteCache
from app.sites.site_favicon_service import SiteFaviconService
from app.sites.site_resolver import SiteResolver
from app.sites.site_userinfo import SiteUserInfo
from app.utils.json_utils import JsonUtils


class SiteService:
    """站点业务服务：站点 CRUD、统计、连通性测试、资源列表"""

    def __init__(
        self,
        sites: SiteCache,
        site_user_info: SiteUserInfo,
        site_conf: SiteConf,
        indexer_service: IndexerService,
        site_repo: SiteRepository,
        site_favicon_service: SiteFaviconService,
        site_resolver: SiteResolver,
        site_cookie: SiteCookie,
        string_utils: Any,
        site_entity_repo: ISiteRepository,
        indexer_site_config_repo: IndexerSiteConfigRepositoryAdapter | None = None,
        site_engine: SiteEngine | None = None,
        idx_config_repo: IndexerConfigRepositoryAdapter | None = None,
    ):
        self._sites = sites
        self._site_user_info = site_user_info
        self._site_conf = site_conf
        self._site_cookie = site_cookie
        self._indexer_service = indexer_service
        self._string_utils = string_utils
        self._site_repo = site_repo
        self._site_entity_repo = site_entity_repo
        self._site_favicon_service = site_favicon_service
        self._site_resolver = site_resolver
        self._indexer_site_config_repo = indexer_site_config_repo or IndexerSiteConfigRepositoryAdapter()
        self._site_engine = site_engine or SiteEngine()
        self._idx_config_repo = idx_config_repo or IndexerConfigRepositoryAdapter()

    def _is_indexer_enabled(self, source: str) -> bool:
        """检查索引器是否启用。builtin 默认启用，第三方读 INDEXER_CONFIG 表。"""
        if source == "builtin":
            entity = self._idx_config_repo.get_by_client_id("builtin")
            return entity.enabled if entity else True
        entity = self._idx_config_repo.get_by_client_id(source)
        return entity.enabled if entity else False

    @property
    def site_user_info(self) -> SiteUserInfo:
        """返回站点用户信息组件。"""
        return self._site_user_info

    # ------------------------------------------------------------------
    # 站点属性
    # ------------------------------------------------------------------
    def check_site_attr(self, url: str | None) -> SiteAttrDTO:
        """检查站点标识（FREE / 2XFREE / HR）"""
        site_attr = self._site_conf.get_grap_conf(url)
        return SiteAttrDTO(
            site_free=bool(site_attr.get("FREE")),
            site_2xfree=bool(site_attr.get("2XFREE")),
            site_hr=bool(site_attr.get("HR")),
        )

    # ------------------------------------------------------------------
    # 站点定义
    # ------------------------------------------------------------------
    def get_site_definitions(self) -> list[SiteDefinitionDTO]:
        """返回所有内置站点定义，供前端选择添加站点。"""
        definitions = []
        for site in self._site_engine.all_sites():
            site_type = ""
            if site.api:
                site_type = "api"
            elif site.html:
                site_type = "html"
            definitions.append(
                SiteDefinitionDTO(
                    id=site.id,
                    name=site.name,
                    domain=site.domain,
                    type=site_type,
                    public=site.public,
                    domain_aliases=site.domain_aliases,
                    encoding=site.encoding,
                    detail_page_url=site.detail_page_url,
                )
            )
        return sorted(definitions, key=lambda x: x.name)

    # ------------------------------------------------------------------
    # CRUD
    # ------------------------------------------------------------------
    def delete_site(self, tid: str | None) -> int | None:
        if not tid:
            return 0
        try:
            site = self._site_entity_repo.get_by_id(int(tid))
            if not site:
                return 0
            self._site_entity_repo.delete(int(tid))
            self._indexer_site_config_repo.upsert_site(site_name=site.name, source="builtin", enabled=False)
            self._sites.refresh()
            return 1
        except Exception:
            return 0

    def get_site(self, tid: str | None) -> SiteDetailDTO:
        if not tid:
            return SiteDetailDTO(site=[])
        site_info = self._sites.get_sites(siteid=tid)
        if not site_info or isinstance(site_info, list):
            return SiteDetailDTO(site=[])
        site_free = site_2xfree = site_hr = False
        signurl = site_info.get("signurl")
        if signurl:
            attr = self._site_conf.get_grap_conf(signurl)
            site_free = bool(attr.get("FREE"))
            site_2xfree = bool(attr.get("2XFREE"))
            site_hr = bool(attr.get("HR"))
        return SiteDetailDTO(site=site_info, site_free=site_free, site_2xfree=site_2xfree, site_hr=site_hr)

    def get_sites(
        self,
        rss: bool = False,
        brush: bool = False,
        statistic: bool = False,
        basic: bool = False,
        source: str | None = None,
    ) -> Any:
        # RSS/刷流/统计场景只返回 builtin 站点
        if rss or brush or statistic:
            return self._sites.get_sites(rss=rss, brush=brush, statistic=statistic, public=True)

        builtin = self._sites.get_sites(public=True)
        engine_by_name = {s.name: s.public for s in self._site_engine.all_sites()}
        config_rows = self._indexer_site_config_repo.list_all()
        config_by_name = {row.site_name.lower(): row for row in config_rows}

        if basic:
            merged = {}
            for s in builtin:
                cfg = config_by_name.get(s["name"].lower())
                enabled = cfg.enabled if cfg else True
                if not enabled:
                    continue
                merged[s["name"]] = {
                    "id": s["id"],
                    "name": s["name"],
                    "source": "builtin",
                    "enabled": True,
                    "site_public": engine_by_name.get(s["name"], s.get("public", False)),
                }
            if source != "builtin":
                for row in config_rows:
                    if row.site_name not in merged and row.source != "builtin":
                        if not self._is_indexer_enabled(row.source):
                            continue
                        merged[row.site_name] = {
                            "id": str(row.id or 0),
                            "name": row.site_name,
                            "source": row.source,
                            "enabled": bool(row.enabled),
                            "third_party": True,
                        }
            return list(merged.values())

        merged = {s["name"]: {**s, "source": "builtin", "third_party": False} for s in builtin}
        for name, site in list(merged.items()):
            cfg = config_by_name.get(name.lower())
            site["enabled"] = cfg.enabled if cfg else True
            if not site["enabled"]:
                del merged[name]
                continue
            site["download_setting"] = cfg.download_setting if cfg else None
            site["default_settings"] = cfg.default_settings if cfg else None
            site["site_public"] = engine_by_name.get(name, site.get("public", False))
        for row in config_rows:
            if row.source == "builtin":
                continue
            if not self._is_indexer_enabled(row.source):
                continue
            if row.site_name not in merged:
                merged[row.site_name] = self._third_party_site_dict(row)
        return list(merged.values())

    @staticmethod
    def _third_party_site_dict(row) -> dict:
        return {
            "id": row.id,
            "name": row.site_name,
            "pri": 0,
            "source": row.source,
            "third_party": True,
            "download_setting": row.download_setting,
            "enabled": bool(row.enabled),
            "default_settings": row.default_settings,
            "public": bool(row.public),
            "rssurl": "",
            "signurl": "",
            "cookie": "",
            "api_key": "",
            "bearer_token": "",
            "api_key_header": None,
            "headers": None,
            "rule": None,
            "rss_enable": False,
            "brush_enable": False,
            "statistic_enable": False,
            "uses": [],
            "ua": "",
            "parse": False,
            "unread_msg_notify": False,
            "chrome": False,
            "proxy": False,
            "subtitle": False,
            "limit_interval": None,
            "limit_count": None,
            "limit_seconds": None,
            "strict_url": "",
            "note": {},
        }

    def _is_site_duplicate(self, name: str | None, tid: str | None) -> bool:
        if not name:
            return False
        sites = self._site_entity_repo.list_by_name(name)
        return any(str(site.id) != str(tid or "") for site in sites)

    def update_site(self, data: dict) -> SiteUpdateResultDTO:
        """新增或更新站点信息（使用领域实体 + ISiteRepository）"""
        tid = data.get("site_id")
        name = data.get("site_name")
        site_pri = data.get("site_pri")
        rssurl = data.get("site_rssurl")
        signurl = data.get("site_signurl")
        cookie = data.get("site_cookie")
        api_key = data.get("site_api_key")
        bearer_token = data.get("site_bearer_token")
        headers = data.get("site_headers")
        note = data.get("site_note")
        if isinstance(note, str):
            try:
                note = JsonUtils.loads(note)
            except Exception:
                note = {}
        note = note or {}

        rss_enable = data.get("rss_enable")
        brush_enable = data.get("brush_enable")
        statistic_enable = data.get("statistic_enable")
        if any(v is not None for v in (rss_enable, brush_enable, statistic_enable)):
            # 基于现有 rss_uses 增量更新，只修改传入的开关，未传入的保持原样
            existing = self._site_entity_repo.get_by_id(int(tid)) if tid else None
            uses = list(existing.rss_uses or "") if existing else []
            has_auth = bool(cookie or headers or api_key or bearer_token)
            if rss_enable is not None:
                uses = [u for u in uses if u != SiteUseType.RSS.value]
                if rss_enable and rssurl:
                    uses.append(SiteUseType.RSS.value)
            if brush_enable is not None:
                uses = [u for u in uses if u != SiteUseType.BRUSH.value]
                if brush_enable and rssurl and has_auth:
                    uses.append(SiteUseType.BRUSH.value)
            if statistic_enable is not None:
                uses = [u for u in uses if u != SiteUseType.STATISTIC.value]
                if statistic_enable and (rssurl or signurl) and has_auth:
                    uses.append(SiteUseType.STATISTIC.value)
            rss_uses = "".join(uses)
        else:
            rss_uses = data.get("site_include")

        # 将 note 中的功能开关统一规范化为布尔值
        switch_keys = ("parse", "message", "chrome", "proxy", "subtitle", "tag", "public")
        for key in switch_keys:
            if key in note:
                value = note[key]
                if isinstance(value, str):
                    note[key] = value.strip().lower() in ("y", "yes", "true", "1")
                else:
                    note[key] = bool(value)

        if self._is_site_duplicate(name, tid):
            return SiteUpdateResultDTO(code=400, msg="站点名称重复")

        entity = SiteEntity(
            id=int(tid) if tid else 0,
            name=name or "",
            pri=int(site_pri) if site_pri else 0,
            rss_url=rssurl,
            sign_url=signurl,
            cookie=cookie,
            api_key=api_key,
            bearer_token=bearer_token,
            headers=headers,
            note=note or {},
            rss_uses=rss_uses,
        )

        if tid:
            existing = self._site_entity_repo.get_by_id(int(tid))
            if not existing:
                return SiteUpdateResultDTO(code=400, msg="站点不存在")
            # 部分更新：请求显式携带的字段用新值，未携带的保留存量（修复"维护编辑只发部分
            # 字段时 cookie/headers/api_key/bearer_token 被覆盖成 NULL 导致配置丢失"）
            explicit_fields: set[str] = set()
            for data_key, attr in (
                ("site_name", "name"),
                ("site_pri", "pri"),
                ("site_rssurl", "rss_url"),
                ("site_signurl", "sign_url"),
                ("site_cookie", "cookie"),
                ("site_api_key", "api_key"),
                ("site_bearer_token", "bearer_token"),
                ("site_headers", "headers"),
                ("site_note", "note"),
            ):
                if data.get(data_key) is not None:
                    explicit_fields.add(attr)
            if data.get("site_include") is not None or any(
                v is not None for v in (rss_enable, brush_enable, statistic_enable)
            ):
                explicit_fields.add("rss_uses")
            entity = self._merge_partial_update(existing, entity, explicit_fields)
            try:
                self._site_entity_repo.update(entity)
                if name and name != existing.name and existing.name:
                    self._site_user_info.update_site_name(name, existing.name)
                self._sites.refresh()
                return SiteUpdateResultDTO(code=0)
            except Exception as e:
                log.error(f"[SiteService]更新站点失败: {e}")
                return SiteUpdateResultDTO(code=500, msg=str(e))
        else:
            if not self._site_engine.get_by_name(name or ""):
                return SiteUpdateResultDTO(code=400, msg="站点不存在于站点定义中，无法添加")
            try:
                self._site_entity_repo.insert(entity)
                self._sites.refresh()
                return SiteUpdateResultDTO(code=0)
            except Exception as e:
                log.error(f"[SiteService]新增站点失败: {e}")
                return SiteUpdateResultDTO(code=500, msg=str(e))

    @staticmethod
    def _merge_partial_update(existing, entity: SiteEntity, explicit_fields: set[str]) -> SiteEntity:
        """部分更新合并：显式携带的字段用实体新值，其余保留存量.

        修复：站点维护页只编辑部分字段时，未发送的 cookie/headers/api_key/
        bearer_token/rssurl/signurl/name 等不能被覆盖为空。
        """
        attrs = {
            "name",
            "pri",
            "rss_url",
            "sign_url",
            "cookie",
            "api_key",
            "bearer_token",
            "headers",
            "note",
            "rss_uses",
        }
        for attr in attrs - explicit_fields:
            setattr(entity, attr, getattr(existing, attr, None))
        return entity

    def update_site_cookie_ua(self, siteid: int | str, cookie: str, ua: str) -> None:
        self._site_entity_repo.update_cookie_ua(int(siteid), cookie, ua)
        self._sites.refresh()

    # ------------------------------------------------------------------
    # 统计
    # ------------------------------------------------------------------
    def get_site_activity(self, name: str) -> SiteActivityDTO:
        dataset = self._site_user_info.get_pt_site_activity_history(name)
        return SiteActivityDTO(dataset=dataset)

    def get_site_history(self, days: int, end_day: str | None = None) -> SiteHistoryDTO:
        _, _, site, upload, download = self._site_user_info.get_pt_site_statistics_history(days + 1, end_day)
        dataset = [["site", "upload", "download"]]
        dataset.extend([[s, u, d] for s, u, d in zip(site, upload, download, strict=False)])
        return SiteHistoryDTO(dataset=dataset)

    def get_site_seeding_info(self, name: str) -> SiteSeedingDTO:
        seeding_info = self._site_user_info.get_pt_site_seeding_info(name).get("seeding_info", [])
        dataset = [["seeders", "size"]]
        dataset.extend(seeding_info)
        return SiteSeedingDTO(dataset=dataset)

    def get_site_daily_history(self, days: int = 30, end_day: str | None = None) -> dict:
        site_urls = []
        for site in self._sites.get_sites(statistic=True):
            site_url = site.get("strict_url")
            if site_url:
                site_urls.append(site_url)
        return self._site_repo.get_site_daily_history(days=days, end_day=end_day, strict_urls=site_urls)

    def refresh_site_data_now(self, specify_sites: list | None = None) -> None:
        """强制刷新站点数据"""
        self._site_user_info.refresh_site_data_now(specify_sites=specify_sites)

    def get_site_user_statistics(
        self,
        sites: list | None = None,
        encoding: str = "DICT",
        sort_by: str | None = None,
        sort_on: str | None = None,
        site_hash: str | None = None,
    ) -> list[Any]:
        statistics = self._site_user_info.get_site_user_statistics(sites=sites, encoding="DICT")
        # 修复馒头站点显示
        for item in statistics:
            item_dict = cast(dict[str, Any], item)
            if "m-team" in item_dict.get("url", ""):
                site_info: Any = self._sites.get_sites(siteurl=item_dict.get("url")) or {}
                item_dict["url"] = site_info.get("signurl") if isinstance(site_info, dict) else None
        # 排序：sort_by 存在时默认降序，sort_on 显式指定时按指定方向
        if sort_by:
            reverse = sort_on != "asc"
            statistics.sort(key=lambda x: cast(dict[str, Any], x).get(sort_by) or 0, reverse=reverse)
        if site_hash == "Y":
            for item in statistics:
                item_dict = cast(dict[str, Any], item)
                item_dict["site_hash"] = self._string_utils.md5_hash(item_dict.get("site_name"))
        return statistics

    # ------------------------------------------------------------------
    # Favicon
    # ------------------------------------------------------------------
    def get_site_favicon(self, name: str | None = None) -> Any:
        return self._site_favicon_service.get_favicon(site_name=name)

    # ------------------------------------------------------------------
    # 连通性测试
    # ------------------------------------------------------------------
    def test_site(self, site_id: int | str) -> SiteTestResultDTO:
        flag, msg, times = self._site_resolver.test_connection(site_id)
        return SiteTestResultDTO(flag=flag, msg=msg, times=times, code=0 if flag else -1)

    def test_sites_batch(self, site_ids: list[str] | None) -> list[dict[str, Any]]:
        """批量测试站点连通性。

        并发执行，返回每个站点的 {id, flag, msg, times}。不抛异常，单点失败不影响其他站点。
        """
        ids = [str(s) for s in (site_ids or []) if str(s).strip()]
        if not ids:
            return []

        def _run(sid: str) -> dict[str, Any]:
            try:
                flag, msg, times = self._site_resolver.test_connection(sid)
            except (ServiceError, DomainError, RepositoryError) as e:
                flag, msg, times = False, str(e), 0.0
            except Exception as e:  # noqa: BLE001
                flag, msg, times = False, f"测试异常: {e}", 0.0
            return {"id": sid, "flag": flag, "msg": msg, "times": times}

        results: list[dict[str, Any]] = []
        max_workers = min(5, len(ids))
        with ThreadPoolExecutor(max_workers=max_workers) as executor:
            futures = {executor.submit(_run, sid): sid for sid in ids}
            for future in as_completed(futures):
                results.append(future.result())
        return results

    # ------------------------------------------------------------------
    # 验证码
    # ------------------------------------------------------------------
    def set_captcha_code(self, code: str, value: str) -> None:
        self._site_cookie.set_code(code=code, value=value)

    # ------------------------------------------------------------------
    # 资源列表
    # ------------------------------------------------------------------
    def list_site_resources(self, index_id: str, page: int, keyword: str) -> SiteResourcesResultDTO:
        result = self._indexer_service.list_resources(index_id=index_id, page=page, keyword=keyword)
        data = result.data
        if result.success and isinstance(data, list):
            for item in data:
                self._attach_media_ident(item)
        return SiteResourcesResultDTO(success=result.success, data=data, msg=result.msg)

    @staticmethod
    def _attach_media_ident(item: Any) -> None:
        """为资源列表项附加解析级识别信息（标题离线解析，不走 TMDB）"""
        if not isinstance(item, dict):
            return
        title = item.get("title") or ""
        if not title:
            return
        try:
            mi = meta_info(title=title, subtitle=item.get("description") or "")
        except Exception:  # noqa: BLE001
            return
        item["media"] = {
            "name": mi.get_name() or "",
            "cn_name": mi.cn_name or "",
            "en_name": mi.en_name or "",
            "season_episode": mi.get_season_episode_string(),
            "year": mi.year or "",
            "type": mi.type.value if mi.type else "",
            "resource_type": mi.get_resource_type_string(),
        }

    def get_site_download_setting(self, site_name: str | None = None) -> Any:
        """获取站点下载设置（代理到 Sites）"""
        return self._sites.get_site_download_setting(site_name=site_name)
