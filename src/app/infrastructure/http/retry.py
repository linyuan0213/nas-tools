"""HTTP 重试配置 — 基于 tenacity."""

from dataclasses import dataclass
from typing import Any

import httpx2
from tenacity import (
    AsyncRetrying,
    Retrying,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential,
)


@dataclass
class HttpRetryConfig:
    """HTTP 重试配置 — 基于 tenacity."""

    max_attempts: int = 3
    min_wait: float = 1.0
    max_wait: float = 60.0
    exp_base: float = 2.0

    def build_retrying(self, **kwargs: Any) -> Retrying:
        """构建 tenacity.Retrying（同步）."""
        return Retrying(
            stop=stop_after_attempt(self.max_attempts),
            wait=wait_exponential(multiplier=self.min_wait, exp_base=self.exp_base, max=self.max_wait),
            retry=retry_if_exception_type(
                (httpx2.ConnectError, httpx2.TimeoutException, httpx2.ReadError, httpx2.WriteError)
            ),
            reraise=True,
            **kwargs,
        )

    def build_async_retrying(self, **kwargs: Any) -> AsyncRetrying:
        """构建 tenacity.AsyncRetrying（异步）."""
        return AsyncRetrying(
            stop=stop_after_attempt(self.max_attempts),
            wait=wait_exponential(multiplier=self.min_wait, exp_base=self.exp_base, max=self.max_wait),
            retry=retry_if_exception_type(
                (httpx2.ConnectError, httpx2.TimeoutException, httpx2.ReadError, httpx2.WriteError)
            ),
            reraise=True,
            **kwargs,
        )
