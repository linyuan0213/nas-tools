"""站点业务解析层.

替代旧 Sites 类的 test_connection 等业务方法。
从 SiteCache 获取配置，委托 SiteEngine 执行。
"""

from datetime import datetime

from app.infrastructure.http import CookieAuth, HttpClient, HttpClientConfig
from app.sites.engine import SiteEngine
from app.sites.site_cache import SiteCache
from app.sites.utils import is_logged_in
from app.utils import JsonUtils, StringUtils
from app.utils.browser_mode import build_browser_mode
from app.utils.config_tools import get_proxies, get_ua


class SiteResolver:
    """站点业务解析器 — 连通性测试等."""

    def __init__(
        self,
        cache: SiteCache,
        site_engine: SiteEngine,
    ):
        self._cache = cache
        self._site_engine = site_engine

    def test_connection(self, site_id: int | str) -> tuple[bool, str, float]:
        """测试站点连通性.

        :return: (是否连通, 错误信息, 耗时秒数)
        """
        site_info = self._cache.get_sites(siteid=site_id)
        if not site_info:
            return False, "站点获取失败", 0.0
        if not isinstance(site_info, dict):
            return False, "站点不存在", 0.0

        is_public = site_info.get("public", False)
        site_cookie = site_info.get("cookie")
        headers = site_info.get("headers")
        ua = site_info.get("ua") or get_ua()
        proxy = site_info.get("proxy")

        site_url = StringUtils.get_base_url(site_info.get("signurl") or site_info.get("rssurl"))
        if not site_url:
            return False, "未配置站点地址", 0.0

        # 公开站点
        if is_public:
            start_time = datetime.now()
            proxy_url = get_proxies().get("http") if proxy and get_proxies() else None
            use_headers = {"User-Agent": ua} if ua else {}
            cookie_auth = CookieAuth(site_cookie) if site_cookie else None
            res = HttpClient(
                config=HttpClientConfig(proxy_url=proxy_url),
            ).get(url=site_url, headers=use_headers, auth=cookie_auth)
            seconds = round((datetime.now() - start_time).total_seconds(), 3)
            if res and res.status_code == 200:
                # 公开站以“是否被重定向到登录页”判断登录态，
                # 页面本身可匿名访问时（如 mikan）不做登录标记强校验
                final_url = str(getattr(res, "url", "") or "")
                redirect_to_login = "/login" in final_url
                has_auth = bool(site_cookie or headers or site_info.get("api_key") or site_info.get("bearer_token"))
                if redirect_to_login:
                    if has_auth:
                        return False, "Cookie失效", seconds
                    return False, "站点需要登录但未配置认证信息", seconds
                return True, "连接成功", seconds
            elif res is not None:
                return False, f"连接失败，状态码：{res.status_code}", seconds
            return False, "无法打开网站", seconds

        # 需要认证
        if not site_cookie and not headers and not site_info.get("api_key") and not site_info.get("bearer_token"):
            return False, "未配置站点认证信息", 0.0

        if JsonUtils.is_valid_json(headers):
            headers = JsonUtils.loads(headers or "{}")
        else:
            headers = {}
        headers.update({"User-Agent": ua})

        # 优先使用引擎统一测试
        site_def = self._site_engine.get_by_url(site_url)
        if site_def:
            user_config = {
                "cookie": site_cookie,
                "api_key": site_info.get("api_key", ""),
                "bearer_token": site_info.get("bearer_token", ""),
                "ua": ua,
                "headers": headers,
                "proxy": proxy,
            }
            return self._site_engine.test_connection(site_url, user_config)

        # 兜底：HTML 站点
        start_time = datetime.now()
        proxy_url = get_proxies().get("http") if proxy and get_proxies() else None
        browser = build_browser_mode(
            site_info=site_info,
            site_key=site_info.get("domain") or site_info.get("name") or site_url,
            proxy_url=proxy_url,
        )
        res = HttpClient(
            config=HttpClientConfig(proxy_url=proxy_url, browser=browser),
        ).get(url=site_url, headers=headers, auth=CookieAuth(site_cookie))
        seconds = round((datetime.now() - start_time).total_seconds(), 3)
        if res and res.status_code == 200:
            if not is_logged_in(res.text):
                return False, "Cookie失效", seconds
            return True, "连接成功", seconds
        elif res is not None:
            return False, f"连接失败，状态码：{res.status_code}", seconds
        return False, "无法打开网站", seconds
