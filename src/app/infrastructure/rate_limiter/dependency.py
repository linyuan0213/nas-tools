"""FastAPI 速率限制依赖 — 按路由精细化限流."""

from fastapi import Request

from app.core.error_codes import ErrorCode
from app.core.exceptions import NexusError
from app.infrastructure.rate_limiter import RateLimitEngine


class RateLimitDependency:
    """
    FastAPI 依赖注入式速率限制器

    用法：
        from app.infrastructure.rate_limiter import RateLimitDependency

        @app.post("/api/auth/login")
        async def login(
            credentials: LoginRequest,
            _rate: None = Depends(RateLimitDependency(rate="5/m")),
        ):
            ...

    :param rate: 速率字符串，如 "60/m"
    :param key_prefix: 限流 key 前缀，默认使用路由路径
    """

    _engine: RateLimitEngine | None = None

    def __init__(self, rate: str = "60/m", key_prefix: str | None = None):
        if RateLimitDependency._engine is None:
            RateLimitDependency._engine = RateLimitEngine()
        self.rate = rate
        self.key_prefix = key_prefix

    async def __call__(self, request: Request) -> None:
        assert RateLimitDependency._engine is not None
        client_ip = self._get_client_ip(request)
        route = self.key_prefix or request.url.path
        key = f"rate_limit_dep:{client_ip}:{route}"

        if not RateLimitDependency._engine.try_acquire(key, rate=self.rate):
            raise NexusError(
                "请求过于频繁，请稍后再试",
                errcode=ErrorCode.RATE_LIMITED,
                http_status=429,
            )

    @staticmethod
    def _get_client_ip(request: Request) -> str:
        """获取真实客户端 IP"""
        forwarded = request.headers.get("X-Forwarded-For")
        if forwarded:
            return forwarded.split(",")[0].strip()
        real_ip = request.headers.get("X-Real-Ip")
        if real_ip:
            return real_ip.strip()
        return request.client.host if request.client else "unknown"
