"""FastAPI 主应用."""

import asyncio
import os
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import Depends, FastAPI, Request, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from scalar_fastapi import get_scalar_api_reference
from starlette.exceptions import HTTPException as StarletteHTTPException

import log
import version
from api.deps import get_message
from api.routers import (
    apikey,
    auth,
    browser_fingerprint,
    brush,
    chat,
    download,
    filter,
    image,
    kb,
    media,
    message_webhook,
    plugin_framework,
    rbac,
    rss_automation,
    scheduler,
    site,
    storage_backend,
    subscription,
    sync,
    system,
    words,
)
from app.core.settings import settings
from app.db import init_db
from app.db.engine import get_engine
from app.di.builders.context_builder import build_app_context
from app.downloader.client import init_clients as init_downloaders
from app.indexer.client import init_clients as init_indexers
from app.infrastructure.rate_limiter.middleware import RateLimitMiddleware
from app.infrastructure.redis import RedisStore
from app.infrastructure.thread import ThreadExecutor
from app.mediaserver.client import init_clients as init_mediaservers
from app.message.client.manager import init_clients as init_message_clients
from app.message.message import Message
from app.schemas.common import HealthCheckResponse, HealthServiceStatus
from app.services.system.lifecycle import SystemLifecycleService


@asynccontextmanager
async def lifespan(app: FastAPI):
    """应用生命周期管理：启动后台服务"""
    app.state.ready = False

    try:
        app_context = build_app_context()
        app.state.context = app_context
    except Exception as e:
        log.error(f"[FastAPI]构建应用上下文失败: {e}")
        raise

    try:
        log.info("[FastAPI]初始化数据库表结构...")
        init_db()
    except Exception as e:
        log.error(f"[FastAPI]数据库初始化失败: {e}")
        raise

    try:
        log.info("[FastAPI]启动后台服务...")
        system_lifecycle: SystemLifecycleService = app_context.system_lifecycle
        system_lifecycle.start_service()
    except Exception as e:
        log.error(f"[FastAPI]后台服务启动失败: {e}")
        raise

    log.info("[FastAPI]后台服务启动完成")

    for name, init_fn in [
        ("索引器", init_indexers),
        ("下载器", init_downloaders),
        ("媒体服务器", init_mediaservers),
        ("消息客户端", init_message_clients),
    ]:
        try:
            init_fn()
            log.info(f"[FastAPI]{name}注册完成")
        except Exception as e:
            log.error(f"[FastAPI]{name}注册失败: {e}")

    app.state.ready = True
    log.info("[FastAPI]核心服务已就绪，后台加载插件...")

    async def _load_plugins_and_refresh_menus():
        """后台加载插件、同步菜单、初始化消息客户端，避免阻塞核心服务就绪."""
        try:
            message: Message = app_context.message
            plugin_sandbox = app_context.plugin_sandbox
            await asyncio.to_thread(plugin_sandbox.load_all)
            log.info("[FastAPI]插件加载完成")
            await asyncio.to_thread(app_context.plugin_framework_service.refresh_plugin_menus_at_startup)
            log.info("[FastAPI]插件菜单同步完成")
            await asyncio.to_thread(lambda: message.active_clients)
            log.info("[FastAPI]消息客户端初始化完成")
            await asyncio.to_thread(message.refresh_menus)
            log.info("[FastAPI]消息菜单刷新完成")
        except Exception as e:
            log.error(f"[FastAPI]后台插件或消息初始化失败: {e}")

    startup_task = asyncio.create_task(_load_plugins_and_refresh_menus())

    yield

    if startup_task and not startup_task.done():
        startup_task.cancel()
        try:
            await startup_task
        except asyncio.CancelledError:
            pass

    log.info("[FastAPI]关闭后台服务...")
    try:
        system_lifecycle.stop_service()
    except Exception as e:
        log.error(f"[FastAPI]服务关闭异常: {e}")
    log.info("[FastAPI]后台服务已关闭")

    ThreadExecutor.shutdown_all()


app = FastAPI(
    title="Nexus Media API",
    description="Nexus Media FastAPI 路由",
    version=version.APP_VERSION,
    lifespan=lifespan,
    docs_url=None,
    redoc_url=None,
)


_debug = bool((settings.get("app") or {}).get("debug"))

if _debug:

    @app.get("/docs", include_in_schema=False)
    async def scalar_html():
        return get_scalar_api_reference(
            openapi_url=app.openapi_url,
            title=app.title,
        )


# CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)


# 速率限制中间件：Redis 可用时分布式限流，否则降级为内存限流
app.add_middleware(RateLimitMiddleware, rate="60/m")


@app.middleware("http")
async def startup_guard(request: Request, call_next):
    """初始化期间返回 503，防止前端请求报内部错误。"""
    if request.url.path in ("/health", "/", "/ws"):
        return await call_next(request)
    if not getattr(request.app.state, "ready", False):
        return _startup_503_response()
    return await call_next(request)


def _startup_503_response() -> JSONResponse:
    return JSONResponse(
        status_code=503,
        content={"code": -1, "message": "服务正在启动中，请稍后刷新..."},
        headers={
            "Access-Control-Allow-Origin": "*",
            "Access-Control-Allow-Methods": "GET, POST, PUT, DELETE, OPTIONS",
            "Access-Control-Allow-Headers": "*",
        },
    )


# 注册 Router（按领域逐步增加）
app.include_router(system.router, prefix="/api/system", tags=["system"])
app.include_router(site.router, prefix="/api/site", tags=["site"])
app.include_router(download.router, prefix="/api/download", tags=["download"])
app.include_router(subscription.router, prefix="/api/subscription", tags=["subscription"])
app.include_router(sync.router, prefix="/api/sync", tags=["sync"])
app.include_router(storage_backend.router, prefix="/api/storage", tags=["storage"])
app.include_router(brush.router, prefix="/api/brush", tags=["brush"])
app.include_router(filter.router, prefix="/api/filter", tags=["filter"])
app.include_router(scheduler.router, prefix="/api/scheduler", tags=["scheduler"])
app.include_router(plugin_framework.router, prefix="/api/plugin-framework", tags=["plugin-framework"])
app.include_router(rss_automation.router, prefix="/api/rss-automation", tags=["rss-automation"])
app.include_router(words.router, prefix="/api/words", tags=["words"])
app.include_router(media.router, prefix="/api/media", tags=["media"])
app.include_router(rbac.router, prefix="/api/rbac", tags=["rbac"])
app.include_router(browser_fingerprint.router, prefix="/api", tags=["browser-fingerprint"])
app.include_router(auth.router, prefix="/api/auth", tags=["authentication"])
app.include_router(image.router, prefix="/img", tags=["image"])
app.include_router(apikey.router, prefix="/api/apikey", tags=["apikey"])
app.include_router(kb.router, prefix="/api/agent", tags=["agent"])
app.include_router(chat.router, prefix="/api/agent", tags=["agent"])
# 消息客户端 webhook（不需要 /api 前缀）
app.include_router(message_webhook.router, tags=["message-webhook"])

# 挂载静态文件
_static_dir = str(Path(settings.data_path) / "static")
os.makedirs(_static_dir, exist_ok=True)
app.mount("/static", StaticFiles(directory=_static_dir), name="static")


@app.get("/", include_in_schema=False, summary="根路径")
def root():
    """根路径欢迎页面"""
    return JSONResponse(
        content={
            "app": "Nexus Media",
            "version": version.APP_VERSION,
            "message": "服务运行中，请通过前端页面访问或查看 /docs 获取 API 文档",
        }
    )


@app.get("/health", response_model=HealthCheckResponse, summary="健康检查")
def health_check(message: Message = Depends(get_message)):
    """健康检查：验证数据库、Redis 及关键外部服务的可用性"""
    result = HealthCheckResponse(status="ok", version=version.APP_VERSION)

    # 数据库检查
    try:
        engine = get_engine()
        if engine is None:
            raise RuntimeError("数据库引擎未初始化")
        with engine.connect() as conn:
            conn.exec_driver_sql("SELECT 1")
        result.database = HealthServiceStatus(status="ok", detail="数据库连接正常")
    except Exception as e:
        result.status = "degraded"
        result.database = HealthServiceStatus(status="error", detail=f"数据库连接失败: {e!s}")

    # Redis 检查
    try:
        redis_ok = RedisStore().ping()
        if redis_ok:
            result.redis = HealthServiceStatus(status="ok", detail="Redis 连接正常")
        else:
            result.status = "degraded"
            result.redis = HealthServiceStatus(status="error", detail="Redis 不可用")
    except Exception as e:
        result.status = "degraded"
        result.redis = HealthServiceStatus(status="error", detail=f"Redis 检查失败: {e!s}")

    # 关键外部服务：消息客户端
    try:
        msg_clients = message.active_clients
        result.services["message"] = HealthServiceStatus(status="ok", detail=f"已配置 {len(msg_clients)} 个消息客户端")
    except Exception as e:
        result.services["message"] = HealthServiceStatus(status="error", detail=f"消息客户端检查失败: {e!s}")

    return result


@app.exception_handler(StarletteHTTPException)
async def http_exception_handler(request: Request, exc: StarletteHTTPException):
    """
    全局 HTTP 异常处理器
    当页面路由返回 401 时，自动重定向到登录页（兼容浏览器行为）
    API 路由返回 JSON 格式错误
    """
    if exc.status_code == 401:
        path = request.url.path
        # API 路由返回 JSON 401，页面路由重定向到登录页
        if path.startswith("/api/"):
            return JSONResponse(
                status_code=status.HTTP_401_UNAUTHORIZED,
                content={"code": -1, "message": "认证失败，请重新登录"},
            )
        return RedirectResponse(url="/")
    return JSONResponse(status_code=exc.status_code, content={"detail": exc.detail})


@app.exception_handler(Exception)
async def global_exception_handler(request: Request, exc: Exception):
    log.error(f"[API]请求异常: {request.method} {request.url.path} - {exc}")
    return JSONResponse(
        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        content={"code": -1, "message": str(exc)},
    )
