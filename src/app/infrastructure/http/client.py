"""同步 HTTP 客户端 Facade."""

import contextlib
import hashlib
import io
import threading
from collections.abc import Callable
from typing import Any, BinaryIO

import httpx2

import log
from app.infrastructure.http.browser_transport import ChromeTransport
from app.infrastructure.http.cache import HttpCacheConfig
from app.infrastructure.http.config import HttpClientConfig
from app.infrastructure.http.exceptions import HttpClientError, HttpRateLimitError, HttpSSLError
from app.infrastructure.http.middleware import HttpMiddleware
from app.infrastructure.http.retry import HttpRetryConfig
from app.infrastructure.rate_limiter import RateLimitEngine

_global_host_mapping: dict[str, str] = {}


def register_global_host_mapping(mapping: dict[str, str]) -> None:
    """注册全局 DNS 映射，对所有 HttpClient/AsyncHttpClient 生效。

    映射在请求时动态读取，无需重建连接池。
    """
    _global_host_mapping.clear()
    _global_host_mapping.update(mapping)


class _ClientPool:
    """按 HttpClientConfig 复用底层 httpx2.Client，减少连接池创建开销."""

    def __init__(self):
        self._lock = threading.RLock()
        self._clients: dict[tuple, tuple[httpx2.Client, int]] = {}

    def _make_key(self, config: HttpClientConfig) -> tuple:
        headers = tuple(sorted((config.default_headers or {}).items()))
        auth_key = ""
        if config.auth is not None:
            auth_key = type(config.auth).__name__
            cookies = getattr(config.auth, "_cookies", None)
            if cookies:
                auth_key += "::" + hashlib.md5(str(sorted(cookies.items())).encode()).hexdigest()
        browser_key = (False, "", "", "", "", False)
        if config.browser is not None:
            b = config.browser
            browser_key = (
                b.enabled,
                b.server_url,
                b.session_key,
                b.fingerprint_profile,
                b.user_agent or "",
                b.proxy_url or "",
                b.render_html,
                b.persistent_session,
            )
        return (
            config.proxy_url,
            headers,
            auth_key,
            config.verify_ssl,
            config.follow_redirects,
            config.timeout,
            config.connect_timeout,
            config.max_connections,
            config.max_keepalive,
        ) + browser_key

    def acquire(self, config: HttpClientConfig, builder: Callable[[], httpx2.Client]) -> httpx2.Client:
        key = self._make_key(config)
        with self._lock:
            client, count = self._clients.get(key, (None, 0))
            if client is None:
                client = builder()
            self._clients[key] = (client, count + 1)
            return client

    def release(self, config: HttpClientConfig) -> None:
        key = self._make_key(config)
        with self._lock:
            client, count = self._clients.get(key, (None, 0))
            if client is None:
                return
            count -= 1
            if count <= 0:
                with contextlib.suppress(Exception):
                    client.close()
                self._clients.pop(key, None)
            else:
                self._clients[key] = (client, count)

    def close_all(self) -> None:
        with self._lock:
            for client, _ in self._clients.values():
                with contextlib.suppress(Exception):
                    client.close()
            self._clients.clear()


_pool = _ClientPool()


class HttpClient:
    """同步 HTTP 客户端 Facade.

    封装 httpx2.Client，内置 tenacity 重试、RateLimitEngine 限流、HttpCacheConfig 缓存。
    相同配置的底层 Client 会被复用，避免每次请求创建/销毁连接池。

    按需实例化，由调用方管理生命周期。
    """

    def __init__(
        self,
        config: HttpClientConfig | None = None,
        retry_config: HttpRetryConfig | None = None,
        rate_limiter: RateLimitEngine | None = None,
        cache: HttpCacheConfig | None = None,
        middlewares: list[HttpMiddleware] | None = None,
    ):
        self._config = config or HttpClientConfig()
        self._retry = (retry_config or HttpRetryConfig()).build_retrying()
        self._rate_limiter = rate_limiter
        self._cache = cache
        self._middlewares = middlewares or []
        self._client = _pool.acquire(self._config, self._build_client)
        self._closed = False

    def _build_client(self) -> httpx2.Client:
        limits = httpx2.Limits(
            max_connections=self._config.max_connections,
            max_keepalive_connections=self._config.max_keepalive,
        )
        config_map = self._config.host_mapping or {}

        if self._config.browser and self._config.browser.enabled:
            transport = ChromeTransport(self._config.browser, limits=limits)
            timeout = httpx2.Timeout(
                self._config.timeout,
                connect=self._config.connect_timeout,
            )
            return httpx2.Client(
                transport=transport,
                timeout=timeout,
                follow_redirects=self._config.follow_redirects,
                verify=self._config.verify_ssl,
                proxy=self._config.proxy_url,
                auth=self._config.auth,
                headers=self._config.default_headers,
            )

        class _MappedTransport(httpx2.HTTPTransport):
            def handle_request(self, request):
                host = request.url.host
                mapping = {**_global_host_mapping, **config_map}
                if host and host in mapping:
                    log.debug(f"[HostMapping] {host} -> {mapping[host]} ({request.url})")
                    request.extensions["sni_hostname"] = host
                    request.url = request.url.copy_with(host=mapping[host])
                return super().handle_request(request)

        transport = _MappedTransport(limits=limits, retries=0)
        timeout = httpx2.Timeout(
            self._config.timeout,
            connect=self._config.connect_timeout,
        )
        return httpx2.Client(
            transport=transport,
            timeout=timeout,
            follow_redirects=self._config.follow_redirects,
            verify=self._config.verify_ssl,
            proxy=self._config.proxy_url,
            auth=self._config.auth,
            headers=self._config.default_headers,
        )

    def request(self, method: str, url: str, **kwargs: Any) -> httpx2.Response:
        """执行 HTTP 请求，tenacity 自动重试 + 异常转换."""
        rate_limit_key = kwargs.pop("rate_limit_key", None)
        rate_limit_rate = kwargs.pop("rate_limit_rate", None)
        rate_limit_timeout = kwargs.pop("rate_limit_timeout", None)
        raise_for_status = kwargs.pop("raise_for_status", True)
        raise_exception = kwargs.pop("raise_exception", False)
        raise_on_error = raise_for_status or raise_exception
        cache_ttl = kwargs.pop("cache_ttl", None)
        cache_bypass = kwargs.pop("cache_bypass", False)

        if self._rate_limiter and rate_limit_key and rate_limit_rate:
            acquired = self._rate_limiter.acquire(
                key=rate_limit_key,
                rate=rate_limit_rate,
                timeout=rate_limit_timeout,
            )
            if not acquired:
                raise HttpRateLimitError(f"Rate limit exceeded: {rate_limit_key}")

        if self._cache and not cache_bypass:
            cache_key = self._build_cache_key(method, url, kwargs)
            cached = self._cache.get(cache_key)
            if cached is not None:
                return cached

        def _do_request() -> httpx2.Response:
            response = self._client.request(method, url, **kwargs)
            if raise_on_error:
                response.raise_for_status()
            return response

        # 请求中间件链路
        if self._middlewares:
            tmp_request = httpx2.Request(
                method, url, **{k: v for k, v in kwargs.items() if k in ("headers", "params", "cookies")}
            )
            for mw in self._middlewares:
                tmp_request = mw.process_request(tmp_request)

        try:
            result = self._retry(_do_request)
        except httpx2.HTTPError as e:
            err = HttpClientError.from_httpx(e)
            if isinstance(err, HttpSSLError):
                log.warn(f"[HttpClient]SSL/TLS 请求失败: {method} {url} - {err}")
                raise err
            raise err from e

        # 响应中间件链路
        for mw in self._middlewares:
            result = mw.process_response(result)

        if self._cache and not cache_bypass and self._cache.is_cacheable(method, result):
            ttl = cache_ttl if cache_ttl is not None else self._cache.default_ttl
            cache_key = self._build_cache_key(method, url, kwargs)
            self._cache.set(cache_key, result, ttl=ttl)

        return result

    @staticmethod
    def _build_cache_key(method: str, url: str, kwargs: dict) -> str:
        params = kwargs.get("params")
        if params:
            if isinstance(params, dict):
                sorted_params = "&".join(f"{k}={v}" for k, v in sorted(params.items()))
            else:
                sorted_params = str(params)
            return f"http:{method}:{url}?{sorted_params}"
        return f"http:{method}:{url}"

    def get(self, url: str, **kwargs: Any) -> httpx2.Response:
        return self.request("GET", url, **kwargs)

    def post(self, url: str, **kwargs: Any) -> httpx2.Response:
        return self.request("POST", url, **kwargs)

    def put(self, url: str, **kwargs: Any) -> httpx2.Response:
        return self.request("PUT", url, **kwargs)

    def patch(self, url: str, **kwargs: Any) -> httpx2.Response:
        return self.request("PATCH", url, **kwargs)

    def delete(self, url: str, **kwargs: Any) -> httpx2.Response:
        return self.request("DELETE", url, **kwargs)

    def stream(self, method: str, url: str, **kwargs: Any) -> BinaryIO:
        """流式请求，返回可读的二进制流（支持 iter_bytes）。"""
        resp = self.request(method, url, **kwargs)
        return StreamResponse(resp)

    def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        _pool.release(self._config)

    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.close()

    @staticmethod
    def close_all() -> None:
        """关闭所有复用的底层 Client（用于进程退出清理）."""
        _pool.close_all()


class StreamResponse(io.BytesIO):
    """将 httpx2.Response 的 iter_bytes() 包装为 BinaryIO。"""

    def __init__(self, response: httpx2.Response) -> None:
        super().__init__(b"")
        self._response = response
        self._iterator = response.iter_bytes()
        self._buffer = b""

    def read(self, size: int | None = -1) -> bytes:
        if size is None or size == -1:
            return b"".join(self._iterator)
        while len(self._buffer) < size:
            try:
                chunk = next(self._iterator)
                self._buffer += chunk
            except StopIteration:
                break
        result = self._buffer[:size]
        self._buffer = self._buffer[size:]
        return result

    def close(self) -> None:
        self._response.close()
        super().close()
