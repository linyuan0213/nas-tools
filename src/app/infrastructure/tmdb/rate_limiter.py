"""
TMDB API 速率限制器
基于统一 RateLimitEngine 实现，支持按 API Key 区分限流
"""

from tenacity import Retrying, retry_if_exception, stop_after_attempt, wait_exponential

import log
from app.infrastructure.rate_limiter import RateLimitEngine


class TMDBRateLimiter:
    """TMDB API 限流器 — 基于 RateLimitEngine 令牌桶."""

    def __init__(self, engine: RateLimitEngine | None = None):
        self._engine = engine or RateLimitEngine()

    def acquire(self, api_key: str | None = None, timeout: float = 30) -> bool:
        """获取 TMDB 请求许可.

        :param api_key: API Key，多 Key 场景下按 Key 分别限流
        :param timeout: 最大等待秒数
        :return: True=获得许可
        """
        key = f"tmdb:{api_key or 'default'}"
        return self._engine.acquire(key, rate="10/s", burst=10, timeout=timeout)

    def try_acquire(self, api_key: str | None = None) -> bool:
        """尝试获取许可，不等待."""
        return self.acquire(api_key, timeout=0)

    @property
    def engine(self) -> RateLimitEngine:
        """暴露底层限流引擎，供 HttpClient 注入使用."""
        return self._engine

    def get_stats(self, api_key: str | None = None) -> dict:
        """获取限流统计."""
        key = f"tmdb:{api_key or 'default'}"
        return self._engine.get_status(key)


def _should_retry_tmdb(exc):
    """判断 TMDB 异常是否应当重试（仅对限流或服务器错误重试）"""
    status_code = getattr(exc, "status_code", None)
    response = getattr(exc, "response", None)
    if response is not None:
        status_code = getattr(response, "status_code", None)
    if status_code is not None and status_code not in [429, 500, 502, 503, 504]:
        return False
    return True


class TMDBRetryWithBackoff:
    """TMDB API 指数退避重试机制（基于 tenacity）"""

    def __init__(
        self, max_retries: int = 3, base_delay: float = 1.0, max_delay: float = 60.0, exponential_base: float = 2.0
    ):
        self._max_retries = max_retries
        self._base_delay = base_delay
        self._max_delay = max_delay
        self._exponential_base = exponential_base

    def execute(self, func, *args, **kwargs):
        """执行带重试的函数"""

        def _log_retry(retry_state):
            exc = retry_state.outcome.exception()
            wait_time = retry_state.next_action.sleep if retry_state.next_action else 0
            log.warn(f"[TMDBRetry]请求失败，{wait_time:.1f}秒后进行第 {retry_state.attempt_number} 次重试: {exc}")

        for attempt in Retrying(
            stop=stop_after_attempt(self._max_retries + 1),
            wait=wait_exponential(
                multiplier=self._base_delay,
                exp_base=self._exponential_base,
                min=self._base_delay,
                max=self._max_delay,
            ),
            retry=retry_if_exception(_should_retry_tmdb),
            before_sleep=_log_retry,
            reraise=True,
        ):
            with attempt:
                return func(*args, **kwargs)
        return None


# 全局实例
_global_rate_limiter = TMDBRateLimiter()
_global_retry_handler = TMDBRetryWithBackoff()


def get_rate_limiter() -> TMDBRateLimiter:
    """获取全局速率限制器实例"""
    return _global_rate_limiter


def get_retry_handler() -> TMDBRetryWithBackoff:
    """获取全局重试处理器实例"""
    return _global_retry_handler
