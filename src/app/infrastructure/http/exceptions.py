"""HTTP 客户端统一异常体系."""

import httpx2

import log


class HttpClientError(Exception):
    """HTTP 客户端统一异常基类."""

    def __init__(
        self,
        message: str,
        status_code: int | None = None,
        response_text: str | None = None,
    ):
        super().__init__(message)
        self.status_code = status_code
        self.response_text = response_text

    @classmethod
    def from_httpx(cls, exc: httpx2.HTTPError) -> "HttpClientError":
        """从 httpx 异常转换."""
        status_code = None
        response_text = None
        if isinstance(exc, httpx2.HTTPStatusError):
            status_code = exc.response.status_code
            try:
                response_text = exc.response.text[:500]
            except Exception as e:  # noqa: BLE001
                log.debug(f"[HTTP]忽略异常: {e}")

        original = str(exc)
        message = original
        if "UNEXPECTED_EOF_WHILE_READING" in original or "EOF occurred in violation of protocol" in original:
            message = "SSL/TLS 握手被服务端异常关闭，请检查站点网络或证书配置"
            return HttpSSLError(message, status_code=status_code, response_text=response_text)
        return cls(
            message=message,
            status_code=status_code,
            response_text=response_text,
        )


class HttpTimeoutError(HttpClientError):
    """请求超时."""


class HttpConnectionError(HttpClientError):
    """连接失败."""


class HttpSSLError(HttpClientError):
    """SSL/TLS 握手失败."""


class HttpAuthError(HttpClientError):
    """认证失败（401/403）."""


class HttpRateLimitError(HttpClientError):
    """本地限流器拒绝（等待超时仍无令牌）."""
