import re
from abc import ABC, abstractmethod
from dataclasses import dataclass, field

from app.infrastructure.http.client import HttpClient
from app.infrastructure.http.config import HttpClientConfig
from app.plugin_framework.context import PluginContext
from app.utils.config_tools import get_proxies


@dataclass
class SiteSigninContext:
    """从 site_info 提取的标准化上下文，站点模块是 URL/凭据唯一来源。"""

    site: str
    site_id: str
    site_url: str
    cookie: str | None
    api_key: str | None
    bearer_token: str | None
    ua: str | None
    proxy_url: str | None
    api_key_header: str | None = None
    headers: dict | None = None
    is_browser: bool = False
    raw: dict = field(default_factory=dict)

    @classmethod
    def from_site_info(cls, site_info: dict, site_engine=None) -> "SiteSigninContext":
        proxy = get_proxies() if site_info.get("proxy") else None
        proxy_url = proxy.get("http") if isinstance(proxy, dict) else (proxy if isinstance(proxy, str) else None)

        raw_site_id = str(site_info.get("id", ""))
        site_id = raw_site_id
        site = site_info.get("name", "")
        site_url = site_info.get("signurl") or site_info.get("strict_url") or site_info.get("rssurl") or ""

        if site_engine:
            site_def = None
            for url in (site_info.get("strict_url"), site_info.get("signurl"), site_info.get("rssurl")):
                if url:
                    site_def = site_engine.get_by_url(url)
                    if site_def:
                        break
            if not site_def and site:
                site_def = site_engine.get_by_name(site)
            if site_def:
                site_id = site_def.id
                site_url = site_url or site_def.domain
                site = site or site_def.name

        return cls(
            site=site,
            site_id=site_id,
            site_url=site_url,
            cookie=site_info.get("cookie"),
            api_key=site_info.get("api_key"),
            bearer_token=site_info.get("bearer_token"),
            ua=site_info.get("ua"),
            proxy_url=proxy_url,
            api_key_header=site_info.get("api_key_header"),
            headers=site_info.get("headers"),
            is_browser=bool(site_info.get("is_browser", False)),
            raw=site_info,
        )


class SigninResult:
    SUCCESS = "签到成功"
    ALREADY = "已签到"
    LOGIN_OK = "登录成功"
    COOKIE_EXPIRED = "cookie失效"
    SITE_UNREACHABLE = "请检查站点连通性"
    REQUEST_FAILED = "签到接口请求失败"
    BROWSER_OK = "浏览器签到成功"

    def __init__(self, ok: bool, msg: str):
        self.ok = ok
        self.msg = msg

    @classmethod
    def success(cls, site: str) -> "SigninResult":
        return cls(True, f"[{site}]{cls.SUCCESS}")

    @classmethod
    def already(cls, site: str) -> "SigninResult":
        return cls(True, f"[{site}]今日{cls.ALREADY}")

    @classmethod
    def fail(cls, site: str, reason: str) -> "SigninResult":
        return cls(False, f"[{site}]签到失败，{reason}")

    @classmethod
    def custom(cls, ok: bool, msg: str) -> "SigninResult":
        return cls(ok, msg)


class SiteSigninHandler(ABC):
    """站点签到处理器基类。"""

    site_id: str = ""
    site_url: str = ""

    def __init__(self, plugin_ctx: PluginContext, rate_limiter=None):
        self._plugin_ctx = plugin_ctx
        self._rate_limiter = rate_limiter

    @abstractmethod
    def signin(self, ctx: SiteSigninContext) -> SigninResult: ...

    def _http_client(self, ctx: SiteSigninContext, **kwargs) -> HttpClient:
        # 浏览器自动化站点统一走 BrowserSigninHandler（签到完关闭页面），
        # 不再在 HTTP 客户端挂 ChromeTransport，避免残留持久会话
        config = HttpClientConfig(proxy_url=ctx.proxy_url, **kwargs)
        return HttpClient(
            config=config,
            rate_limiter=self._rate_limiter,
        )

    @staticmethod
    def sign_in_result(html_res: str, regexs: list[str]) -> bool:
        html_text = re.sub(r"#\d+", "", re.sub(r"\d+px", "", html_res))
        return any(re.search(str(regex), html_text) for regex in regexs)

    def _check_cookie(self, html_text: str, site: str) -> SigninResult | None:
        if "login.php" in html_text:
            return SigninResult.fail(site, SigninResult.COOKIE_EXPIRED)
        return None
