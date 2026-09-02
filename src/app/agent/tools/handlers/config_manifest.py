"""全量配置清单应用 handler — 一次校验、一次确认、统一应用、逐项报告"""

import json
from typing import Any

from app.agent.tools.base import ToolResult
from app.agent.tools.context import ToolContext
from app.core.settings import settings
from app.domain.enums import SystemConfigKey
from app.services.system.config import ConfigUpdateService

_PLUGIN_ACTIONS = ("enable", "disable", "config")
_SECRET_HINTS = ("password", "passwd", "api_key", "apikey", "token", "secret", "cookie", "jwt")
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
            elif any(h in k.lower() for h in _SECRET_HINTS):
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
    conn_fields = {k: item[k] for k in ("host", "port", "username", "password") if item.get(k) is not None}
    merged = dict((item.get("config") or {}))
    merged.update(conn_fields)
    if did:
        current = core.get_downloader_conf(did=did)
        if not current:
            raise RuntimeError(f"下载器不存在: {did}")
        cur_cfg = dict(current.get("config") or {})
        cur_cfg.update({k: v for k, v in merged.items() if v is not None})
        enabled = current.get("enabled") if item.get("enabled") is None else (1 if item["enabled"] else 0)
        core.update_downloader(
            did=did,
            name=item.get("name") or current.get("name") or "",
            enabled=enabled,
            dtype=current.get("type") or "",
            transfer=current.get("transfer"),
            only_nexus_media=current.get("only_nexus_media"),
            match_path=current.get("match_path"),
            rmt_mode=current.get("rmt_mode"),
            config=cur_cfg,
            download_dir=current.get("download_dir"),
        )
        if item.get("is_default"):
            core.set_default_downloader_id(str(did))
        return "下载器配置已更新"
    # 新增下载器（id 自动生成）
    name = item.get("name") or ""
    dtype = item.get("type") or ""
    if not name or not dtype:
        raise RuntimeError("新增下载器需提供 name 与 type")
    enabled = 1 if item.get("enabled", True) else 0
    core.update_downloader(
        did=None,
        name=name,
        enabled=enabled,
        dtype=dtype,
        transfer=item.get("transfer", 0),
        only_nexus_media=item.get("only_nexus_media", 0),
        match_path=0,
        rmt_mode="",
        config=merged,
        download_dir=[],
    )
    if item.get("is_default"):
        try:
            fresh = core.get_downloader_conf()
            target = None
            for k, v in (fresh or {}).items():
                if v.get("name") == name:
                    target = k
                    break
            if target:
                core.set_default_downloader_id(str(target))
        except Exception:  # noqa: BLE001, S110
            pass  # 设默认失败不阻断新增
    return f"已新增下载器「{name}」({dtype})"


def _apply_message_client(ctx: ToolContext, item: dict) -> str:
    svc = ctx.message_client_service
    svc.upsert_client(
        name=item["name"],
        cid=int(item.get("cid") or 0),
        ctype=item["type"],
        config=json.dumps(item["config"], ensure_ascii=False),
        switches="",
        interactive=0,
        enabled=1 if item.get("enabled", True) else 0,
        templates="",
    )
    return "消息渠道已保存"


def _apply_plugin(ctx: ToolContext, item: dict) -> str:
    svc = ctx.plugin_framework_service
    action = item["action"]
    if action == "enable":
        svc.enable(item["plugin_id"])
    elif action == "disable":
        svc.disable(item["plugin_id"])
    else:
        svc.save_config(item["plugin_id"], item.get("config") or {})
    action_cn = {"enable": "启用", "disable": "禁用"}.get(action, "更新配置")
    return f"插件已{action_cn}"


def _apply_mediaserver(ctx: ToolContext, item: dict) -> str:
    svc = ctx.media_server_config_service
    info = svc.get_media_servers_info()
    current = (info.get("servers") or {}).get(item["name"]) or {}
    if not current:
        raise RuntimeError(f"媒体服务器不存在: {item['name']}")
    merged = dict(current.get("config") or {})
    # 合并连接字段 + 顶层启停/默认开关（enabled/is_default 属于媒体服务器配置字段）
    for k in ("enabled", "is_default"):
        if item.get(k) is not None:
            merged[k] = 1 if item[k] else 0
    merged.update({k: v for k, v in item["config"].items() if v is not None})
    result = svc.save_config({"type": item["name"], **merged})
    if not getattr(result, "success", True):
        raise RuntimeError(getattr(result, "msg", "保存失败"))
    return "媒体服务器配置已更新"


def _apply_indexer(ctx: ToolContext, item: dict) -> str:
    svc = ctx.indexer_config_service
    existing = {}
    try:
        cur = svc.get_config(item["client_id"])
        if cur:
            existing = cur.get("config") or {}
    except Exception:  # noqa: BLE001
        existing = {}
    merged = dict(existing)
    merged.update({k: v for k, v in (item.get("config") or {}).items() if v is not None})
    data = {"type": item["client_id"], "enabled": 1 if item.get("enabled", True) else 0}
    for k, v in merged.items():
        data[f"{item['client_id']}.{k}"] = v
    result = svc.save_config(data)
    if not getattr(result, "success", True):
        raise RuntimeError(getattr(result, "msg", "保存失败"))
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


HANDLERS = {
    "config_apply_manifest": config_apply_manifest,
}
