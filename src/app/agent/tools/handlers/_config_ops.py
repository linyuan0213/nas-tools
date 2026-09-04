"""配置保存共享操作 — 供各写工具 handler 与 config_manifest 复用的持久化逻辑

避免“同一保存语义”在多处重复实现（handler 负责确认/校验与返回文案，manifest 负责批量应用，
两侧都只调用这里的持久化操作）。
"""

import json


def save_indexer_config(svc, client_id: str, enabled: bool, config: dict | None = None) -> None:
    """合并已有索引器配置并保存；失败抛 RuntimeError（调用方负责文案）"""
    if not client_id:
        raise RuntimeError("client_id 必填")
    existing: dict = {}
    try:
        cur = svc.get_config(client_id)
        if cur:
            existing = cur.get("config") or {}
    except Exception:  # noqa: BLE001
        existing = {}
    merged = dict(existing)
    merged.update({k: v for k, v in (config or {}).items() if v is not None})
    data: dict = {"type": client_id, "enabled": 1 if enabled else 0}
    for k, v in merged.items():
        data[f"{client_id}.{k}"] = v
    result = svc.save_config(data)
    if not getattr(result, "success", True):
        raise RuntimeError(getattr(result, "msg", "保存失败"))


def save_message_client(svc, name: str, ctype: str, config: dict, cid: int = 0, enabled: bool = True) -> None:
    """新增/更新消息通知渠道；失败抛 RuntimeError（调用方负责文案）"""
    svc.upsert_client(
        name=name,
        cid=int(cid or 0),
        ctype=ctype,
        config=json.dumps(config, ensure_ascii=False),
        switches="",
        interactive=0,
        enabled=1 if enabled else 0,
        templates="",
    )


def apply_plugin_action(svc, plugin_id: str, action: str, config: dict | None = None) -> None:
    """执行插件启用/禁用/写配置；失败抛 RuntimeError（调用方负责文案）"""
    if action == "enable":
        svc.enable(plugin_id)
    elif action == "disable":
        svc.disable(plugin_id)
    else:
        svc.save_config(plugin_id, config or {})
