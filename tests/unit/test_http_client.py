"""HttpClient 单元测试 — 同步/异步客户端、限流、缓存、中间件、认证、重试."""

from __future__ import annotations

from unittest.mock import patch

import httpx2
import pytest

from app.infrastructure.http import (
    ApiKeyAuth,
    AsyncHttpClient,
    BearerAuth,
    CookieAuth,
    HttpCacheConfig,
    HttpClient,
    HttpClientConfig,
    HttpClientError,
    HttpMiddleware,
    HttpRetryConfig,
    LoggingMiddleware,
)
from app.infrastructure.rate_limiter import MemoryTokenBucketBackend, RateLimitEngine

# ==================== HttpClient 基础测试 ====================


def test_http_client_default_init():
    client = HttpClient()
    assert client._config.timeout == 120.0
    client.close()


def test_http_client_custom_config():
    config = HttpClientConfig(timeout=5.0, max_connections=10)
    client = HttpClient(config=config)
    assert client._config.timeout == 5.0
    client.close()


def test_http_client_get(mock_httpx_client):
    client = HttpClient()
    resp = client.get("https://example.com", params={"q": "test"})
    assert resp.status_code == 200
    assert resp.text == "mock body"
    client.close()


def test_http_client_post(mock_httpx_client):
    client = HttpClient()
    resp = client.post("https://example.com", data="body")
    assert resp.status_code == 200
    client.close()


def test_http_client_put_delete(mock_httpx_client):
    client = HttpClient()
    assert client.put("https://example.com").status_code == 200
    assert client.delete("https://example.com").status_code == 200
    client.close()


def test_http_client_context_manager(mock_httpx_client):
    with HttpClient() as client:
        assert client.get("https://example.com").status_code == 200


def test_http_client_error_propagation(mock_httpx_error):
    client = HttpClient()
    with pytest.raises(HttpClientError) as exc_info:
        client.get("https://example.com")
    assert exc_info.value.status_code == 500
    client.close()


# ==================== raise_for_status 测试 ====================


def test_raise_for_status_disabled(mock_httpx_status_error):
    client = HttpClient()
    resp = client.get("https://example.com", raise_for_status=False)
    assert resp.status_code == 418
    client.close()


def test_raise_for_status_enabled(mock_httpx_status_error):
    client = HttpClient()
    with pytest.raises(HttpClientError):
        client.get("https://example.com")
    client.close()


# ==================== 限流器测试 ====================


def test_rate_limiter_acquire_blocks(mock_httpx_client):
    backend = MemoryTokenBucketBackend()
    engine = RateLimitEngine(backend=backend)
    client = HttpClient(rate_limiter=engine)
    resp = client.get("https://example.com", rate_limit_key="test_key", rate_limit_rate="10/m")
    assert resp.status_code == 200
    client.close()


def test_rate_limiter_without_key_passes(mock_httpx_client):
    backend = MemoryTokenBucketBackend()
    engine = RateLimitEngine(backend=backend)
    client = HttpClient(rate_limiter=engine)
    resp = client.get("https://example.com")
    assert resp.status_code == 200
    client.close()


# ==================== 缓存测试 ====================


def test_cache_hit_stores_and_returns(mock_httpx_client):
    from app.infrastructure.cache_system.adapters import MemoryCacheAdapter

    adapter = MemoryCacheAdapter(name="test", maxsize=10)
    cache = HttpCacheConfig(cache_name="test", default_ttl=60)
    cache.set_adapter(adapter)
    client = HttpClient(cache=cache)
    # 首次请求
    resp1 = client.get("https://example.com/cached")
    assert resp1.status_code == 200
    # 第二次应命中缓存
    resp2 = client.get("https://example.com/cached")
    assert resp2.status_code == 200
    client.close()


def test_cache_bypass_skips_cache(mock_httpx_client):
    from app.infrastructure.cache_system.adapters import MemoryCacheAdapter

    adapter = MemoryCacheAdapter(name="test", maxsize=10)
    cache = HttpCacheConfig(cache_name="test", default_ttl=60)
    cache.set_adapter(adapter)
    client = HttpClient(cache=cache)
    resp1 = client.get("https://example.com/cached")
    resp2 = client.get("https://example.com/cached", cache_bypass=True)
    assert resp1.status_code == 200
    assert resp2.status_code == 200
    client.close()


def test_cache_not_cacheable_post(mock_httpx_client):
    from app.infrastructure.cache_system.adapters import MemoryCacheAdapter

    adapter = MemoryCacheAdapter(name="test", maxsize=10)
    cache = HttpCacheConfig(cache_name="test")
    cache.set_adapter(adapter)
    client = HttpClient(cache=cache)
    client.post("https://example.com", data="x")
    cached = adapter.get("http:POST:https://example.com")
    assert cached is None
    client.close()


# ==================== 中间件测试 ====================


class _TestMiddleware(HttpMiddleware):
    def __init__(self):
        self.requests = []
        self.responses = []

    def process_request(self, request):
        self.requests.append(request.method)
        return request

    def process_response(self, response):
        self.responses.append(response.status_code)
        return response


def test_middleware_pipeline(mock_httpx_client):
    mw = _TestMiddleware()
    client = HttpClient(middlewares=[mw])
    client.get("https://example.com/a")
    client.get("https://example.com/b")
    assert mw.requests == ["GET", "GET"]
    assert mw.responses == [200, 200]
    client.close()


def test_logging_middleware_no_error(mock_httpx_client):
    client = HttpClient(middlewares=[LoggingMiddleware()])
    resp = client.get("https://example.com")
    assert resp.status_code == 200
    client.close()


# ==================== 认证测试 ====================


def test_bearer_auth():
    auth = BearerAuth("token123")
    req = httpx2.Request("GET", "https://example.com")
    for r in auth.auth_flow(req):
        pass
    assert req.headers["Authorization"] == "Bearer token123"


def test_api_key_auth_header():
    auth = ApiKeyAuth("X-API-Key", "secret", location="header")
    req = httpx2.Request("GET", "https://example.com")
    for r in auth.auth_flow(req):
        pass
    assert req.headers["X-API-Key"] == "secret"


def test_api_key_auth_query():
    auth = ApiKeyAuth("key", "val", location="query")
    req = httpx2.Request("GET", "https://example.com")
    for r in auth.auth_flow(req):
        pass
    assert "key=val" in str(req.url)


def test_cookie_auth_from_dict():
    auth = CookieAuth({"session": "abc", "token": "xyz"})
    req = httpx2.Request("GET", "https://example.com")
    for r in auth.auth_flow(req):
        pass
    assert "session=abc" in req.headers["Cookie"]
    assert "token=xyz" in req.headers["Cookie"]


def test_cookie_auth_from_string():
    auth = CookieAuth("session=abc; token=xyz")
    req = httpx2.Request("GET", "https://example.com")
    for r in auth.auth_flow(req):
        pass
    assert "session=abc" in req.headers["Cookie"]


def test_http_client_with_auth_in_config(mock_httpx_client):
    auth = BearerAuth("token")
    config = HttpClientConfig(auth=auth)
    client = HttpClient(config=config)
    resp = client.get("https://example.com")
    assert resp.status_code == 200
    client.close()


# ==================== 重试测试 ====================


def test_retry_connect_error():
    config = HttpRetryConfig(max_attempts=2, min_wait=0.001)
    retrying = config.build_retrying()
    call_count = [0]

    @retrying.wraps
    def failing():
        call_count[0] += 1
        if call_count[0] < 2:
            raise httpx2.ConnectError("try again")
        return "ok"

    result = retrying(failing)
    assert result == "ok"
    assert call_count[0] == 2


def test_retry_timeout():
    config = HttpRetryConfig(max_attempts=2, min_wait=0.001)
    retrying = config.build_retrying()
    call_count = [0]

    @retrying.wraps
    def failing():
        call_count[0] += 1
        if call_count[0] < 2:
            raise httpx2.TimeoutException("try again")
        return "ok"

    result = retrying(failing)
    assert result == "ok"
    assert call_count[0] == 2


# ==================== 配置测试 ====================


def test_http_client_config_defaults():
    config = HttpClientConfig()
    assert config.timeout == 120.0
    assert config.connect_timeout == 10.0
    assert config.verify_ssl is True
    assert config.follow_redirects is True


def test_http_client_config_custom():
    config = HttpClientConfig(
        max_connections=50,
        timeout=10.0,
        verify_ssl=False,
        proxy_url="http://proxy:8080",
    )
    assert config.max_connections == 50
    assert config.proxy_url == "http://proxy:8080"


# ==================== 异常测试 ====================


def test_http_client_error_from_httpx():
    from httpx2 import HTTPStatusError, Request, Response

    req = Request("GET", "https://example.com")
    resp = Response(500, request=req, content=b"internal error")
    exc = HTTPStatusError("server error", request=req, response=resp)
    converted = HttpClientError.from_httpx(exc)
    assert converted.status_code == 500
    assert converted.response_text and "internal error" in converted.response_text


def test_http_client_error_from_connect_error():
    exc = httpx2.ConnectError("connection refused")
    converted = HttpClientError.from_httpx(exc)
    assert converted.status_code is None


# ==================== 异步客户端测试 ====================


@pytest.mark.asyncio
async def test_async_http_client_get(mock_async_client):
    client = AsyncHttpClient(config=HttpClientConfig(enable_http2=False))
    resp = await client.get("https://example.com")
    assert resp.status_code == 200
    await client.close()


@pytest.mark.asyncio
async def test_async_http_client_post_put_delete(mock_async_client):
    client = AsyncHttpClient(config=HttpClientConfig(enable_http2=False))
    assert (await client.post("https://example.com")).status_code == 200
    assert (await client.put("https://example.com")).status_code == 200
    assert (await client.delete("https://example.com")).status_code == 200
    await client.close()


@pytest.mark.asyncio
async def test_async_http_client_context(mock_async_client):
    async with AsyncHttpClient(config=HttpClientConfig(enable_http2=False)) as client:
        assert (await client.get("https://example.com")).status_code == 200


@pytest.mark.asyncio
async def test_async_http_client_error(mock_async_error):
    client = AsyncHttpClient(config=HttpClientConfig(enable_http2=False))
    with pytest.raises(HttpClientError):
        await client.get("https://example.com")
    await client.close()


@pytest.mark.asyncio
async def test_async_http_client_raise_for_status_false(mock_async_status_error):
    client = AsyncHttpClient(config=HttpClientConfig(enable_http2=False))
    resp = await client.get("https://example.com", raise_for_status=False)
    assert resp.status_code == 418
    await client.close()


# ==================== 连接池复用测试 ====================


def test_http_client_connection_pool_reuse(mock_httpx_client):
    """相同配置的 HttpClient 应复用底层 httpx2.Client."""
    config = HttpClientConfig(timeout=10.0)
    client1 = HttpClient(config=config)
    client2 = HttpClient(config=config)
    assert client1._client is client2._client
    client1.close()
    client2.close()


def test_http_client_connection_pool_release(mock_httpx_client):
    """最后一个引用释放后才真正关闭底层 client."""
    config = HttpClientConfig(timeout=10.0)
    client1 = HttpClient(config=config)
    client2 = HttpClient(config=config)
    underlying = client1._client
    client1.close()
    # 仍有一个引用，底层 client 未被关闭
    assert underlying is client2._client
    client2.close()


def test_http_client_different_config_different_pool(mock_httpx_client):
    """不同配置应创建不同底层 client."""
    config1 = HttpClientConfig(timeout=10.0)
    config2 = HttpClientConfig(timeout=20.0)
    client1 = HttpClient(config=config1)
    client2 = HttpClient(config=config2)
    assert client1._client is not client2._client
    client1.close()
    client2.close()


@pytest.mark.asyncio
async def test_async_http_client_connection_pool_reuse(mock_async_client):
    """相同配置的 AsyncHttpClient 应复用底层 httpx2.AsyncClient."""
    config = HttpClientConfig(timeout=10.0, enable_http2=False)
    client1 = AsyncHttpClient(config=config)
    client2 = AsyncHttpClient(config=config)
    assert client1._client is client2._client
    await client1.close()
    await client2.close()


@pytest.mark.asyncio
async def test_async_http_client_connection_pool_release(mock_async_client):
    """AsyncHttpClient 引用计数归零后才关闭底层 client."""
    config = HttpClientConfig(timeout=10.0, enable_http2=False)
    client1 = AsyncHttpClient(config=config)
    client2 = AsyncHttpClient(config=config)
    underlying = client1._client
    await client1.close()
    assert underlying is client2._client
    await client2.close()


# ==================== fixtures ====================


@pytest.fixture
def mock_httpx_client():
    with patch.object(httpx2.Client, "request") as mock_req:
        mock_req.return_value = httpx2.Response(
            200, content=b"mock body", request=httpx2.Request("GET", "https://example.com")
        )
        yield mock_req


@pytest.fixture
def mock_httpx_error():
    with patch.object(httpx2.Client, "request") as mock_req:
        mock_req.side_effect = httpx2.HTTPStatusError(
            "error",
            request=httpx2.Request("GET", "https://example.com"),
            response=httpx2.Response(
                500, request=httpx2.Request("GET", "https://example.com"), content=b"internal error"
            ),
        )
        yield mock_req


@pytest.fixture
def mock_httpx_status_error():
    with patch.object(httpx2.Client, "request") as mock_req:
        mock_req.return_value = httpx2.Response(
            418, content=b"teapot", request=httpx2.Request("GET", "https://example.com")
        )
        yield mock_req


@pytest.fixture
def mock_async_client():
    with (
        patch.object(httpx2.AsyncClient, "request") as mock_req,
        patch.object(httpx2.AsyncClient, "aclose", return_value=None),
    ):
        mock_req.return_value = httpx2.Response(
            200, content=b"async mock", request=httpx2.Request("GET", "https://example.com")
        )
        yield mock_req


@pytest.fixture
def mock_async_error():
    with (
        patch.object(httpx2.AsyncClient, "request") as mock_req,
        patch.object(httpx2.AsyncClient, "aclose", return_value=None),
    ):
        mock_req.side_effect = httpx2.HTTPStatusError(
            "error",
            request=httpx2.Request("GET", "https://example.com"),
            response=httpx2.Response(500, request=httpx2.Request("GET", "https://example.com"), content=b"error"),
        )
        yield mock_req


@pytest.fixture
def mock_async_status_error():
    with (
        patch.object(httpx2.AsyncClient, "request") as mock_req,
        patch.object(httpx2.AsyncClient, "aclose", return_value=None),
    ):
        mock_req.return_value = httpx2.Response(
            418, content=b"teapot", request=httpx2.Request("GET", "https://example.com")
        )
        yield mock_req
