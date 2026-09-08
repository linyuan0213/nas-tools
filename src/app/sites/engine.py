"""
站点引擎 — 统一站点定义加载与功能入口

消除散落在 20+ 个文件中的 'if m-team in url' 逻辑，
通过声明式 JSON 站点定义提供统一的搜索、下载、字幕等功能入口。
"""

import importlib
import os
import random
import re
import threading
import time
import traceback
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any
from urllib.parse import urlencode, urlparse

import dateutil.parser
from lxml import etree

import log
from app.core.root_path import get_project_root
from app.infrastructure.chrome.challenge import is_challenge
from app.infrastructure.http.auth import CookieAuth
from app.infrastructure.http.client import HttpClient
from app.infrastructure.http.config import HttpClientConfig
from app.sites import engine_connection, engine_download, engine_tools, engine_user_info
from app.sites.utils import is_logged_in
from app.utils import JsonUtils
from app.utils.browser_mode import build_browser_mode
from app.utils.config_tools import get_proxies

# 详情页/页面抓取限流退避：站点连续返回空/失败时，串行化并放缓后续请求，
# 避免瞬时并发触发站点风控；恢复正常后自动回到无间隔并发。
_PAGE_PACE_WINDOW = 180.0
_PAGE_PACE_MAX_INTERVAL = 6.0
_page_pace_state: dict[str, dict] = {}
_page_pace_lock = threading.Lock()


def _record_page_fetch_result(site_id: str, ok: bool) -> None:
    """记录一次页面抓取结果，ok=False 表示空/失败，进入退避窗口"""
    with _page_pace_lock:
        st = _page_pace_state.setdefault(site_id, {"last_fail": 0.0, "streak": 0})
        if ok:
            st["last_fail"] = 0.0
            st["streak"] = 0
            st["slot"] = 0.0
        else:
            st["last_fail"] = time.monotonic()
            st["streak"] = int(st.get("streak", 0)) + 1


def _claim_page_fetch_slot(site_id: str, interval: float) -> float:
    """为一次抓取预约时间片，返回需等待秒数（>0 则调用方 sleep）"""
    with _page_pace_lock:
        now = time.monotonic()
        slot = _page_pace_state.get(site_id, {}).get("slot", 0.0) or 0.0
        start = max(now, slot)
        _page_pace_state.setdefault(site_id, {})["slot"] = start + interval
        return start - now


def _page_fetch_interval(site_id: str) -> float:
    """当前站点是否处于退避窗口；是则返回建议间隔"""
    with _page_pace_lock:
        st = _page_pace_state.get(site_id)
        if not st:
            return 0.0
        now = time.monotonic()
        if now - float(st.get("last_fail", 0.0)) > _PAGE_PACE_WINDOW:
            st["streak"] = 0
            return 0.0
        streak = int(st.get("streak", 0))
        if streak <= 0:
            return 0.0
        base = min(0.8 + (streak - 1) * 1.2, _PAGE_PACE_MAX_INTERVAL)
        return random.uniform(base * 0.7, base * 1.3)


class TorrentAttrFetchError(Exception):
    """种子详情属性抓取失败（网络错误/限流/页面为空等）。

    调用方应把属性视为“未知”，不得当作“非免费/非HR”处理，
    以免在抓取失败时误判（如把仍免费的种子判定为免费到期而删种）。
    """


# ---- 数据模型 ----


@dataclass
class DownloadConfig:
    """下载链接配置"""

    type: str = "api"
    method: str = "GET"
    path: str = ""
    body: dict[str, str] | None = None
    response_key: str = "data"
    params: dict[str, str] | None = None
    download_url: str | None = None
    selectors: dict | None = None
    presigned: bool = False


@dataclass
class SubtitleConfig:
    """字幕下载配置"""

    type: str = "api"
    list_endpoint: dict | None = None
    genlink_endpoint: dict | None = None
    download_endpoint: dict | None = None


@dataclass
class SiteApiConfig:
    """站点 API 配置"""

    base_url: str = ""
    auth: dict = field(default_factory=dict)
    endpoints: dict = field(default_factory=dict)


@dataclass
class SiteHtmlConfig:
    """HTML 站点配置"""

    search: dict = field(default_factory=dict)
    torrents: dict = field(default_factory=dict)
    category: dict = field(default_factory=dict)
    conf: dict = field(default_factory=dict)
    browse: dict | None = None
    parser_type: str = "flat"
    test_connection: str | None = None


@dataclass
class SiteDefinition:
    """站点完整定义"""

    id: str = ""
    name: str = ""
    domain: str = ""
    domain_aliases: list[str] = field(default_factory=list)
    # RSS 专用域名（仅用于识别 RSS 种子归属，功能访问仍走主站 domain）
    rss_domains: list[str] = field(default_factory=list)
    tid_pattern: str = r"\d+"
    encoding: str = "UTF-8"
    public: bool = False
    favicon: str = ""
    language: str | None = None
    api: SiteApiConfig | None = None
    html: SiteHtmlConfig | None = None
    download: DownloadConfig | None = None
    torrent_attr: dict | None = None
    subtitle: SubtitleConfig | None = None
    detail_page_url: str = ""
    user_info: dict | None = None

    def match_url(self, url: str) -> bool:
        if not url or not self.domain:
            return False
        url_lower = url.lower()
        domain_lower = self.domain.lower()
        if domain_lower in url_lower or url_lower in domain_lower:
            return True
        url_stripped = url_lower.replace("www.", "")
        domain_stripped = domain_lower.replace("www.", "")
        if domain_stripped in url_stripped or url_stripped in domain_stripped:
            return True
        if any(alias.lower() in url_lower or url_lower in alias.lower() for alias in self.domain_aliases):
            return True
        return any(rss.lower() in url_lower or url_lower in rss.lower() for rss in self.rss_domains)

    @classmethod
    def from_dict(cls, data: dict) -> "SiteDefinition":
        d = cls()
        d.id = data.get("id", "")
        d.name = data.get("name", data.get("id", ""))
        d.domain = data.get("domain", "")
        d.domain_aliases = data.get("domain_aliases", [])
        d.rss_domains = data.get("rss_domains", [])
        d.tid_pattern = data.get("tid_pattern", r"\d+")
        d.encoding = data.get("encoding", "UTF-8")
        d.public = data.get("public", False)
        d.favicon = data.get("favicon", "")
        d.language = data.get("language")
        d.detail_page_url = data.get("detail_page_url", "")
        if data.get("api"):
            api = data["api"]
            endpoints = api.get("endpoints", {})
            d.api = SiteApiConfig(base_url=api.get("base_url", ""), auth=api.get("auth", {}), endpoints=endpoints)
        if data.get("html"):
            html = data["html"]
            d.html = SiteHtmlConfig(
                search=html.get("search", {}),
                torrents=html.get("torrents", {}),
                category=html.get("category", {}),
                conf=html.get("conf", {}),
                browse=html.get("browse"),
                parser_type=html.get("parser_type", "flat"),
                test_connection=html.get("test_connection"),
            )
        if data.get("download"):
            dl = data["download"]
            d.download = DownloadConfig(
                type=dl.get("type", "api"),
                method=dl.get("method", "GET"),
                path=dl.get("path", ""),
                body=dl.get("body"),
                response_key=dl.get("response_key", "data"),
                params=dl.get("params"),
                download_url=dl.get("download_url"),
                selectors=dl.get("selectors"),
                presigned=dl.get("presigned", False),
            )
        if data.get("torrent_attr"):
            d.torrent_attr = data["torrent_attr"]
        if data.get("subtitle"):
            sub = data["subtitle"]
            d.subtitle = SubtitleConfig(
                type=sub.get("type", "api"),
                list_endpoint=sub.get("list"),
                genlink_endpoint=sub.get("genlink"),
                download_endpoint=sub.get("download"),
            )
        if data.get("user_info"):
            d.user_info = data["user_info"]
        return d


# ---- 站点引擎 ----


def _extract_detail_labels(doc, site) -> str:
    labels: list[str] = []
    if site.html and site.html.torrents:
        if isinstance(site.html.torrents, dict):
            fields = site.html.torrents.get("fields")
        else:
            fields = getattr(site.html.torrents, "fields", None)
        if isinstance(fields, dict):
            labels_selector = fields.get("labels", {}).get("selector")
            if labels_selector:
                for el in doc.cssselect(labels_selector):
                    txt = "".join(str(t) for t in el.itertext()).strip()
                    if txt:
                        labels.append(txt)
        elif fields is not None:
            labels_field = getattr(fields, "labels", None)
            if labels_field and getattr(labels_field, "selector", None):
                for el in doc.cssselect(labels_field.selector):
                    txt = "".join(str(t) for t in el.itertext()).strip()
                    if txt:
                        labels.append(txt)
    if not labels:
        tag_patterns = [
            "span[class*='tag']",
            "a[class*='tag']",
            "div[class*='tag']",
            "span[class*='label']",
            "a[class*='label']",
        ]
        for pattern in tag_patterns:
            for el in doc.cssselect(pattern):
                txt = "".join(str(t) for t in el.itertext()).strip()
                if txt and txt not in labels:
                    labels.append(txt)
            if labels:
                break
    return "|".join(labels)


class SiteEngine:
    """站点引擎单例"""

    _BUILTIN_DEFINITIONS_DIR = os.path.join(get_project_root(), "config", "sites")

    @classmethod
    def _resolve_definitions_dir(cls) -> str:
        """优先使用环境变量 NEXUS_SITES_DIR，不存在则回退到内置目录"""
        env_dir = os.environ.get("NEXUS_SITES_DIR")
        if env_dir and os.path.isdir(env_dir):
            return env_dir
        return cls._BUILTIN_DEFINITIONS_DIR

    def __init__(self, definitions_dir: str | None = None):
        self._sites: dict[str, SiteDefinition] = {}
        self._domain_index: dict[str, SiteDefinition] = {}
        self._auth_cache: dict[str, str] = {}
        self._user_info_factories = []
        self.site_limiter: Any = None
        self._definitions_dir = definitions_dir or self._resolve_definitions_dir()
        if self._definitions_dir and os.path.isdir(self._definitions_dir):
            for subdir in ("api", "html"):
                subpath = os.path.join(self._definitions_dir, subdir)
                if os.path.isdir(subpath):
                    self._load(subpath)

    def _register_user_info_factories(self) -> None:
        """注册默认的用户信息解析工厂（动态导入避免循环依赖）"""
        importlib.import_module("app.sites.siteuserinfo.config_api")
        importlib.import_module("app.sites.siteuserinfo.config_html")

    def _load(self, directory: str):
        for fname in sorted(os.listdir(directory)):
            if not fname.endswith(".json"):
                continue
            fpath = os.path.join(directory, fname)
            try:
                with open(fpath, encoding="utf-8") as f:
                    data = JsonUtils.load(f)
                site_def = SiteDefinition.from_dict(data)
                self._sites[site_def.id] = site_def
                self._index_site(site_def)
                log.debug(f"[SiteEngine]加载站点定义: {site_def.name} ({site_def.id})")
            except Exception:
                log.warn(f"[SiteEngine]加载站点定义失败: {fname}\n{traceback.format_exc()}")

    def _index_site(self, site_def: SiteDefinition) -> None:
        """将站点定义加入 domain 索引."""
        if site_def.domain:
            self._domain_index[site_def.domain.lower()] = site_def
            for alias in site_def.domain_aliases:
                self._domain_index[alias.lower()] = site_def
            for rss in site_def.rss_domains:
                self._domain_index[rss.lower()] = site_def

    def register_rss_domain(self, site_key: str, rss_domain: str) -> None:
        """注册用户配置的 RSS 域名到站点匹配索引（RSS 种子识别用）.

        用户站点配置的 RSS 链接域名与主站不一致时，RSS 种子 URL 据此识别站点归属；
        功能访问（搜索/详情/属性解析）仍走站点定义的主站 domain。
        """
        if not rss_domain:
            return
        site = self.get_by_name(site_key) or self._sites.get(site_key)
        if not site:
            return
        self._domain_index[rss_domain.lower()] = site
        if rss_domain not in site.rss_domains:
            site.rss_domains.append(rss_domain)

    def register(self, site_def: SiteDefinition):
        self._sites[site_def.id] = site_def
        self._index_site(site_def)

    def get_by_id(self, site_id: str) -> SiteDefinition | None:
        if not site_id:
            return None
        site = self._sites.get(site_id)
        if site:
            return site
        # 兼容存量数据中的大小写差异（站点 id 已统一为小写）
        lowered = site_id.lower()
        return self._sites.get(lowered) if lowered != site_id else None

    def get_by_url(self, url: str) -> SiteDefinition | None:
        if not url:
            return None
        parsed = urlparse(url.lower())
        if parsed.netloc:
            site = self._domain_index.get(parsed.netloc)
            if site:
                return site
        for site in self._sites.values():
            if site.match_url(url):
                return site
        return None

    def get_by_domain(self, domain: str) -> SiteDefinition | None:
        return self._domain_index.get(domain.lower()) if domain else None

    def get_by_name(self, name: str) -> SiteDefinition | None:
        if not name:
            return None
        name_lower = name.lower()
        for site in self._sites.values():
            if site.name.lower() == name_lower or site.id.lower() == name_lower:
                return site
        return None

    def all_sites(self) -> list[SiteDefinition]:
        return list(self._sites.values())

    def normalize_domain(self, url: str) -> str:
        site = self.get_by_url(url)
        return site.domain if site else self._base_from_url(url)

    def is_tid_based_dedup(self, url: str) -> bool:
        site = self.get_by_url(url)
        return site.tid_pattern != "" if site else False

    # ---- 详情页 ----

    def resolve_detail_url(self, url: str, tid: str) -> str:
        site = self.get_by_url(url)
        if site and site.detail_page_url:
            return site.detail_page_url.format(tid=tid)
        return f"{self._base_from_url(url)}/detail/{tid}"

    # ---- 下载链接 ----

    def resolve_download_url(self, page_url: str, user_config: dict | None = None) -> str | None:
        site = self.get_by_url(page_url)
        if not site:
            return None
        user_config = user_config or {}
        if site.download:
            if site.download.type == "html":
                return engine_download.resolve_html_download(self, page_url, site, user_config)
            tid = self._extract_tid(page_url, site)
            if not tid:
                return None
            base = site.api.base_url.rstrip("/") if site.api else self._base_from_url(page_url)
            path = site.download.path.format(tid=tid)
            url = f"{base}{path}" if path.startswith("/") else path
            if site.download.type == "api":
                return engine_download.resolve_download_api(self, url, site, user_config, tid)
            elif site.download.type == "api_chained":
                return engine_download.resolve_download_chained(self, url, site, user_config, tid)
            elif site.download.type == "template":
                return site.download.path.format(tid=tid)
            return url
        if site.html:
            return engine_download.resolve_html_download(self, page_url, site, user_config)
        return None

    # ---- 种子属性检查 ----

    @staticmethod
    def _match_attr_value(extracted, expected, match_type: str = "exact") -> bool:
        """按匹配方式判断 API 返回值与期望值是否匹配（exact / contains）."""
        if match_type == "contains":
            return bool(expected and expected in str(extracted or ""))
        if isinstance(extracted, (int, float)):
            try:
                return extracted == float(expected)
            except (TypeError, ValueError):
                return str(extracted) == expected
        return str(extracted) == expected

    @staticmethod
    def _attr_rule_active(text: str, resp_cfg: dict, prefix: str) -> bool:
        """校验站点级活动规则时间窗是否覆盖当前时刻（可选配置）.

        站点级活动（如“全站免费”）可能在种子徽标未更新的情况下生效，
        是否生效以规则自身的 startTime/endTime 为准：
        - 未配置 *_start_key / *_end_key 时不校验时间窗；
        - 配置了但字段缺失或不可解析时视为活动未生效，
          避免活动结束后遗留规则导致长期误判免费。
        """
        start_key = resp_cfg.get(f"{prefix}_start_key", "")
        end_key = resp_cfg.get(f"{prefix}_end_key", "")
        if not start_key and not end_key:
            return True
        try:
            now = datetime.now(timezone.utc)
            if start_key:
                start_val = JsonUtils.get_json_object(text, start_key)
                if not start_val:
                    return False
                if SiteEngine._parse_rule_time(start_val) > now:
                    return False
            if end_key:
                end_val = JsonUtils.get_json_object(text, end_key)
                if not end_val:
                    return False
                if SiteEngine._parse_rule_time(end_val) <= now:
                    return False
        except Exception:
            return False
        return True

    @staticmethod
    def _parse_rule_time(value: Any) -> datetime:
        """解析站点活动时间字段，兼容 ISO 字符串与 epoch 秒/毫秒（数字或数字字符串）.

        返回 aware UTC 时间；无法解析时抛错由调用方按活动未生效处理。
        """
        try:
            numeric = float(str(value).strip())
            ts = numeric / 1000.0 if numeric > 1e12 else numeric
            return datetime.fromtimestamp(ts, tz=timezone.utc)
        except (TypeError, ValueError):
            parsed = dateutil.parser.parse(str(value))
            if parsed.tzinfo is None:
                # naive 视为服务器本地时间
                parsed = parsed.replace(tzinfo=datetime.now().astimezone().tzinfo)
            return parsed.astimezone(timezone.utc)

    def _eval_html_conf(self, html_txt, conf) -> dict | None:
        """统一评估站点定义 html.conf 的属性选择器（JSON path=value 或 XPath）。

        返回 {"free","2xfree","hr","peer_count","hits":{KEY:n},"doc":etree|None}；
        HTML 无法解析时返回 None。free/2xfree/hr/peer_count 的唯一求值入口，
        resolve_torrent_attr 与 html_selector_stats 共享，不再各自硬编码键组。
        """
        is_json = JsonUtils.is_valid_json(html_txt)
        doc = None
        if not is_json:
            doc = etree.HTML(html_txt)
            if doc is None:
                return None

        def _json_val(path):
            return JsonUtils.get_json_object(html_txt, path)

        def _match_eq(xp):  # path=value 精确匹配（FREE / 2XFREE）
            if is_json:
                path, _, value = xp.partition("=")
                return str(_json_val(path)) == value
            return bool(doc.xpath(xp))  # type: ignore[union-attr]

        def _match_truthy(xp):  # 存在且非空（HR）
            if is_json:
                return bool(_json_val(xp))
            return bool(doc.xpath(xp))  # type: ignore[union-attr]

        def _match_exist(xp):  # 存在即命中（PEER_COUNT 命中统计）
            if is_json:
                return _json_val(xp) is not None
            return bool(doc.xpath(xp))  # type: ignore[union-attr]

        free_hits = sum(1 for xp in (conf.get("FREE") or []) if _match_eq(xp))
        x2_hits = sum(1 for xp in (conf.get("2XFREE") or []) if _match_eq(xp))
        hr_hits = sum(1 for xp in (conf.get("HR") or []) if _match_truthy(xp))
        peer_hits = sum(1 for xp in (conf.get("PEER_COUNT") or []) if _match_exist(xp))

        peer_count = 0
        for xp in conf.get("PEER_COUNT") or []:
            if is_json:
                val = _json_val(xp)
                if val:
                    peer_count = int(val)
                    break
            else:
                els = doc.xpath(xp)  # type: ignore[union-attr]
                if els:
                    txt = "".join(str(t) for t in els[0].itertext())  # type: ignore[union-attr]
                    peer_count = int("".join(c for c in txt if c.isdigit()) or 0)
                    break

        # 详情页发布时间（PUBDATE）：刷流时间规则以此为准（若配置了 PUBDATE 选择器）
        pubdate = None
        for xp in conf.get("PUBDATE") or []:
            if is_json:
                val = _json_val(xp)
                if val:
                    pubdate = str(val).strip()
                    break
            else:
                nodes: list = doc.xpath(xp)  # type: ignore[union-attr]
                if not nodes:
                    continue
                first = nodes[0]
                if isinstance(first, str):
                    text = first.strip()
                else:
                    text = "".join(str(t) for t in first.itertext()).strip()  # type: ignore[union-attr]
                if text:
                    pubdate = text
                    break

        return {
            "free": free_hits > 0 or x2_hits > 0,
            "2xfree": x2_hits > 0,
            "hr": hr_hits > 0,
            "peer_count": peer_count,
            "pubdate": pubdate,
            "hits": {"FREE": free_hits, "2XFREE": x2_hits, "HR": hr_hits, "PEER_COUNT": peer_hits},
            "doc": doc,
        }

    def resolve_torrent_attr(
        self,
        torrent_url,
        cookie=None,
        api_key=None,
        bearer_token=None,
        ua=None,
        headers=None,
        proxy=False,
        chrome=False,
        browser_persistent=False,
        detail=None,
    ):
        ret = {"free": False, "2xfree": False, "hr": False, "peer_count": 0, "labels": ""}
        site = self.get_by_url(torrent_url)
        if not site:
            # 站点未匹配：属性未知而非"非免费"，避免上层按非免费误删
            log.warn(f"[SiteEngine]resolve_torrent_attr 未匹配站点, url={torrent_url[:100]}")
            raise TorrentAttrFetchError(f"未匹配站点: {torrent_url[:100]}")
        user_config = {
            "cookie": cookie or "",
            "api_key": api_key or "",
            "bearer_token": bearer_token or "",
            "ua": ua or "",
            "proxy": proxy,
            "headers": headers or {},
            "chrome": chrome,
            "browser_persistent": bool(browser_persistent),
        }

        if site.api and site.torrent_attr:
            tid = self._extract_tid(torrent_url, site)
            if not tid:
                # TID 提取失败（如 RSS 一次性签名链接）：属性未知，不得按"非免费"处理
                log.warn(f"[SiteEngine]resolve_torrent_attr TID提取失败, url={torrent_url[:100]}")
                raise TorrentAttrFetchError(f"TID提取失败: {torrent_url[:100]}")
            cfg = site.torrent_attr
            base = site.api.base_url.rstrip("/")
            path = cfg.get("path", "").format(tid=tid)
            url = f"{base}{path}" if path.startswith("/") else path
            body = {k: v.format(tid=tid) for k, v in (cfg.get("body") or {}).items()}
            method = (cfg.get("method") or "POST").upper()
            if method == "GET":
                # GET 接口的查询参数（如 /api/torrent/info?id={tid}）
                query = {k: v.format(tid=tid) for k, v in (cfg.get("params") or {}).items()}
                if query:
                    url = f"{url}?{urlencode(query)}"
            headers, auth = engine_tools._build_auth(self, site, user_config)
            body_format = cfg.get("body_format", "form")
            if body_format == "json":
                if method == "POST":
                    headers["Content-Type"] = headers.get("Content-Type", "application/json")
            else:
                headers.pop("Content-Type", None)
            proxies = get_proxies() if proxy else None
            proxy_url = proxies.get("http") if proxies else None
            try:
                rate_limiter = getattr(self, "site_limiter", None)
                rate_limiter_engine = rate_limiter.engine if rate_limiter else None
                rl_kwargs = engine_tools._get_rate_limit_kwargs(self, site)
                client = HttpClient(
                    config=HttpClientConfig(proxy_url=proxy_url),
                    rate_limiter=rate_limiter_engine,
                )
                if method == "POST":
                    if body_format == "json":
                        res = client.post(
                            url=url,
                            json=body if body else None,
                            headers=headers,
                            auth=auth,
                            **rl_kwargs,
                        )
                    else:
                        res = client.post(
                            url=url,
                            data=body if body else None,
                            headers=headers,
                            auth=auth,
                            **rl_kwargs,
                        )
                else:
                    res = client.get(url=url, headers=headers, auth=auth, **rl_kwargs)
                text = res.text
                # 非 JSON 响应（302 错误页/限流 HTML 等）：属性未知，不得按"非免费"处理
                if not JsonUtils.is_valid_json(text):
                    raise TorrentAttrFetchError(f"详情返回非 JSON（疑似错误页/限流）: {url[:100]}")
                resp_cfg = cfg.get("response", {})
                # 业务失败响应（如 {"code":1,"message":"非法用戶端"} 无 data）：
                # free_key 顶层字段（约定为 data）缺失或为空时视为属性未知，不误判"非免费"
                free_path = resp_cfg.get("free_key", "")
                top_key = free_path.split(".")[0] if free_path else ""
                if top_key:
                    root = JsonUtils.loads(text)
                    if isinstance(root, dict) and (top_key not in root or root.get(top_key) is None):
                        raise TorrentAttrFetchError(f"详情接口无 {top_key} 数据（疑似业务失败）: {str(root)[:120]}")
                free_val = resp_cfg.get("free_value", "")
                free_match = resp_cfg.get("free_match", "exact")
                # free_value 可能为 0（如朱雀 downloadRate==0 表示免费），不能用真值判断
                if free_path and free_val is not None and free_val != "":
                    extracted = JsonUtils.get_json_object(text, free_path)
                    if self._match_attr_value(extracted, free_val, free_match):
                        ret["free"] = True
                free2x_path = cfg.get("response", {}).get("2xfree_key", "")
                free2x_val = cfg.get("response", {}).get("2xfree_value", "")
                free2x_match = cfg.get("response", {}).get("2xfree_match", "exact")
                if free2x_path and free2x_val is not None and free2x_val != "":
                    extracted2x = JsonUtils.get_json_object(text, free2x_path)
                    if self._match_attr_value(extracted2x, free2x_val, free2x_match):
                        ret["free"] = True
                        ret["2xfree"] = True
                # 站点级活动（如“全站免费”）：
                # 部分站点活动期间不逐种更新徽标（如 M-Team 全站 FREE 时多数种子仍显示
                # 上传者自设的折扣），此时以详情返回的全站活动规则补判免费。
                if not ret["free"]:
                    site_free_path = resp_cfg.get("site_free_key", "")
                    site_free_val = resp_cfg.get("site_free_value", "")
                    site_free_match = resp_cfg.get("site_free_match", "exact")
                    if (
                        site_free_path
                        and site_free_val
                        and self._attr_rule_active(text, resp_cfg, "site_free")
                        and self._match_attr_value(
                            JsonUtils.get_json_object(text, site_free_path), site_free_val, site_free_match
                        )
                    ):
                        ret["free"] = True
                if not ret["2xfree"]:
                    site_2x_path = resp_cfg.get("site_2xfree_key", "")
                    site_2x_val = resp_cfg.get("site_2xfree_value", "")
                    site_2x_match = resp_cfg.get("site_2xfree_match", "exact")
                    if (
                        site_2x_path
                        and site_2x_val
                        and self._attr_rule_active(text, resp_cfg, "site_2xfree")
                        and self._match_attr_value(
                            JsonUtils.get_json_object(text, site_2x_path), site_2x_val, site_2x_match
                        )
                    ):
                        ret["free"] = True
                        ret["2xfree"] = True
                peer_path = cfg.get("response", {}).get("peer_count_key", "")
                if peer_path:
                    val = JsonUtils.get_json_object(text, peer_path)
                    peer_type = cfg.get("response", {}).get("peer_count_type", "int")
                    if peer_type == "str":
                        ret["peer_count"] = str(val) if val else ""
                    else:
                        ret["peer_count"] = int(val) if val else 0
                labels_path = cfg.get("response", {}).get("labels_key", "")
                if labels_path:
                    labels_val = JsonUtils.get_json_object(text, labels_path)
                    if isinstance(labels_val, (list, tuple)):
                        ret["labels"] = ",".join(str(x) for x in labels_val if x)
                    elif labels_val:
                        ret["labels"] = str(labels_val)
                # 自检用：输出各配置字段在响应中是否存在（识别字段漂移）
                if isinstance(detail, dict):
                    resp = cfg.get("response", {}) or {}
                    key_map = {
                        "free": resp.get("free_key"),
                        "2xfree": resp.get("2xfree_key"),
                        "peer_count": resp.get("peer_count_key"),
                        "labels": resp.get("labels_key"),
                    }
                    keys = {}
                    for label, path in key_map.items():
                        if path:
                            keys[label] = JsonUtils.get_json_object(text, path) is not None
                    detail["api_keys"] = keys
            except TorrentAttrFetchError:
                raise
            except Exception as e:  # noqa: BLE001
                # 抓取异常：属性视为“未知”，交由上层决定（避免误判为“非免费”）
                log.debug(f"[SiteEngine]种子属性抓取异常: {e}")
                raise TorrentAttrFetchError(f"种子详情抓取失败: {e}") from e
            return ret

        if site.html and site.html.conf:
            conf = site.html.conf
            if site.detail_page_url:
                detail_url = site.detail_page_url.format(tid=self._extract_tid(torrent_url, site) or "")
                if not detail_url.startswith("http"):
                    detail_url = f"{self._base_from_url(torrent_url).rstrip('/')}/{detail_url.lstrip('/')}"
            else:
                detail_url = torrent_url
            html_txt = self._fetch_page(detail_url, user_config)
            if not html_txt:
                raise TorrentAttrFetchError(f"种子详情页抓取为空, url={detail_url[:120]}")
            attrs = self._eval_html_conf(html_txt, conf)
            if attrs is None:
                raise TorrentAttrFetchError(f"种子详情页解析失败, url={detail_url[:120]}")
            ret["free"] = attrs["free"]
            ret["2xfree"] = attrs["2xfree"]
            ret["hr"] = attrs["hr"]
            ret["peer_count"] = attrs["peer_count"]
            if attrs.get("pubdate"):
                ret["pubdate"] = attrs["pubdate"]
            if attrs["doc"] is not None:
                ret["labels"] = _extract_detail_labels(attrs["doc"], site)
        return ret

    def html_selector_stats(self, torrent_url: str, user_config: dict) -> dict:
        """
        单次抓取 HTML 站点种子详情页，统一返回：
        - 各配置选择器命中数（selector 静默失效监控）
        - 属性值 free/2xfree/hr/peer_value（替代单独的属性解析，避免二次抓取触发反爬）
        - 登录态 auth（凭据失效/访问受限，不属结构变更）
        """
        site = self.get_by_url(torrent_url)
        if not site or not site.html or not site.html.conf:
            return {"fetched": False}
        conf = site.html.conf
        html_txt, final_url = self._fetch_page_ex(torrent_url, user_config)
        is_login_redirect = "login" in final_url.lower()
        if not html_txt:
            if is_login_redirect:
                return {"fetched": False, "auth": True}
            return {"fetched": False, "error": "empty"}
        if is_login_redirect or not is_logged_in(html_txt):
            return {"fetched": True, "auth": True}
        attrs = self._eval_html_conf(html_txt, conf)
        if attrs is None:
            return {"fetched": False, "error": "parse"}
        return {
            "fetched": True,
            "selectors": attrs["hits"],
            "peer_value": attrs["peer_count"],
            "free": attrs["free"],
            "hr": attrs["hr"],
            "pubdate": attrs.get("pubdate"),
        }

    def _fetch_page(self, url, user_config):
        """抓取页面文本（兼容签名）."""
        text, _ = self._fetch_page_ex(url, user_config)
        return text

    def _fetch_page_ex(self, url, user_config) -> tuple[str | None, str]:
        """抓取页面，返回 (text, final_url)；final_url 供调用方检测登录重定向."""
        ua = user_config.get("ua", "")
        headers = {"User-Agent": ua} if ua else {}
        proxies = get_proxies() if user_config.get("proxy") else None
        proxy_url = proxies.get("http") if proxies else None
        site = self.get_by_url(url)
        site_id = str(site.id) if site is not None else ""
        pace_wait = 0.0
        if site_id:
            interval = _page_fetch_interval(site_id)
            if interval > 0:
                pace_wait = _claim_page_fetch_slot(site_id, interval)
        if pace_wait > 0:
            log.debug(f"[SiteEngine]{site_id} 页面抓取空/失败退避，{pace_wait:.1f}s 后重试")
            time.sleep(pace_wait)
        rate_limiter = getattr(self, "site_limiter", None)
        rate_limiter_engine = rate_limiter.engine if rate_limiter else None
        rl_kwargs = engine_tools._get_rate_limit_kwargs(self, site)
        cookie = user_config.get("cookie", "")
        if site and site.api:
            auth_headers, auth = engine_tools._build_auth(self, site, user_config)
            headers.update(auth_headers)
            if cookie:
                auth = CookieAuth(cookie)
        else:
            auth = CookieAuth(cookie) if cookie else None

        # 站点开启浏览器自动化：HttpClient 挂载 ChromeTransport，
        # 用实验室指纹画像自动导航，挑战页可绕过；请求携带 cookie（CookieAuth）
        # render_html=True：让 nexus-chrome 渲染页面后返回，而非挑战页原始 body
        def _request(with_browser) -> tuple[str | None, str]:
            # 浏览器模式请求用完即关（release）：非持久会话立即删除，
            # 避免 nexus-chrome 会话/标签页在进程退出前持续堆积
            client = None
            try:
                client = HttpClient(
                    config=HttpClientConfig(proxy_url=proxy_url, browser=with_browser),
                    rate_limiter=rate_limiter_engine,
                )
                res = client.get(url=url, headers=headers, auth=auth, **rl_kwargs)
                final = str(res.url) if getattr(res, "url", None) else url
                if not res.is_success:
                    log.debug(f"[SiteEngine]页面抓取非 2xx: HTTP {res.status_code} url={str(url)[:80]}")
                    return None, final
                return res.text, final
            except Exception as e:
                # 鉴权失败被重定向到登录页时，CF 挑战/403 会抛异常且消息含 login URL，
                # 把异常中的最终地址透传，供自检调用方识别（正常路径不受影响）
                err_msg = str(e)
                return None, (err_msg if "login" in err_msg.lower() else url)
            finally:
                if client is not None and with_browser is not None:
                    client.close()

        # 站点需开启“浏览器自动化”才会尝试 chrome 降级；否则仅直连
        text, final_url = _request(None)
        if (text is None or is_challenge(text)) and site and user_config.get("chrome"):
            try:
                text2, final2 = _request(
                    build_browser_mode(
                        site_info={
                            "chrome": True,
                            "ua": ua,
                            "browser_render": True,
                            "browser_persistent": bool(user_config.get("browser_persistent")),
                        },
                        site_key=site.id,
                        proxy_url=proxy_url,
                        render_html=True,
                    )
                )
                if text2 is not None:
                    text, final_url = text2, final2
            except Exception as e:
                log.debug(f"[SiteEngine]浏览器降级抓取失败: {e}")
        if site_id:
            blocked = text is None and "login" not in str(final_url).lower()
            _record_page_fetch_result(site_id, ok=not blocked)
        return text, final_url

    # ---- 连接测试 ----

    def test_connection(self, url: str, user_config: dict | None = None) -> tuple:
        site = self.get_by_url(url)
        if not site:
            return False, "未找到站点定义", 0
        user_config = user_config or {}
        if site.api:
            test_cfg = site.api.endpoints.get("test_connection")
            if not test_cfg:
                return False, "站点未配置连接测试端点", 0
            start = time.time()
            result = engine_tools._call_endpoint(self, test_cfg, site, user_config, {})
            latency = round(time.time() - start, 3)
            if result is None:
                return False, "连接失败", latency
            raw = JsonUtils.dumps(result, separators=(",", ":")) if not isinstance(result, str) else result
            if not is_logged_in(raw):
                auth_type = (site.api.auth.get("type") if site.api.auth else "") or ""
                if auth_type in ("cookie", "csrf"):
                    return False, "Cookie失效", latency
                if auth_type == "bearer":
                    return False, "Token失效", latency
                return False, "密钥失效", latency
            return True, "连接成功", latency
        if site.html:
            return engine_connection.test_html_connection(self, site, user_config, base_url=url)
        return False, "未配置 API 或 HTML 端点", 0

    # ---- 用户信息 ----

    def register_user_info_factory(self, factory):
        self._user_info_factories.append(factory)

    def get_user_info(
        self,
        url,
        site_name,
        site_cookie,
        html_text=None,
        site_headers=None,
        ua="",
        emulate=False,
        proxy=False,
        session=None,
        api_key=None,
        bearer_token=None,
        browser_persistent=False,
    ):
        for factory in self._user_info_factories:
            result = factory(
                url,
                site_name,
                site_cookie,
                self,
                html_text=html_text,
                site_headers=site_headers,
                ua=ua,
                emulate=emulate,
                proxy=proxy,
                session=session,
                api_key=api_key,
                bearer_token=bearer_token,
                browser_persistent=browser_persistent,
            )
            if result:
                return result
        return None

    def prefetch_user_profile(
        self, url, site_cookie, site_headers=None, ua="", proxy=False, session=None, api_key=None, bearer_token=None
    ):
        return engine_user_info.prefetch_user_profile(
            self,
            url,
            site_cookie,
            site_headers=site_headers,
            ua=ua,
            proxy=proxy,
            session=session,
            api_key=api_key,
            bearer_token=bearer_token,
        )

    # ---- 字幕 ----

    def resolve_subtitle(
        self, page_url: str, torrent_id: str, subtitle_dir: str, user_config: dict | None = None
    ) -> int:
        site = self.get_by_url(page_url)
        if not site or not site.subtitle:
            return 0
        user_config = user_config or {}
        tid = self._extract_tid(page_url, site) or torrent_id
        list_cfg = site.subtitle.list_endpoint
        genlink_cfg = site.subtitle.genlink_endpoint
        dl_cfg = site.subtitle.download_endpoint
        if not list_cfg or not dl_cfg:
            return 0
        subs = engine_tools._call_endpoint(self, list_cfg, site, user_config, {"tid": tid}) or []
        if not isinstance(subs, list):
            return 0
        cnt = 0
        for sub in subs:
            sid = sub.get("id", "") if isinstance(sub, dict) else ""
            if not sid:
                continue
            genlink_vars = {"tid": tid, "subtitle_id": sid}
            link = (
                engine_tools._call_endpoint(self, genlink_cfg, site, user_config, genlink_vars) if genlink_cfg else None
            )
            if link:
                dl_cfg_path = dl_cfg.get("path", "").format(tid=tid, subtitle_id=sid)
                dl_url = f"{(site.api.base_url or '').rstrip('/')}/{dl_cfg_path.lstrip('/')}" if site.api else ""
                if engine_tools._call_endpoint(
                    self,
                    {"method": "GET", "path": dl_url},
                    site,
                    user_config,
                    {},
                    credential=str(sid),
                    download_dir=subtitle_dir,
                    download=True,
                ):
                    cnt += 1
            else:
                if engine_tools._call_endpoint(
                    self,
                    dl_cfg,
                    site,
                    user_config,
                    {"tid": tid, "subtitle_id": sid},
                    credential=str(sid),
                    download_dir=subtitle_dir,
                    download=True,
                ):
                    cnt += 1
        return cnt

    # ---- 内部工具 (委托给 engine_tools) ----

    def _call_endpoint(self, cfg, site, user_config, template_vars, credential="", download_dir="", download=False):
        return engine_tools._call_endpoint(
            self,
            cfg,
            site,
            user_config,
            template_vars,
            credential=credential,
            download_dir=download_dir,
            download=download,
        )

    def _build_auth(self, site, user_config):
        return engine_tools._build_auth(self, site, user_config)

    def _build_headers(self, site, user_config):
        return engine_tools._build_headers(self, site, user_config)

    def _resolve_auth_token(self, site, user_config, token_type):
        return engine_tools._resolve_auth_token(self, site, user_config, token_type)

    def _fetch_csrf_token(self, site, user_config):
        return engine_tools._fetch_csrf_token(self, site, user_config)

    def _fetch_passkey(self, site, user_config):
        return engine_tools._fetch_passkey(self, site, user_config)

    @staticmethod
    def _extract_tid(page_url: str, site: SiteDefinition | None = None) -> str | None:
        if not page_url:
            return None
        pattern = site.tid_pattern if site else r"\d+"
        match = re.findall(pattern, page_url)
        return match[-1] if match else None

    @staticmethod
    def _base_from_url(url: str) -> str:
        parts = urlparse(url)
        return f"{parts.scheme}://{parts.netloc}"

    def get_auth_token(self, site_id, token_type):
        cache_key = f"{site_id}:{token_type}"
        return self._auth_cache.get(cache_key)


def get_tid_by_url(url: str, site_engine: SiteEngine) -> str | None:
    """从下载链接提取种子 ID"""
    if not url:
        return None
    # 优先提取显式 tid 参数：部分站点 RSS 链接同时含 tid 与 uid（如 M-Team dlv2）
    explicit = re.search(r"(?:[?&])tid=(\d+)", url)
    if explicit:
        return explicit.group(1)
    # 从 URL 路径的数字段取最后一个（种子 id 通常在路径末尾，避免 RSS token/uid 干扰）
    path_segments = [s for s in urlparse(url).path.split("/") if s.isdigit()]
    if path_segments:
        return path_segments[-1]
    site_def = site_engine.get_by_url(url)
    # 域名可能含数字（如 u2.dmhy.org 里的 2），剥离 host 后再匹配，避免把域名数字当 tid
    url_without_host = re.sub(r"^[a-zA-Z]+://[^/]+", "", url)
    if site_def and site_def.download and site_def.download.type in ("api", "api_chained"):
        pattern = site_def.tid_pattern if site_def.tid_pattern else r"\d+"
        tid = re.findall(pattern, url_without_host)
        return tid[-1] if tid else None
    pattern = site_def.tid_pattern if site_def and site_def.tid_pattern else r"id=(\d+)"
    tid = re.findall(pattern, url_without_host)
    # 取最后一个数字（种子 id 一般在链接尾部）
    return tid[-1] if tid else None
