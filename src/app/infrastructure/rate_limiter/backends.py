"""RateLimitEngine - 统一限流引擎.

支持令牌桶和滑动窗口两种算法，Redis/内存双后端，支持等待模式.
"""

import re
import threading
import time
from abc import ABC, abstractmethod
from collections import deque

import log
from app.infrastructure.redis import RedisStore


def _parse_rate(rate: str) -> tuple[float, int]:
    """解析速率字符串，如 '10/m' -> (10, 60), '2.5/s' -> (2.5, 1), '1/2s' -> (1, 2)."""

    m = re.match(r"^(\d+\.?\d*)/(\d+\.?\d*)?([smhd])?$", rate.strip())
    if not m:
        raise ValueError(f"Invalid rate format: {rate}")
    count = float(m.group(1))
    interval = float(m.group(2)) if m.group(2) else 1.0
    unit = m.group(3) or "s"
    multipliers: dict[str, int] = {"s": 1, "m": 60, "h": 3600, "d": 86400}
    window = int(interval * multipliers.get(unit, 60))
    return count, window


class RateLimitBackend(ABC):
    """限流后端抽象基类."""

    @abstractmethod
    def acquire(self, key: str, rate: float, burst: int, tokens: int, timeout: float | None) -> bool:
        """原子化获取许可.

        :param rate: 每秒速率
        :param burst: 桶容量/窗口上限
        :param tokens: 本次消耗令牌数
        :param timeout: 最大等待秒数，None=不等待，0=立即返回
        :return: True=获得许可
        """

    @abstractmethod
    def get_status(self, key: str | None = None) -> dict:
        """获取限流状态."""


class MemoryTokenBucketBackend(RateLimitBackend):
    """内存令牌桶后端（线程安全）."""

    def __init__(self):
        self._buckets: dict[str, dict] = {}
        self._lock = threading.Lock()
        self._stats: dict[str, dict] = {}

    def acquire(self, key, rate, burst, tokens, timeout) -> bool:
        deadline = time.time() + timeout if timeout is not None else None
        while True:
            with self._lock:
                bucket = self._buckets.setdefault(key, {"tokens": burst, "last_update": time.time()})
                self._stats.setdefault(key, {"blocked": 0, "waited": 0})
                now = time.time()
                bucket["tokens"] = min(burst, bucket["tokens"] + (now - bucket["last_update"]) * rate)
                bucket["last_update"] = now
                if bucket["tokens"] >= tokens:
                    bucket["tokens"] -= tokens
                    return True
                wait_time = (tokens - bucket["tokens"]) / rate
            if deadline and time.time() + wait_time > deadline:
                with self._lock:
                    self._stats[key]["blocked"] += 1
                return False
            if timeout == 0:
                with self._lock:
                    self._stats[key]["blocked"] += 1
                return False
            with self._lock:
                self._stats[key]["waited"] += 1
            time.sleep(wait_time)

    def get_status(self, key=None) -> dict:
        with self._lock:
            if key:
                bucket = self._buckets.get(key, {})
                stats = self._stats.get(key, {})
                return {
                    "tokens": round(bucket.get("tokens", 0), 2),
                    "blocked": stats.get("blocked", 0),
                    "waited": stats.get("waited", 0),
                }
            return {
                k: {
                    "tokens": round(self._buckets.get(k, {}).get("tokens", 0), 2),
                    "blocked": self._stats.get(k, {}).get("blocked", 0),
                    "waited": self._stats.get(k, {}).get("waited", 0),
                }
                for k in self._buckets
            }


class MemorySlidingWindowBackend(RateLimitBackend):
    """内存滑动窗口后端（线程安全）."""

    def __init__(self):
        self._windows: dict[str, deque[float]] = {}
        self._lock = threading.Lock()
        self._stats: dict[str, dict] = {}

    def acquire(self, key, rate, burst, tokens, timeout) -> bool:
        # 滑动窗口不支持等待模式（无法预测何时有容量）
        deadline = time.time() + timeout if timeout is not None else None
        window = burst / rate if rate > 0 else 60
        while True:
            with self._lock:
                now = time.time()
                cutoff = now - window
                timestamps = self._windows.setdefault(key, deque())
                while timestamps and timestamps[0] < cutoff:
                    timestamps.popleft()
                if len(timestamps) + tokens <= burst:
                    for _ in range(tokens):
                        timestamps.append(now)
                    return True
                stats = self._stats.setdefault(key, {"blocked": 0, "waited": 0})
                if timeout == 0:
                    stats["blocked"] += 1
                    return False
                if deadline and now >= deadline:
                    stats["blocked"] += 1
                    return False
                wait_time = (timestamps[0] + window) - now if timestamps else 0.1
            if deadline and time.time() + wait_time > deadline:
                with self._lock:
                    self._stats.setdefault(key, {"blocked": 0, "waited": 0})["blocked"] += 1
                return False
            with self._lock:
                self._stats.setdefault(key, {"blocked": 0, "waited": 0})["waited"] += 1
            time.sleep(min(wait_time, 0.5))

    def get_status(self, key=None) -> dict:
        with self._lock:
            if key:
                timestamps = self._windows.get(key, deque())
                stats = self._stats.get(key, {})
                return {
                    "count": len(timestamps),
                    "blocked": stats.get("blocked", 0),
                    "waited": stats.get("waited", 0),
                }
            return {
                k: {
                    "count": len(self._windows.get(k, deque())),
                    "blocked": self._stats.get(k, {}).get("blocked", 0),
                    "waited": self._stats.get(k, {}).get("waited", 0),
                }
                for k in self._windows
            }


class RedisTokenBucketBackend(RateLimitBackend):
    """Redis 分布式令牌桶（Lua 原子脚本）."""

    _TOKEN_BUCKET_SCRIPT = """
    local key = KEYS[1]
    local rate = tonumber(ARGV[1])
    local burst = tonumber(ARGV[2])
    local tokens = tonumber(ARGV[3])
    local now = tonumber(ARGV[4])

    local data = redis.call('HMGET', key, 'tokens', 'last_update')
    local current_tokens = tonumber(data[1]) or burst
    local last_update = tonumber(data[2]) or now
    current_tokens = math.min(burst, current_tokens + (now - last_update) * rate / 1000.0)
    if current_tokens >= tokens then
        current_tokens = current_tokens - tokens
        redis.call('HMSET', key, 'tokens', current_tokens, 'last_update', now)
        redis.call('EXPIRE', key, math.ceil(burst / rate * 1000) + 1)
        return 1
    else
        redis.call('HMSET', key, 'tokens', current_tokens, 'last_update', now)
        return 0
    end
    """

    def __init__(self):
        self._redis = RedisStore()
        self._script_sha: str | None = None

    def _load_script(self) -> str | None:
        return self._redis.script_load(self._TOKEN_BUCKET_SCRIPT)

    def acquire(self, key, rate, burst, tokens, timeout) -> bool:
        """原子化获取许可。NOSCRIPT 时自动重载脚本重试。"""
        if not self._redis.is_available():
            return True
        now_ms = int(time.time() * 1000)
        for _ in range(2):
            try:
                if self._script_sha is None:
                    self._script_sha = self._load_script()
                if self._script_sha:
                    result = self._redis.evalsha(self._script_sha, 1, key, rate, burst, tokens, now_ms)
                    return bool(result)
                return True
            except Exception as e:
                err = str(e)
                if "NOSCRIPT" in err:
                    self._script_sha = None
                    continue
                log.warn(f"RedisTokenBucketBackend 限流异常 {key}: {e}")
                return True
        return True

    def get_status(self, key=None) -> dict:
        return {}


class RateLimitEngine:
    """统一限流引擎 — 令牌桶 + 滑动窗口，Redis/内存双后端."""

    def __init__(self, backend: RateLimitBackend | None = None, algorithm: str = "token_bucket"):
        self._algorithm = algorithm
        self._sliding_window_backend: MemorySlidingWindowBackend | None = None
        if backend is None:
            redis = RedisTokenBucketBackend()
            if redis._redis.is_available():
                self._backend = redis
                log.info("[RateLimitEngine]使用 Redis 后端")
            else:
                self._backend = MemoryTokenBucketBackend()
                log.info("[RateLimitEngine]使用内存后端")
        else:
            self._backend = backend

    def acquire(
        self,
        key: str,
        rate: str = "10/m",
        burst: int | None = None,
        tokens: int = 1,
        timeout: float | None = None,
        algorithm: str | None = None,
    ) -> bool:
        """获取执行许可.

        :param key: 限流标识
        :param rate: 速率字符串，如 '10/m', '2.5/s', '100/h'
        :param burst: 突发容量，默认等于 rate 数值
        :param tokens: 本次消耗令牌数
        :param timeout: 最大等待秒数，None=不等待，0=立即返回
        :param algorithm: 覆盖默认算法
        :return: True=获得许可
        """
        count, window = _parse_rate(rate)
        rate_per_sec = count / window
        if burst is None:
            burst = int(count)
        algo = algorithm or self._algorithm
        # 滑动窗口使用不同的内存后端
        if algo == "sliding_window" and isinstance(self._backend, (MemoryTokenBucketBackend, RedisTokenBucketBackend)):
            if self._sliding_window_backend is None:
                self._sliding_window_backend = MemorySlidingWindowBackend()
            return self._sliding_window_backend.acquire(key, rate_per_sec, burst, tokens, timeout)
        # 引擎层统一补阻塞循环（仅 timeout>0 时生效，兼容 timeout=None 非阻塞语义）
        # Lua 脚本内部已处理 ms→s 转换，rate 应为每秒令牌数
        backend_rate = rate_per_sec
        if timeout is not None and timeout > 0:
            deadline = time.time() + timeout
            while True:
                if self._backend.acquire(key, backend_rate, burst, tokens, 0):
                    return True
                if time.time() >= deadline:
                    return False
                time.sleep(0.05)
        return self._backend.acquire(key, backend_rate, burst, tokens, timeout)

    def try_acquire(self, key: str, rate: str = "10/m", tokens: int = 1) -> bool:
        """不等待，立即返回."""
        return self.acquire(key, rate, tokens=tokens, timeout=0)

    def get_status(self, key: str | None = None) -> dict:
        """获取限流状态."""
        return self._backend.get_status(key)


# 兼容旧 API 的快捷类
class RateLimiter:
    """兼容旧接口的限流器 — 滑动窗口，自动选择 Redis/内存后端."""

    def __init__(self):
        redis = RedisTokenBucketBackend()
        if redis._redis.is_available():
            self._backend: RateLimitBackend = redis
        else:
            self._backend = MemorySlidingWindowBackend()

    def is_allowed(self, key: str, limit: int, window: int) -> bool:
        rate_per_sec = limit / window
        return self._backend.acquire(key, rate_per_sec * 1000, limit, 1, 0)
