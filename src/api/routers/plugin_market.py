"""Plugin Market Router — FastAPI

远程插件市场：市场源管理 + catalog 同步 + 目录插件浏览（里程碑一）。
"""

from typing import Optional

from fastapi import APIRouter, Depends
from pydantic import BaseModel

from api.deps import (
    get_plugin_framework_service,
    get_plugin_market_service,
    require_any_permission,
    require_permission,
)
from app.schemas.common import CommonResponse
from app.services.plugin_framework_service import PluginFrameworkService
from app.services.plugin_market_service import PluginMarketService
from app.utils.response import fail, success

router = APIRouter()


class MarketSourceAddRequest(BaseModel):
    name: str
    url: str
    public_key: str = ""


class MarketSourceUpdateRequest(BaseModel):
    name: Optional[str] = None
    url: Optional[str] = None
    public_key: Optional[str] = None
    enabled: Optional[bool] = None
    auto_update: Optional[bool] = None


@router.get("/sources", response_model=CommonResponse, summary="市场源列表")
def list_sources(
    _: str = Depends(require_any_permission("plugin:view", "plugin:manage")),
    svc: PluginMarketService = Depends(get_plugin_market_service),
):
    """列出已配置的插件市场源"""
    return success(data={"total": len(svc.list_sources()), "items": svc.list_sources()})


@router.post("/sources", response_model=CommonResponse, summary="添加市场源")
def add_source(
    req: MarketSourceAddRequest,
    _: str = Depends(require_permission("plugin:manage")),
    svc: PluginMarketService = Depends(get_plugin_market_service),
):
    """添加市场源（URL 需公网 http(s)）"""
    try:
        source = svc.add_source(name=req.name, url=req.url, public_key=req.public_key)
    except ValueError as e:
        return fail(msg=str(e))
    return success(data=source)


@router.put("/sources/{source_id}", response_model=CommonResponse, summary="编辑市场源")
def update_source(
    source_id: str,
    req: MarketSourceUpdateRequest,
    _: str = Depends(require_permission("plugin:manage")),
    svc: PluginMarketService = Depends(get_plugin_market_service),
):
    """编辑市场源（启停/自动更新/签名公钥/URL）"""
    try:
        fields = {k: v for k, v in req.model_dump().items() if v is not None}
        source = svc.update_source(source_id, **fields)
    except ValueError as e:
        return fail(msg=str(e))
    return success(data=source)


@router.delete("/sources/{source_id}", response_model=CommonResponse, summary="移除市场源")
def delete_source(
    source_id: str,
    _: str = Depends(require_permission("plugin:manage")),
    svc: PluginMarketService = Depends(get_plugin_market_service),
):
    """移除市场源"""
    if not svc.delete_source(source_id):
        return fail(msg=f"市场源不存在: {source_id}")
    return success(data={"deleted": True})


@router.post("/sources/{source_id}/sync", response_model=CommonResponse, summary="立即同步市场源")
def sync_source(
    source_id: str,
    _: str = Depends(require_any_permission("plugin:view", "plugin:manage")),
    svc: PluginMarketService = Depends(get_plugin_market_service),
):
    """拉取目录索引 catalog.json 并缓存"""
    try:
        result = svc.sync_source(source_id)
    except ValueError as e:
        return fail(msg=str(e))
    return success(data=result)


@router.get("/plugins", response_model=CommonResponse, summary="浏览市场插件目录")
def list_plugins(
    source_id: str,
    keyword: str = "",
    _: str = Depends(require_any_permission("plugin:view", "plugin:manage")),
    svc: PluginMarketService = Depends(get_plugin_market_service),
):
    """按源列出已同步目录中的插件（来自 catalog 缓存，需先 sync）"""
    items = svc.list_catalog_plugins(source_id, keyword=keyword)
    return success(data={"total": len(items), "items": items})


@router.get("/plugins/{plugin_id}/audit", response_model=CommonResponse, summary="插件包预检（SAST）")
def audit_plugin(
    plugin_id: str,
    source_id: str,
    _: str = Depends(require_any_permission("plugin:view", "plugin:manage")),
    svc: PluginMarketService = Depends(get_plugin_market_service),
):
    """下载插件包做 sha256 + 静态扫描（不落盘/不启用），返回扫描报告"""
    try:
        result = svc.audit_plugin(source_id, plugin_id)
    except ValueError as e:
        return fail(msg=str(e))
    return success(data=result)


@router.get("/plugins/{plugin_id}", response_model=CommonResponse, summary="插件详情（懒加载）")
def get_plugin_detail(
    plugin_id: str,
    source_id: str,
    _: str = Depends(require_any_permission("plugin:view", "plugin:manage")),
    svc: PluginMarketService = Depends(get_plugin_market_service),
):
    """按需拉取 plugins/<id>.json（同源限制 + id 一致性校验，含本地缓存）"""
    try:
        detail = svc.get_plugin_detail(source_id, plugin_id)
    except ValueError as e:
        return fail(msg=str(e))
    return success(data=detail)


@router.get("/status", response_model=CommonResponse, summary="已装插件 vs 市场版本状态")
def plugin_status(
    source_id: str,
    _: str = Depends(require_any_permission("plugin:view", "plugin:manage")),
    market: PluginMarketService = Depends(get_plugin_market_service),
    framework: PluginFrameworkService = Depends(get_plugin_framework_service),
):
    """对指定源目录与本地已装插件做版本对比：installed_current / update_available / downgrade"""
    catalog = market.get_catalog(source_id)
    if not catalog:
        return fail(msg="目录未同步，请先同步市场源")
    installed = {p.get("id"): p for p in (framework.list_plugins() or []) if p.get("id")}
    wanted: list[str] = []
    for p in catalog.plugins:
        pid = p.get("id")
        if isinstance(pid, str) and pid in installed:
            wanted.append(pid)
    details = market.list_plugin_details(source_id, wanted)
    items = []
    for pid, detail in details.items():
        local_ver = str(installed[pid].get("version") or "")
        remote_ver = str(detail.get("version") or "")
        if local_ver and remote_ver:
            cmp_val = PluginMarketService.compare_versions(local_ver, remote_ver)
            state = "installed_current" if cmp_val == 0 else ("update_available" if cmp_val < 0 else "downgrade")
        else:
            state = "update_available" if remote_ver else "unknown"
        items.append(
            {
                "plugin_id": pid,
                "source_id": source_id,
                "installed_version": local_ver,
                "remote_version": remote_ver,
                "state": state,
                "min_app_version": detail.get("min_app_version", ""),
                "channel": detail.get("channel", "stable"),
            }
        )
    return success(data={"total": len(items), "items": items})
