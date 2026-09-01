"""引擎连接测试 — 从 engine.py 拆分"""

import time

import log
from app.infrastructure.http.auth import CookieAuth
from app.infrastructure.http.client import HttpClient
from app.infrastructure.http.config import HttpClientConfig
from app.sites import engine_tools
from app.sites.utils import is_logged_in
from app.utils.config_tools import get_proxies


def test_html_connection(engine, site, user_config, base_url=None):
    # 优先使用调用方传入的实际站点地址（用户配置的签到域名/别名），回退站点规范域名
    domain = (base_url or site.domain or "").rstrip("/")
    if not domain.startswith("http"):
        domain = f"https://{domain}"
    if site.html and getattr(site.html, "test_connection", None):
        test_path = str(site.html.test_connection).lstrip("/")
        domain = f"{domain}/{test_path}"
    start = time.time()
    cookie = user_config.get("cookie", "")
    ua = user_config.get("ua", "")
    headers = {"User-Agent": ua} if ua else {}
    proxy = get_proxies() if user_config.get("proxy") else None
    proxy_url = proxy.get("http") if proxy else None
    rate_limiter = getattr(engine, "site_limiter", None)
    rate_limiter_engine = rate_limiter.engine if rate_limiter else None
    rl_kwargs = engine_tools._get_rate_limit_kwargs(engine, site)
    try:
        res = HttpClient(
            config=HttpClientConfig(proxy_url=proxy_url, auth=CookieAuth(cookie) if cookie else None),
            rate_limiter=rate_limiter_engine,
        ).get(url=domain, headers=headers, **rl_kwargs)
    except Exception as e:
        latency = round(time.time() - start, 3)
        log.error(f"[SiteEngine]请求异常 {domain}: {e}")
        return False, "无法打开网站", latency
    latency = round(time.time() - start, 3)
    if not is_logged_in(res.text):
        return False, "Cookie失效", latency
    return True, "连接成功", latency
