"""媒体库目录与目录同步工具 handler"""

from app.agent.tools.base import ToolResult
from app.agent.tools.context import ToolContext

_PATH_TYPES = {"movie": "电影", "tv": "剧集", "anime": "动漫", "unknown": "未识别"}
_SYNC_MODES = {"copy": "复制", "link": "硬链接", "softlink": "软链接", "move": "移动"}


def media_library_dirs_get(ctx: ToolContext) -> ToolResult:
    """读取媒体库目录配置（电影/剧集/动漫/未识别 各自的目录与存储后端）"""
    svc = ctx.media_config_service
    if not svc:
        return ToolResult(success=False, error="媒体库目录服务不可用")
    try:
        cfg = svc.get_config() or {}
    except Exception as e:  # noqa: BLE001
        return ToolResult(success=False, error=f"读取媒体库目录失败: {e}")
    items = []
    for pt, label in _PATH_TYPES.items():
        items.append(
            {
                "type": pt,
                "label": label,
                "paths": cfg.get(f"{pt}_path") or [],
                "backends": cfg.get(f"{pt}_backend") or [],
            }
        )
    return ToolResult(success=True, data={"items": items})


def media_library_dir_add(
    ctx: ToolContext, path_type: str, path: str, backend: str = "", confirmed: bool = False
) -> ToolResult:
    """在指定媒体库分类下新增一个目录（可指定存储后端名，默认本地 local）"""
    svc = ctx.media_config_service
    if not svc:
        return ToolResult(success=False, error="媒体库目录服务不可用")
    if path_type not in _PATH_TYPES:
        return ToolResult(success=False, error=f"path_type 必须是 {'/'.join(_PATH_TYPES)}")
    if not path:
        return ToolResult(success=False, error="path 必填")
    if not confirmed:
        return ToolResult(
            success=True,
            need_confirm=True,
            data={"action": "library_dir_add", "message": f"在「{_PATH_TYPES[path_type]}」下新增目录 {path} 需确认"},
        )
    try:
        svc.add_path(path_type, path, backend or "")
    except Exception as e:  # noqa: BLE001
        return ToolResult(success=False, error=f"添加媒体库目录失败: {e}")
    return ToolResult(success=True, data={"message": f"已添加 {_PATH_TYPES[path_type]} 目录: {path}"})


def media_library_dir_remove(ctx: ToolContext, path_type: str, path: str, confirmed: bool = False) -> ToolResult:
    """移除指定媒体库分类下的一个目录"""
    svc = ctx.media_config_service
    if not svc:
        return ToolResult(success=False, error="媒体库目录服务不可用")
    if path_type not in _PATH_TYPES or not path:
        return ToolResult(success=False, error="path_type/path 必填")
    if not confirmed:
        return ToolResult(
            success=True,
            need_confirm=True,
            data={"action": "library_dir_remove", "message": f"移除 {_PATH_TYPES[path_type]} 目录 {path} 需确认"},
        )
    try:
        svc.remove_path(path_type, path)
    except Exception as e:  # noqa: BLE001
        return ToolResult(success=False, error=f"移除媒体库目录失败: {e}")
    return ToolResult(success=True, data={"message": f"已移除 {_PATH_TYPES[path_type]} 目录: {path}"})


def storage_backend_list(ctx: ToolContext) -> ToolResult:
    """列出存储后端（本地/WebDAV/SMB 等），用于同步任务选择来源/目的后端"""
    svc = ctx.storage_backend_service
    if not svc:
        return ToolResult(success=False, error="存储后端服务不可用")
    try:
        backends = svc.list_backends() or []
    except Exception as e:  # noqa: BLE001
        return ToolResult(success=False, error=f"读取存储后端失败: {e}")
    items = [
        {"id": b.get("id"), "name": b.get("name"), "type": b.get("type"), "enabled": b.get("enabled")} for b in backends
    ]
    return ToolResult(success=True, data={"total": len(items), "items": items})


def sync_path_list(ctx: ToolContext) -> ToolResult:
    """列出目录同步任务（源目录→目的目录、同步方式、启停状态）"""
    svc = ctx.sync_service
    if not svc:
        return ToolResult(success=False, error="同步服务不可用")
    try:
        paths = svc.get_sync_paths() or {}
    except Exception as e:  # noqa: BLE001
        return ToolResult(success=False, error=f"读取同步任务失败: {e}")
    items = []
    for sid, p in paths.items():
        items.append(
            {
                "id": sid,
                "source": p.get("source"),
                "dest": p.get("dest"),
                "unknown": p.get("unknown"),
                "mode": p.get("operation") or p.get("mode"),
                "src_backend": p.get("src_backend") or "local",
                "dst_backend": p.get("dst_backend") or "local",
                "rename": p.get("rename"),
                "enabled": p.get("enabled"),
            }
        )
    return ToolResult(success=True, data={"total": len(items), "items": items})


def sync_path_save(
    ctx: ToolContext,
    source: str,
    dest: str = "",
    mode: str = "copy",
    src_backend: str = "local",
    dst_backend: str = "local",
    unknown: str = "",
    enabled: bool = True,
    sid: int = 0,
    confirmed: bool = False,
) -> ToolResult:
    """新增或更新一条目录同步任务（源→目的，方式 copy/link/softlink/move，来源/目的可为本地 local 或存储后端名）"""
    svc = ctx.sync_service
    if not svc:
        return ToolResult(success=False, error="同步服务不可用")
    if not source:
        return ToolResult(success=False, error="source（源目录）必填")
    if mode not in _SYNC_MODES:
        return ToolResult(success=False, error=f"mode 必须是 {'/'.join(_SYNC_MODES)}")
    if not confirmed:
        action = "更新" if sid else "新增"
        return ToolResult(
            success=True,
            need_confirm=True,
            data={
                "action": "sync_path_save",
                "message": f"{action}同步任务：{source} → {dest or '(同库整理)'}（{_SYNC_MODES[mode]}）需确认",
            },
        )
    try:
        svc.add_or_edit_sync_path(
            sid=int(sid or 0),
            source=source,
            dest=dest or "",
            unknown=unknown or "",
            mode=mode,
            operation=mode,
            src_backend=src_backend or "local",
            dst_backend=dst_backend or "local",
            compatibility=0,
            rename=0,
            enabled=1 if enabled else 0,
        )
    except Exception as e:  # noqa: BLE001
        return ToolResult(success=False, error=f"保存同步任务失败: {e}")
    return ToolResult(success=True, data={"message": f"同步任务已保存：{source} → {dest or '(同库整理)'}"})


HANDLERS = {
    "media_library_dirs_get": media_library_dirs_get,
    "media_library_dir_add": media_library_dir_add,
    "media_library_dir_remove": media_library_dir_remove,
    "storage_backend_list": storage_backend_list,
    "sync_path_list": sync_path_list,
    "sync_path_save": sync_path_save,
}
