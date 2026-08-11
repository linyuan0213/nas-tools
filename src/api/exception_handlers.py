"""统一异常处理器

将所有异常转换为统一响应结构：{"code": <errcode>, "message": str, "data": None}
在 main.py 中通过 register_exception_handlers(app) 注册。
"""

from fastapi import FastAPI, Request, status
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse, RedirectResponse
from starlette.exceptions import HTTPException as StarletteHTTPException
from starlette.responses import Response

import log
from app.core.error_codes import ErrorCode
from app.core.exceptions import NexusError
from app.utils.response import fail

_HTTP_STATUS_ERRCODE: dict[int, ErrorCode] = {
    status.HTTP_400_BAD_REQUEST: ErrorCode.PARAM_VALIDATION_FAILED,
    status.HTTP_401_UNAUTHORIZED: ErrorCode.UNAUTHORIZED,
    status.HTTP_403_FORBIDDEN: ErrorCode.PERMISSION_DENIED,
    status.HTTP_404_NOT_FOUND: ErrorCode.RESOURCE_NOT_FOUND,
    status.HTTP_409_CONFLICT: ErrorCode.RESOURCE_ALREADY_EXISTS,
    status.HTTP_429_TOO_MANY_REQUESTS: ErrorCode.RATE_LIMITED,
}


async def nexus_error_handler(request: Request, exc: NexusError) -> JSONResponse:
    """业务异常：携带 errcode 与 http_status"""
    if exc.http_status >= 500:
        log.error(f"[API]业务异常: {request.method} {request.url.path} - {exc}")
    else:
        log.warn(f"[API]业务异常: {request.method} {request.url.path} - {exc}")
    return JSONResponse(
        status_code=exc.http_status,
        content=fail(code=exc.errcode, msg=exc.message, details=exc.details or None),
        headers=exc.headers or None,
    )


async def http_exception_handler(request: Request, exc: StarletteHTTPException) -> Response:
    """HTTP 异常：映射 HTTP 状态码到业务错误码；页面路由 401 重定向登录页"""
    if exc.status_code == status.HTTP_401_UNAUTHORIZED and not request.url.path.startswith("/api/"):
        return RedirectResponse(url="/")
    fallback = ErrorCode.UNKNOWN if exc.status_code >= 500 else ErrorCode.OPERATION_FAILED
    errcode = _HTTP_STATUS_ERRCODE.get(exc.status_code, fallback)
    if isinstance(exc.detail, str):
        content = fail(code=errcode, msg=exc.detail)
    else:
        # 非字符串 detail（dict/list，如 OAuth2 错误结构）：保留在 details 中
        content = fail(code=errcode, details={"detail": exc.detail})
    return JSONResponse(
        status_code=exc.status_code,
        content=content,
        headers=dict(exc.headers) if exc.headers else None,
    )


async def validation_exception_handler(request: Request, exc: RequestValidationError) -> JSONResponse:
    """请求参数校验异常（pydantic）"""
    errors = [{"loc": list(e.get("loc", ())), "msg": e.get("msg", "")} for e in exc.errors()]
    first_msg = errors[0]["msg"] if errors else ""
    return JSONResponse(
        status_code=status.HTTP_400_BAD_REQUEST,
        content=fail(
            code=ErrorCode.PARAM_VALIDATION_FAILED,
            msg=f"参数校验失败: {first_msg}",
            details={"errors": errors},
        ),
    )


async def global_exception_handler(request: Request, exc: Exception) -> JSONResponse:
    """兜底异常：统一 500"""
    log.error(f"[API]未处理异常: {request.method} {request.url.path} - {exc}")
    return JSONResponse(
        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        content=fail(code=ErrorCode.INTERNAL_ERROR, msg="服务器内部错误"),
    )


def register_exception_handlers(app: FastAPI) -> None:
    app.add_exception_handler(NexusError, nexus_error_handler)  # type: ignore[arg-type]
    app.add_exception_handler(StarletteHTTPException, http_exception_handler)  # type: ignore[arg-type]
    app.add_exception_handler(RequestValidationError, validation_exception_handler)  # type: ignore[arg-type]
    app.add_exception_handler(Exception, global_exception_handler)  # type: ignore[arg-type]
