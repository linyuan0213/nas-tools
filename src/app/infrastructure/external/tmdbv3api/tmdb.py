"""TMDb API 核心 — 基于 HttpClient 重写."""

import os
import threading

from app.infrastructure.http.client import HttpClient
from app.infrastructure.http.config import HttpClientConfig
from app.infrastructure.http.retry import HttpRetryConfig
from app.infrastructure.tmdb import get_rate_limiter
from app.utils.config_tools import get_proxies

from .as_obj import AsObj
from .exceptions import TMDbError

# 语言必须线程隔离：TMDB_LANGUAGE 原用全局环境变量，多线程并发（转移/识别/别名补取）
# 会相互覆盖，导致转移重命名拿到英文标题。改为线程本地，各线程互不影响。
_tmdb_local = threading.local()


def _proxy_url_from_settings() -> str | None:
    """从全局配置读取代理地址."""
    proxies = get_proxies() or {}
    if isinstance(proxies, dict):
        return proxies.get("http") or proxies.get("https")
    return None


class TMDb:
    TMDB_API_KEY = "TMDB_API_KEY"
    TMDB_LANGUAGE = "TMDB_LANGUAGE"
    TMDB_DOMAIN = "TMDB_DOMAIN"

    def __init__(self, session=None):
        self._session = session
        self._remaining = 40
        self._reset = None
        if not getattr(_tmdb_local, "language", None):
            _tmdb_local.language = "zh"
        if not os.environ.get(self.TMDB_DOMAIN):
            os.environ[self.TMDB_DOMAIN] = "https://api.themoviedb.org/3"

    def _get_client(self) -> HttpClient:
        """获取或创建带限流 + 重试的 HttpClient 实例."""
        if self._session is not None:
            return self._session
        return HttpClient(
            config=HttpClientConfig(proxy_url=_proxy_url_from_settings(), timeout=10),
            retry_config=HttpRetryConfig(max_attempts=3, min_wait=1.0),
            rate_limiter=get_rate_limiter().engine,
        )

    @property
    def page(self):
        return os.environ["PAGE"]

    @property
    def total_results(self):
        return os.environ["TOTAL_RESULTS"]

    @property
    def total_pages(self):
        return os.environ["TOTAL_PAGES"]

    @property
    def api_key(self):
        return os.environ.get(self.TMDB_API_KEY)

    @property
    def domain(self):
        return os.environ.get(self.TMDB_DOMAIN)

    @domain.setter
    def domain(self, domain):
        os.environ[self.TMDB_DOMAIN] = str(domain or "")

    @api_key.setter
    def api_key(self, api_key):
        os.environ[self.TMDB_API_KEY] = str(api_key)

    @property
    def language(self):
        return getattr(_tmdb_local, "language", "zh")

    @language.setter
    def language(self, language):
        _tmdb_local.language = language

    @staticmethod
    def _get_obj(result, key="results", all_details=False):
        if "success" in result and result["success"] is False:
            raise TMDbError(result["status_message"])
        if all_details is True or key is None:
            return AsObj(**result)
        else:
            return [AsObj(**res) for res in result[key]]

    def _call(self, action, append_to_response, method="GET", data=None):
        if self.api_key is None or self.api_key == "":
            raise TMDbError("No API key found.")

        url = (
            f"{self.domain}{action}?api_key={self.api_key}"
            f"&include_adult=false&{append_to_response}&language={self.language}"
        )

        client = self._get_client()
        req = client.request(
            method,
            url,
            data=data,
            rate_limit_key="tmdb:api",
            rate_limit_rate="2.5/s",
            rate_limit_timeout=30,
        )

        headers = req.headers
        if "X-RateLimit-Remaining" in headers:
            self._remaining = int(headers["X-RateLimit-Remaining"])
        if "X-RateLimit-Reset" in headers:
            self._reset = int(headers["X-RateLimit-Reset"])

        json_data = req.json()

        if "page" in json_data:
            os.environ["PAGE"] = str(json_data["page"])
        if "total_results" in json_data:
            os.environ["TOTAL_RESULTS"] = str(json_data["total_results"])
        if "total_pages" in json_data:
            os.environ["TOTAL_PAGES"] = str(json_data["total_pages"])

        if "errors" in json_data:
            raise TMDbError(json_data["errors"])

        return json_data
