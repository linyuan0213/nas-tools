"""全量配置清单应用 handler — 一次校验、一次确认、统一应用、逐项报告"""

from typing import Any

from app.agent.sanitize import is_secret_key
from app.agent.tools.base import ToolResult
from app.agent.tools.context import ToolContext
from app.agent.tools.handlers._config_ops import (
    apply_plugin_action,
    save_indexer_config,
    save_message_client,
)
from app.core.settings import settings
from app.domain.enums import SystemConfigKey
from app.services.system.config import ConfigUpdateService

_PLUGIN_ACTIONS = ("enable", "disable", "config")
_CONFIG_SECTIONS = ("app", "media", "pt", "subscribe", "laboratory", "agent")

_SECTION_LABELS = {
    "downloaders": "下载器",
    "message_clients": "消息通知",
    "plugins": "插件",
    "mediaservers": "媒体服务器",
    "indexers": "索引器",
    "scraper": "刮削",
    "config": "系统配置",
}


def config_apply_manifest(ctx: ToolContext, manifest: dict, confirmed: bool = False) -> ToolResult:
    """应用一份全量配置清单（downloaders/message_clients/plugins/mediaservers/indexers/scraper/config）。

    先整体校验与预览，一次确认后统一应用，逐项返回成功/失败。
    """
    if not isinstance(manifest, dict):
        return ToolResult(success=False, error="manifest 必须是一个对象（包含各配置节）")

    entries, errors = _collect(manifest)
    if errors:
        return ToolResult(
            success=False,
            error="清单校验失败：\n"
            + "\n".join(f"- {e}" for e in errors[:20])
            + (f"\n…共 {len(errors)} 项" if len(errors) > 20 else ""),
        )
    if not entries:
        return ToolResult(success=False, error="清单为空，没有可应用的配置")

    if not confirmed:
        preview = _preview(entries)
        return ToolResult(
            success=True,
            need_confirm=True,
            data={
                "action": "apply_manifest",
                "summary": preview,
                "message": "将应用以下配置，确认后统一执行： " + preview,
            },
        )

    results, failures = _apply(ctx, entries)
    ok_count = len(results) - len(failures)
    payload = {"ok": ok_count, "failed": len(failures), "results": results}
    payload["message"] = (
        f"完成 {ok_count}/{len(results)} 项，{len(failures)} 项失败，详见 results"
        if failures
        else f"全部 {ok_count} 项配置已应用"
    )
    return ToolResult(success=not failures, data=payload)


# --------------------------------------------------------------------------- 收集 + 校验


def _collect(manifest: dict) -> tuple[list[dict], list[str]]:
    """把 manifest 展开为 [(section, target, payload)]，同时做字段级校验"""
    errors: list[str] = []
    entries: list[dict] = []

    for sec in ("downloaders", "message_clients", "plugins", "mediaservers", "indexers"):
        items = manifest.get(sec) or []
        if not isinstance(items, list):
            errors.append(f"{sec} 必须是数组")
            continue
        for idx, item in enumerate(items):
            if not isinstance(item, dict):
                errors.append(f"{sec}[{idx}] 必须是对象")
                continue
            err = _validate_entry(sec, item)
            if err:
                errors.append(err)
                continue
            entries.append({"section": sec, "target": _label(sec, item), "payload": item})

    scraper = manifest.get("scraper")
    if scraper is not None:
        if not isinstance(scraper, dict):
            errors.append("scraper 必须是对象")
        else:
            entries.append({"section": "scraper", "target": "刮削配置", "payload": scraper})

    cfg = manifest.get("config") or {}
    if isinstance(cfg, dict):
        for key in cfg:
            k = str(key)
            top = k.split(".", 1)[0]
            if top not in _CONFIG_SECTIONS:
                errors.append(f"config 键不允许: {k}")
            elif is_secret_key(k):
                errors.append(f"config 键为敏感字段，禁止通过清单修改: {k}")
            elif not _is_known_leaf(k):
                errors.append(f"config 未知配置键: {k}")
        if cfg and not any("config 键" in e for e in errors):
            entries.append({"section": "config", "target": f"{len(cfg)} 个配置项", "payload": cfg})
    elif cfg:
        errors.append("config 必须是对象")
    return entries, errors


def _validate_entry(sec: str, item: dict) -> str:
    if sec == "downloaders":
        has_id = bool(item.get("id"))
        if not has_id and (not item.get("name") or not item.get("type")):
            return "downloaders 项：新增下载器需提供 name 与 type；修改已有则填 id"
        has_change = item.get("config") or item.get("host") or item.get("port")
        has_change = has_change or item.get("username") or item.get("password")
        has_change = has_change or item.get("enabled") is not None or item.get("name") or item.get("is_default")
        if has_id and not has_change:
            return "downloaders 项未提供任何要修改的内容"
    elif sec == "message_clients":
        if not item.get("name") or not item.get("type"):
            return f"message_clients[{item.get('name')}] 缺少 name 或 type"
        cfg = item.get("config")
        if not isinstance(cfg, dict) or not cfg:
            return f"message_clients[{item.get('name')}] 缺少非空 config"
    elif sec == "plugins":
        if not item.get("plugin_id"):
            return "plugins 项缺少 plugin_id"
        if item.get("action") not in _PLUGIN_ACTIONS:
            return f"plugins[{item.get('plugin_id')}].action 必须是 {'/'.join(_PLUGIN_ACTIONS)}"
        if item.get("action") == "config" and not isinstance(item.get("config"), dict):
            return f"plugins[{item.get('plugin_id')}] action=config 需提供 config 对象"
    elif sec == "mediaservers":
        if not item.get("name"):
            return "mediaservers 项缺少 name"
        if not isinstance(item.get("config"), dict):
            return f"mediaservers[{item.get('name')}] 缺少 config 对象"
    elif sec == "indexers":
        if not item.get("client_id"):
            return "indexers 项缺少 client_id"
    return ""


def _label(sec: str, item: dict) -> str:
    if sec == "downloaders":
        return f"下载器#{item.get('id')}"
    if sec == "message_clients":
        return f"消息渠道[{item.get('type')}] {item.get('name')}"
    if sec == "plugins":
        return f"插件 {item.get('plugin_id')} -> {item.get('action')}"
    if sec == "mediaservers":
        return f"媒体服务器 {item.get('name')}"
    if sec == "indexers":
        return f"索引器 {item.get('client_id')}"
    return sec


def _preview(entries: list) -> str:
    groups: dict[str, int] = {}
    for e in entries:
        groups[e["section"]] = groups.get(e["section"], 0) + 1
    return "、".join(f"{_SECTION_LABELS.get(s, s)} {n} 项" for s, n in groups.items())


# --------------------------------------------------------------------------- 应用


def _apply(ctx: ToolContext, entries: list) -> tuple[list[dict], list[dict]]:
    results: list[dict] = []
    failures: list[dict] = []
    for entry in entries:
        try:
            msg = _apply_one(ctx, entry)
            results.append({"section": entry["section"], "target": entry["target"], "ok": True, "message": msg})
        except Exception as e:  # noqa: BLE001
            failures.append({"section": entry["section"], "target": entry["target"], "ok": False, "message": str(e)})
            results.append({"section": entry["section"], "target": entry["target"], "ok": False, "message": str(e)})
    return results, failures


def _apply_one(ctx: ToolContext, entry: dict) -> str:
    sec, payload = entry["section"], entry["payload"]
    if sec == "downloaders":
        return _apply_downloader(ctx, payload)
    if sec == "message_clients":
        return _apply_message_client(ctx, payload)
    if sec == "plugins":
        return _apply_plugin(ctx, payload)
    if sec == "mediaservers":
        return _apply_mediaserver(ctx, payload)
    if sec == "indexers":
        return _apply_indexer(ctx, payload)
    if sec == "scraper":
        ctx.system_config_service.set(SystemConfigKey.UserScraperConf, payload)
        return "刮削配置已保存"
    if sec == "config":
        result = ConfigUpdateService.update_config(payload)
        if not getattr(result, "success", True):
            raise RuntimeError(getattr(result, "msg", "保存配置失败"))
        return "系统配置已更新"
    raise RuntimeError(f"未知配置节: {sec}")


def _apply_downloader(ctx: ToolContext, item: dict) -> str:
    core = ctx.downloader_core
    did = int(item["id"]) if item.get("id") else 0
    overlay = dict(item.get("config") or {})
    # 顶层连接字段（host/port/username/password）与 config 一并作为覆盖层合并
    for k in ("host", "port", "username", "password"):
        if item.get(k) is not None:
            overlay[k] = item[k]
    enabled = bool(item["enabled"]) if item.get("enabled") is not None else None
    name, dtype, created = core.upsert_downloader(
        did=did or None,
        name=item.get("name") or "",
        dtype=item.get("type") or "",
        config_overlay=overlay,
        enabled=enabled,
        is_default=bool(item.get("is_default")),
    )
    if created:
        return f"已新增下载器「{name}」({dtype})"
    return "下载器配置已更新"


def _apply_message_client(ctx: ToolContext, item: dict) -> str:
    save_message_client(
        svc=ctx.message_client_service,
        name=item["name"],
        ctype=item["type"],
        config=item["config"],
        cid=int(item.get("cid") or 0),
        enabled=bool(item.get("enabled", True)),
    )
    return "消息渠道已保存"


def _apply_plugin(ctx: ToolContext, item: dict) -> str:
    action = item["action"]
    apply_plugin_action(ctx.plugin_framework_service, item["plugin_id"], action, item.get("config") or {})
    action_cn = {"enable": "启用", "disable": "禁用"}.get(action, "更新配置")
    return f"插件已{action_cn}"


def _apply_mediaserver(ctx: ToolContext, item: dict) -> str:
    svc = ctx.media_server_config_service
    svc.apply_config(
        name=item["name"],
        config_overlay=item["config"],
        enabled=bool(item["enabled"]) if item.get("enabled") is not None else None,
        is_default=bool(item["is_default"]) if item.get("is_default") is not None else None,
    )
    return "媒体服务器配置已更新"


def _apply_indexer(ctx: ToolContext, item: dict) -> str:
    save_indexer_config(
        svc=ctx.indexer_config_service,
        client_id=item["client_id"],
        enabled=bool(item.get("enabled", True)),
        config=item.get("config"),
    )
    return "索引器配置已保存"


def _is_known_leaf(key: str) -> bool:
    try:
        data = settings.get() or {}
    except Exception:  # noqa: BLE001
        return False
    parts = key.split(".")
    cur: Any = data
    for part in parts[:-1]:
        if not isinstance(cur, dict) or part not in cur:
            return False
        cur = cur[part]
    return isinstance(cur, dict) and parts[-1] in cur
