"""刮削（NFO/图片）配置工具 handler"""

import json

from app.agent.tools.base import ToolResult
from app.agent.tools.context import ToolContext
from app.domain.enums import SystemConfigKey

_SECRET_HINTS = ("apikey", "api_key", "token", "password", "secret")


def scraper_config_get(ctx: ToolContext) -> ToolResult:
    """读取刮削配置（nfo/pic 等各节），密钥类已脱敏"""
    svc = ctx.system_config_service
    if not svc:
        return ToolResult(success=False, error="系统配置服务不可用")
    try:
        raw = svc.get(SystemConfigKey.UserScraperConf)
    except Exception as e:  # noqa: BLE001
        return ToolResult(success=False, error=f"读取刮削配置失败: {e}")
    cfg = _parse(raw)
    return ToolResult(success=True, data=_mask(cfg))


def scraper_config_save(ctx: ToolContext, config: dict, confirmed: bool = False) -> ToolResult:
    """整体保存刮削配置（scraper_nfo / scraper_pic 等节），需确认。"""
    svc = ctx.system_config_service
    if not svc:
        return ToolResult(success=False, error="系统配置服务不可用")
    if not isinstance(config, dict) or not config:
        return ToolResult(success=False, error="config 必须是非空对象（包含 scraper_nfo/scraper_pic 等节）")
    if not confirmed:
        return ToolResult(
            success=True,
            need_confirm=True,
            data={
                "action": "scraper_save",
                "message": "整体覆盖刮削配置需确认，将写入节: " + ", ".join(config.keys()),
            },
        )
    try:
        svc.set(SystemConfigKey.UserScraperConf, config)
    except Exception as e:  # noqa: BLE001
        return ToolResult(success=False, error=f"保存刮削配置失败: {e}")
    return ToolResult(success=True, data={"message": "刮削配置已保存"})


def _parse(raw):
    if raw is None:
        return {}
    if isinstance(raw, dict):
        return raw
    if isinstance(raw, str):
        try:
            data = json.loads(raw)
            return data if isinstance(data, dict) else {}
        except (ValueError, TypeError):
            return {}
    return {}


def _mask(cfg: dict) -> dict:
    out = {}
    for k, v in cfg.items():
        if isinstance(v, dict):
            out[k] = _mask(v)
        else:
            out[k] = "***" if v and _is_secret(k) else v
    return out


def _is_secret(key: str) -> bool:
    low = key.lower()
    return any(h in low for h in _SECRET_HINTS)
