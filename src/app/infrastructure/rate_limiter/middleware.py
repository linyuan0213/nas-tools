"""FastAPI 速率限制中间件."""

from fastapi import Request
from fastapi.responses import JSONResponse
from starlette.middleware.base import BaseHTTPMiddleware

import log
from app.infrastructure.rate_limiter import RateLimitEngine


class RateLimitMiddleware(BaseHTTPMiddleware):
    """
    全局 API 速率限制中间件

    基于客户端 IP 的令牌桶限流，Redis 可用时分布式生效，
    否则降级为单进程内存限流。

    豁免路径：
    - /health  健康检查
    - /static  静态文件
    - /docs /openapi.json  Swagger
    """

    _EXEMPT_PATHS = {"/health", "/static", "/docs", "/openapi.json", "/redoc"}

    # 特定路径自定义限流规则：{path: rate}
    _PATH_LIMITS: dict[str, str] = {
        "/api/system/refresh": "30/m",
        "/api/auth/login": "5/m",
        "/api/agent/chat": "20/m",
        "/api/agent/chat/confirm": "20/m",
        "/api/agent/message/interact": "10/m",
        "/api/agent/message/stream": "10/m",
    }

    def __init__(self, app, rate: str = "60/m"):
        super().__init__(app)
        self._engine = RateLimitEngine()
        self._rate = rate

    async def dispatch(self, request: Request, call_next):
        path = request.url.path

        # 豁免路径
        if any(path.startswith(exempt) for exempt in self._EXEMPT_PATHS):
            return await call_next(request)

        # 提取客户端 IP
        client_ip = self._get_client_ip(request)
        key = f"api:{client_ip}:{path}"

        # 特定路径使用自定义限流，其余使用全局默认值
        rate = self._PATH_LIMITS.get(path, self._rate)

        if not self._engine.try_acquire(key, rate=rate):
            log.warn(f"[RateLimit]IP {client_ip} 请求 {path} 触发限流")
            return JSONResponse(
                content={"detail": "请求过于频繁，请稍后再试"},
                status_code=429,
            )

        return await call_next(request)

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
