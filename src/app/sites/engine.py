"""
站点引擎 — 统一站点定义加载与功能入口

消除散落在 20+ 个文件中的 'if m-team in url' 逻辑，
通过声明式 JSON 站点定义提供统一的搜索、下载、字幕等功能入口。
"""

import importlib
import os
import re
import time
import traceback
from dataclasses import dataclass, field
from typing import Any
from urllib.parse import urlparse

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
    ):
        ret = {"free": False, "2xfree": False, "hr": False, "peer_count": 0, "labels": ""}
        site = self.get_by_url(torrent_url)
        if not site:
            log.debug(f"[SiteEngine]resolve_torrent_attr 未匹配站点, url={torrent_url[:100]}")
            return ret
        user_config = {
            "cookie": cookie or "",
            "api_key": api_key or "",
            "bearer_token": bearer_token or "",
            "ua": ua or "",
            "proxy": proxy,
            "headers": headers or {},
            "chrome": chrome,
        }

        if site.api and site.torrent_attr:
            tid = self._extract_tid(torrent_url, site)
            if not tid:
                log.debug(f"[SiteEngine]resolve_torrent_attr TID提取失败, url={torrent_url[:100]}")
                return ret
            cfg = site.torrent_attr
            base = site.api.base_url.rstrip("/")
            path = cfg.get("path", "").format(tid=tid)
            url = f"{base}{path}" if path.startswith("/") else path
            body = {k: v.format(tid=tid) for k, v in (cfg.get("body") or {}).items()}
            headers, auth = engine_tools._build_auth(self, site, user_config)
            method = (cfg.get("method") or "POST").upper()
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
                free_path = cfg.get("response", {}).get("free_key", "")
                free_val = cfg.get("response", {}).get("free_value", "")
                free_match = cfg.get("response", {}).get("free_match", "exact")
                if free_path and free_val:
                    extracted = JsonUtils.get_json_object(text, free_path)
                    if self._match_attr_value(extracted, free_val, free_match):
                        ret["free"] = True
                free2x_path = cfg.get("response", {}).get("2xfree_key", "")
                free2x_val = cfg.get("response", {}).get("2xfree_value", "")
                free2x_match = cfg.get("response", {}).get("2xfree_match", "exact")
                if free2x_path and free2x_val:
                    extracted2x = JsonUtils.get_json_object(text, free2x_path)
                    if self._match_attr_value(extracted2x, free2x_val, free2x_match):
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
            if JsonUtils.is_valid_json(html_txt):
                for xp in conf.get("2XFREE", []):
                    if str(JsonUtils.get_json_object(html_txt, xp.split("=")[0])) == xp.split("=")[1]:
                        ret["free"] = True
                        ret["2xfree"] = True
                for xp in conf.get("FREE", []):
                    if str(JsonUtils.get_json_object(html_txt, xp.split("=")[0])) == xp.split("=")[1]:
                        ret["free"] = True
                for xp in conf.get("HR", []):
                    if JsonUtils.get_json_object(html_txt, xp):
                        ret["hr"] = True
                for xp in conf.get("PEER_COUNT", []):
                    val = JsonUtils.get_json_object(html_txt, xp)
                    ret["peer_count"] = int(val) if val else 0
            else:
                doc = etree.HTML(html_txt)
                if doc is not None:
                    for xp in conf.get("2XFREE", []):
                        if doc.xpath(xp):
                            ret["free"] = True
                            ret["2xfree"] = True
                    for xp in conf.get("FREE", []):
                        if doc.xpath(xp):
                            ret["free"] = True
                    for xp in conf.get("HR", []):
                        if doc.xpath(xp):
                            ret["hr"] = True
                    for xp in conf.get("PEER_COUNT", []):
                        els = doc.xpath(xp)
                        if els:
                            txt = "".join(str(t) for t in els[0].itertext())  # type: ignore[union-attr]
                            ret["peer_count"] = int("".join(c for c in txt if c.isdigit()) or 0)
                    ret["labels"] = _extract_detail_labels(doc, site)
        return ret

    def _fetch_page(self, url, user_config):
        ua = user_config.get("ua", "")
        headers = {"User-Agent": ua} if ua else {}
        proxies = get_proxies() if user_config.get("proxy") else None
        proxy_url = proxies.get("http") if proxies else None
        site = self.get_by_url(url)
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
        def _request(with_browser) -> str | None:
            try:
                res = HttpClient(
                    config=HttpClientConfig(proxy_url=proxy_url, browser=with_browser),
                    rate_limiter=rate_limiter_engine,
                ).get(url=url, headers=headers, auth=auth, **rl_kwargs)
                return res.text
            except Exception:
                return None

        # 站点需开启“浏览器自动化”才会尝试 chrome 降级；否则仅直连
        text = _request(None)
        if (text is None or is_challenge(text)) and site and user_config.get("chrome"):
            try:
                text = _request(
                    build_browser_mode(
                        site_info={"chrome": True, "ua": ua, "browser_render": True},
                        site_key=site.id,
                        proxy_url=proxy_url,
                        render_html=True,
                    )
                )
            except Exception:
                text = None
        return text

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
    if site_def and site_def.download and site_def.download.type in ("api", "api_chained"):
        pattern = site_def.tid_pattern if site_def.tid_pattern else r"\d+"
        tid = re.findall(pattern, url)
        return tid[-1] if tid else None
    pattern = site_def.tid_pattern if site_def and site_def.tid_pattern else r"id=(\d+)"
    tid = re.findall(pattern, url)
    return tid[0] if tid else None
