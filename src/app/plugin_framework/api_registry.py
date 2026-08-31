"""插件自定义 API 注册表.

统一注册表以 (kind, plugin_id, path) 为键，两条分发路径共享归一化与注销语义：
- API：PluginContext.register_api 注册，/api/plugin-framework/plugins/{id}/api/{path}（需登录态）
- 公开回调：PluginContext.register_public_webhook 注册，/api/plugin-framework/webhooks/{id}/{path}（免鉴权）

handler 约定：handler(params: dict) -> dict
- 返回 {"success": bool, "message": str, "data": ...} 时映射为 success/fail 响应
- 返回其他值时包装为 success(data=result)
"""

import threading
from collections.abc import Callable

PluginApiHandler = Callable[[dict], object]

_KIND_API = "api"
_KIND_WEBHOOK = "webhook"

_handlers: dict[tuple[str, str, str], PluginApiHandler] = {}
_lock = threading.Lock()


def _register(kind: str, plugin_id: str, path: str, handler: PluginApiHandler) -> None:
    """按 (kind, plugin_id, path) 注册处理器"""
    normalized = path.strip("/")
    if not plugin_id or not normalized:
        return
    with _lock:
        _handlers[(kind, plugin_id, normalized)] = handler


def _unregister(kind: str, plugin_id: str) -> None:
    """移除指定 kind 下某插件的全部注册"""
    with _lock:
        for key in [k for k in _handlers if k[0] == kind and k[1] == plugin_id]:
            _handlers.pop(key, None)


def register_api(plugin_id: str, path: str, handler: PluginApiHandler) -> None:
    """注册插件 API 处理器"""
    _register(_KIND_API, plugin_id, path, handler)


def unregister_plugin_apis(plugin_id: str) -> None:
    """移除插件的全部 API 注册（卸载/禁用时调用）"""
    _unregister(_KIND_API, plugin_id)


def get_api_handler(plugin_id: str, path: str) -> PluginApiHandler | None:
    """获取插件 API 处理器"""
    with _lock:
        return _handlers.get((_KIND_API, plugin_id, path.strip("/")))


def register_public_webhook(plugin_id: str, path: str, handler: PluginApiHandler) -> None:
    """注册插件公开回调（免鉴权），供外部平台 webhook 回调"""
    _register(_KIND_WEBHOOK, plugin_id, path, handler)


def get_webhook_handler(plugin_id: str, path: str) -> PluginApiHandler | None:
    """获取插件公开回调处理器"""
    with _lock:
        return _handlers.get((_KIND_WEBHOOK, plugin_id, path.strip("/")))


def unregister_plugin_all(plugin_id: str) -> None:
    """移除插件全部注册（API + 公开回调）"""
    with _lock:
        for key in [k for k in _handlers if k[1] == plugin_id]:
            _handlers.pop(key, None)
