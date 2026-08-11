"""统一 Web 响应格式工具

统一响应结构：{"code": <errcode>, "message": str, "data": ...}
- 成功：code = 0
- 失败：code = 业务错误码（见 app.core.error_codes.ErrorCode）
"""

from typing import Any

from app.core.error_codes import ErrorCode, default_message


class WebResponse:
    """统一成功/失败响应封装"""

    @staticmethod
    def success(data: Any = None, message: str = "", **kwargs) -> dict[str, Any]:
        result: dict[str, Any] = {"code": ErrorCode.SUCCESS, "message": message}
        if data is not None:
            result["data"] = data
        result.update(kwargs)
        return result

    @staticmethod
    def fail(code: int | ErrorCode = ErrorCode.OPERATION_FAILED, msg: str = "", **kwargs) -> dict[str, Any]:
        if isinstance(code, ErrorCode):
            errcode: int | ErrorCode = code
        else:
            try:
                errcode = ErrorCode(code)
            except ValueError:
                errcode = code
        default_msg = default_message(errcode) if isinstance(errcode, ErrorCode) else "操作失败"
        result: dict[str, Any] = {"code": errcode, "message": msg or default_msg}
        result.update(kwargs)
        return result


# 顶层便捷函数，供装饰器及其他模块直接使用
def success(data: Any = None, **kwargs) -> dict[str, Any]:
    return WebResponse.success(data=data, **kwargs)


def fail(code: int | ErrorCode = ErrorCode.OPERATION_FAILED, msg: str = "", **kwargs) -> dict[str, Any]:
    return WebResponse.fail(code=code, msg=msg, **kwargs)
