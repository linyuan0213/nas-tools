"""
Plugin Framework Router - FastAPI
插件框架 v2 API 路由
"""

import asyncio
import inspect
import json
import os
import tempfile
import threading
from typing import Any

from fastapi import APIRouter, Depends, File, Request, Response, UploadFile
from fastapi.responses import FileResponse
from pydantic import BaseModel

import log
from api.deps import get_hook_system, get_plugin_framework_service, require_any_permission, require_permission
from app.core.error_codes import ErrorCode
from app.core.exceptions import DomainError, NexusError, ServiceError
from app.core.settings import settings
from app.plugin_framework import api_registry
from app.plugin_framework.hook_system import HookSystem
from app.schemas.common import CommonResponse
from app.services.plugin_framework_service import PluginFrameworkService
from app.utils.response import fail, success

router = APIRouter()


# ---------------------------------------------------------------------------
# Request Models
# ---------------------------------------------------------------------------


class PluginIdRequest(BaseModel):
    plugin_id: str


class PluginConfigRequest(BaseModel):
    plugin_id: str
    config: dict


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------


@router.get("/plugins", response_model=CommonResponse, summary="列出所有插件")
def list_plugins(
    user: str = Depends(require_any_permission("plugin:view", "plugin:manage")),
    svc: PluginFrameworkService = Depends(get_plugin_framework_service),
):
    """列出所有已安装插件"""
    plugins = svc.list_plugins()
    return success(data=plugins)


@router.get("/plugins/{plugin_id}/manifest", response_model=CommonResponse, summary="获取插件清单")
def get_plugin_manifest(
    plugin_id: str,
    user: str = Depends(require_any_permission("plugin:view", "plugin:manage")),
    svc: PluginFrameworkService = Depends(get_plugin_framework_service),
):
    """获取插件完整 manifest"""
    manifest = svc.get_manifest(plugin_id)
    if not manifest:
        return fail(code=ErrorCode.PLUGIN_NOT_FOUND, msg="插件未找到")
    return success(data=manifest.to_dict())


@router.get("/plugins/{plugin_id}/config", response_model=CommonResponse, summary="获取插件配置")
def get_plugin_config(
    plugin_id: str,
    user: str = Depends(require_any_permission("plugin:view", "plugin:manage")),
    svc: PluginFrameworkService = Depends(get_plugin_framework_service),
):
    """获取插件配置"""
    config = svc.get_config(plugin_id)
    fields = svc.get_config_fields(plugin_id)
    return success(data={"config": config, "fields": fields})


@router.put("/plugins/{plugin_id}/config", response_model=CommonResponse, summary="保存插件配置")
def save_plugin_config(
    plugin_id: str,
    req: PluginConfigRequest,
    user: str = Depends(require_permission("plugin:manage")),
    svc: PluginFrameworkService = Depends(get_plugin_framework_service),
):
    """保存插件配置"""
    if not svc.get_manifest(plugin_id):
        return fail(code=ErrorCode.PLUGIN_NOT_FOUND, msg="插件未找到")
    svc.save_config(plugin_id, req.config)
    return success(message="保存成功")


@router.post("/plugins/install", response_model=CommonResponse, summary="安装插件")
def install_plugin(
    file: UploadFile = File(...),
    user: str = Depends(require_permission("plugin:manage")),
    svc: PluginFrameworkService = Depends(get_plugin_framework_service),
):
    """安装插件（上传 zip 包）"""
    try:
        suffix = os.path.splitext(file.filename or "")[1]
        with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as tmp:
            tmp.write(file.file.read())
            tmp_path = tmp.name

        manifest = svc.install(tmp_path)
        os.unlink(tmp_path)

        return success(data={"id": manifest.id, "name": manifest.name}, message="安装成功")
    except (ServiceError, DomainError) as e:
        _code = e.errcode if isinstance(e, NexusError) else ErrorCode.OPERATION_FAILED
        return fail(code=_code, msg=e.message)
    except Exception as e:
        log.error(f"[PluginAPI] 安装插件失败: {e}")
        return fail(msg=f"安装失败: {e!s}")


@router.delete("/plugins/{plugin_id}", response_model=CommonResponse, summary="卸载插件")
def uninstall_plugin(
    plugin_id: str,
    user: str = Depends(require_permission("plugin:manage")),
    svc: PluginFrameworkService = Depends(get_plugin_framework_service),
):
    """卸载插件"""
    if not svc.get_manifest(plugin_id):
        return fail(code=ErrorCode.PLUGIN_NOT_FOUND, msg="插件未找到")

    try:
        svc.uninstall(plugin_id)
        return success(message="卸载成功")
    except (ServiceError, DomainError) as e:
        _code = e.errcode if isinstance(e, NexusError) else ErrorCode.OPERATION_FAILED
        return fail(code=_code, msg=e.message)
    except Exception as e:
        log.error(f"[PluginAPI] 卸载插件失败 {plugin_id}: {e}")
        return fail(msg=f"卸载失败: {e!s}")


@router.post("/plugins/{plugin_id}/enable", response_model=CommonResponse, summary="启用插件")
def enable_plugin(
    plugin_id: str,
    user: str = Depends(require_permission("plugin:manage")),
    svc: PluginFrameworkService = Depends(get_plugin_framework_service),
):
    """启用插件"""
    if not svc.get_manifest(plugin_id):
        return fail(code=ErrorCode.PLUGIN_NOT_FOUND, msg="插件未找到")

    try:
        # 先更新数据库和缓存状态（同步），后台线程加载插件实例
        svc.enable(plugin_id)
        threading.Thread(target=svc._do_enable, args=(plugin_id,), daemon=True).start()
        return success(message="启用中，请稍后刷新")
    except (ServiceError, DomainError) as e:
        _code = e.errcode if isinstance(e, NexusError) else ErrorCode.OPERATION_FAILED
        return fail(code=_code, msg=e.message)
    except Exception as e:
        log.error(f"[PluginAPI] 启用插件失败 {plugin_id}: {e}")
        return fail(msg=f"启用失败: {e!s}")


@router.post("/plugins/{plugin_id}/disable", response_model=CommonResponse, summary="禁用插件")
def disable_plugin(
    plugin_id: str,
    user: str = Depends(require_permission("plugin:manage")),
    svc: PluginFrameworkService = Depends(get_plugin_framework_service),
):
    """禁用插件"""
    if not svc.get_manifest(plugin_id):
        return fail(code=ErrorCode.PLUGIN_NOT_FOUND, msg="插件未找到")

    try:
        svc.disable(plugin_id)
        return success(message="禁用成功")
    except (ServiceError, DomainError) as e:
        _code = e.errcode if isinstance(e, NexusError) else ErrorCode.OPERATION_FAILED
        return fail(code=_code, msg=e.message)
    except Exception as e:
        log.error(f"[PluginAPI] 禁用插件失败 {plugin_id}: {e}")
        return fail(msg=f"禁用失败: {e!s}")


@router.post("/plugins/{plugin_id}/reload", response_model=CommonResponse, summary="重载插件")
def reload_plugin(
    plugin_id: str,
    user: str = Depends(require_permission("plugin:manage")),
    svc: PluginFrameworkService = Depends(get_plugin_framework_service),
):
    """热重载插件"""
    if not svc.get_manifest(plugin_id):
        return fail(code=ErrorCode.PLUGIN_NOT_FOUND, msg="插件未找到")

    try:
        svc.reload_plugin(plugin_id)
        return success(message="重载成功")
    except (ServiceError, DomainError) as e:
        _code = e.errcode if isinstance(e, NexusError) else ErrorCode.OPERATION_FAILED
        return fail(code=_code, msg=e.message)
    except Exception as e:
        log.error(f"[PluginAPI] 重载插件失败 {plugin_id}: {e}")
        return fail(msg=f"重载失败: {e!s}")


@router.post("/plugins/{plugin_id}/run", response_model=CommonResponse, summary="运行插件")
def run_plugin(
    plugin_id: str,
    user: str = Depends(require_permission("plugin:manage")),
    svc: PluginFrameworkService = Depends(get_plugin_framework_service),
):
    """立即运行插件"""
    if not svc.get_manifest(plugin_id):
        return fail(code=ErrorCode.PLUGIN_NOT_FOUND, msg="插件未找到")

    try:
        svc.run_plugin(plugin_id)
        return success(message="运行任务已启动")
    except (ServiceError, DomainError) as e:
        _code = e.errcode if isinstance(e, NexusError) else ErrorCode.OPERATION_FAILED
        return fail(code=_code, msg=e.message)
    except Exception as e:
        log.error(f"[PluginAPI] 运行插件失败 {plugin_id}: {e}")
        return fail(msg=f"运行失败: {e!s}")


def _dispatch_plugin_api(plugin_id: str, api_path: str, params: dict):
    """分发插件自定义 API 请求"""
    handler = api_registry.get_api_handler(plugin_id, api_path)
    if not handler:
        return fail(msg=f"插件接口不存在: {api_path}")
    try:
        result = handler(params)
        if isinstance(result, dict) and "success" in result:
            if result.get("success"):
                return success(data=result.get("data"), message=result.get("message") or "success")
            return fail(msg=result.get("message") or "插件接口调用失败")
        return success(data=result)
    except (ServiceError, DomainError) as e:
        _code = e.errcode if isinstance(e, NexusError) else ErrorCode.OPERATION_FAILED
        return fail(code=_code, msg=e.message)
    except Exception as e:
        log.error(f"[PluginAPI] 插件接口异常 {plugin_id}/{api_path}: {e}")
        return fail(msg=f"插件接口异常: {e!s}")


@router.get("/plugins/{plugin_id}/api/{api_path:path}", response_model=CommonResponse, summary="插件自定义接口GET")
def plugin_api_get(
    plugin_id: str,
    api_path: str,
    request: Request,
    user: str = Depends(require_permission("plugin:view")),
):
    return _dispatch_plugin_api(plugin_id, api_path, dict(request.query_params))


@router.post("/plugins/{plugin_id}/api/{api_path:path}", response_model=CommonResponse, summary="插件自定义接口POST")
async def plugin_api_post(
    plugin_id: str,
    api_path: str,
    request: Request,
    user: str = Depends(require_permission("plugin:manage")),
):
    params: dict = dict(request.query_params)
    try:
        body = await request.json()
        if isinstance(body, dict):
            params.update(body)
    except Exception as e:
        log.debug(f"[PluginAPI] 请求体非 JSON，忽略: {e}")
    return _dispatch_plugin_api(plugin_id, api_path, params)


@router.get("/plugins/{plugin_id}/logs", response_model=CommonResponse, summary="获取插件日志")
def get_plugin_logs(
    plugin_id: str,
    page: int = 1,
    page_size: int = 20,
    user: str = Depends(require_any_permission("plugin:view", "plugin:manage")),
    svc: PluginFrameworkService = Depends(get_plugin_framework_service),
):
    """获取插件日志"""
    result = svc.get_logs(plugin_id, page, page_size)
    return success(data=result)


@router.delete("/plugins/{plugin_id}/logs", response_model=CommonResponse, summary="清空插件日志")
def clear_plugin_logs(
    plugin_id: str,
    user: str = Depends(require_permission("plugin:manage")),
    svc: PluginFrameworkService = Depends(get_plugin_framework_service),
):
    """清空插件日志"""
    svc.clear_logs(plugin_id)
    return success(message="日志已清空")


@router.get("/plugins/{plugin_id}/readme", response_model=CommonResponse, summary="获取插件 README")
def get_plugin_readme(
    plugin_id: str,
    user: str = Depends(require_any_permission("plugin:view", "plugin:manage")),
    svc: PluginFrameworkService = Depends(get_plugin_framework_service),
):
    """获取插件 README"""
    content = svc.get_readme(plugin_id)
    return success(data=content)


@router.get("/hooks/events")
def list_hook_events(
    user: str = Depends(require_any_permission("plugin:view", "plugin:manage")),
    hook_system: HookSystem = Depends(get_hook_system),
):
    """列出所有可用事件"""
    return success(data=hook_system.EVENTS)


@router.get("/plugins/{plugin_id}/data/{filename}")
def get_plugin_data(
    plugin_id: str,
    filename: str,
    user: str = Depends(require_any_permission("plugin:view", "plugin:manage")),
):
    """获取插件数据文件（JSON）"""
    try:
        data_dir = os.path.join(settings.data_path, "plugins_data", plugin_id)
        target = os.path.join(data_dir, filename)
        real_dir = os.path.realpath(data_dir)
        real_target = os.path.realpath(target)
        if not real_target.startswith(real_dir):
            return fail(code=ErrorCode.PARAM_VALIDATION_FAILED, msg="非法路径")
        if not os.path.exists(target):
            return success(data=[])
        with open(target, encoding="utf-8") as f:
            data = json.load(f)
        # 如果是字典，返回 values 列表
        if isinstance(data, dict):
            return success(data=list(data.values()))
        return success(data=data)
    except (ServiceError, DomainError) as e:
        _code = e.errcode if isinstance(e, NexusError) else ErrorCode.OPERATION_FAILED
        return fail(code=_code, msg=e.message)
    except Exception as e:
        log.error(f"[PluginAPI] 获取插件数据失败: {e}")
        return fail(msg=f"获取数据失败: {e!s}")


@router.delete("/plugins/{plugin_id}/data/{filename}/{item_id}")
def delete_plugin_data(
    plugin_id: str,
    filename: str,
    item_id: str,
    user: str = Depends(require_permission("plugin:manage")),
):
    """删除插件数据文件中的某条记录"""
    try:
        data_dir = os.path.join(settings.data_path, "plugins_data", plugin_id)
        target = os.path.join(data_dir, filename)
        real_dir = os.path.realpath(data_dir)
        real_target = os.path.realpath(target)
        if not real_target.startswith(real_dir):
            return fail(code=ErrorCode.PARAM_VALIDATION_FAILED, msg="非法路径")
        if not os.path.exists(target):
            return fail(code=ErrorCode.RESOURCE_NOT_FOUND, msg="数据文件不存在")
        with open(target, encoding="utf-8") as f:
            data = json.load(f)
        if isinstance(data, dict) and item_id in data:
            del data[item_id]
        elif isinstance(data, list):
            data = [x for x in data if str(x.get("id", x)) != item_id]
        else:
            return fail(code=ErrorCode.RESOURCE_NOT_FOUND, msg="记录不存在")
        with open(target, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        return success(message="删除成功")
    except (ServiceError, DomainError) as e:
        _code = e.errcode if isinstance(e, NexusError) else ErrorCode.OPERATION_FAILED
        return fail(code=_code, msg=e.message)
    except Exception as e:
        log.error(f"[PluginAPI] 删除插件数据失败: {e}")
        return fail(msg=f"删除失败: {e!s}")


@router.get("/plugins/{plugin_id}/assets/{file_path:path}")
def get_plugin_asset(
    plugin_id: str,
    file_path: str,
    svc: PluginFrameworkService = Depends(get_plugin_framework_service),
):
    """获取插件前端资源文件（ESM 组件等）.

    URL 中的 /assets/ 前缀映射到插件根目录；
    若插件未提供前端资源，返回空 JS 占位，避免前端 loader 报 404.
    """
    plugin_path = svc.get_plugin_path(plugin_id)
    if not plugin_path:
        return fail(code=ErrorCode.PLUGIN_NOT_FOUND, msg="插件未找到")

    # /assets/ 是虚拟前缀，实际文件位于插件根目录下
    relative_path = file_path
    if relative_path.startswith("assets/"):
        relative_path = relative_path[len("assets/") :]

    target = os.path.join(plugin_path, relative_path)
    real_plugin_path = os.path.realpath(plugin_path)
    real_target = os.path.realpath(target)

    if not real_target.startswith(real_plugin_path):
        return fail(code=ErrorCode.PARAM_VALIDATION_FAILED, msg="非法路径")

    if not os.path.exists(target) or not os.path.isfile(target):
        if relative_path.endswith("index.mjs"):
            empty_esm = "export default {};\n"
            return Response(
                content=empty_esm,
                media_type="application/javascript",
                headers={"Cache-Control": "no-cache, no-store, must-revalidate"},
            )
        return fail(code=ErrorCode.RESOURCE_NOT_FOUND, msg="文件不存在")

    return FileResponse(
        target,
        headers={"Cache-Control": "no-cache, no-store, must-revalidate"},
    )


_MAX_CALLBACK_BODY = 1 * 1024 * 1024


@router.post("/webhooks/{plugin_id}/{webhook_path:path}", summary="插件公开回调")
async def plugin_public_webhook(plugin_id: str, webhook_path: str, request: Request):
    """插件公开回调（免鉴权），供飞书/Telegram 等外部平台 webhook 回调.

    处理器由插件通过 PluginContext.register_public_webhook(path, handler) 注册，
    约定 handler(params: dict) -> dict。来源校验由插件回调内自行完成（如 apikey）。
    query 参数与 JSON body 合并后一并传入 handler。
    """
    handler = api_registry.get_webhook_handler(plugin_id, webhook_path)
    if not handler:
        return _webhook_response({"code": -1, "msg": "回调接口不存在"})
    # 先按 Content-Length 预检，再流式读取累计，超限即中断（防大 body 内存 DoS）
    content_length = request.headers.get("content-length")
    if content_length:
        try:
            if int(content_length) > _MAX_CALLBACK_BODY:
                return _webhook_response({"code": -1, "msg": "请求体过大"})
        except ValueError:
            pass
    chunks = []
    size = 0
    async for chunk in request.stream():
        size += len(chunk)
        if size > _MAX_CALLBACK_BODY:
            return _webhook_response({"code": -1, "msg": "请求体过大"})
        chunks.append(chunk)
    raw = b"".join(chunks)
    params: dict = dict(request.query_params)
    if raw:
        try:
            body = json.loads(raw)
            if isinstance(body, dict):
                params.update(body)
        except ValueError:
            pass
    # _client_ip 为真实来源 IP，禁止被 query/body 覆盖（防伪造绕过白名单）
    params.pop("_client_ip", None)
    params["_client_ip"] = request.client.host if request.client else ""
    try:
        if inspect.iscoroutinefunction(handler):
            result = await handler(params)
        else:
            result = await asyncio.to_thread(handler, params)
    except Exception as e:
        log.error(f"[PluginAPI] 插件回调异常 {plugin_id}/{webhook_path}: {e}")
        return _webhook_response({"code": -1, "msg": f"回调处理异常: {e!s}"})
    if result is None:
        result = {"code": 0, "msg": "success"}
    return _webhook_response(result)


def _webhook_response(data: Any) -> Response:
    """构造插件回调 JSON 响应"""
    return Response(content=json.dumps(data, ensure_ascii=False), media_type="application/json")
