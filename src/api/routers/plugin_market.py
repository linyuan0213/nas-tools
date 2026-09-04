"""Plugin Market Router — FastAPI

远程插件市场：市场源管理 + catalog 同步 + 目录插件浏览（里程碑一）。
"""

from typing import Optional

from fastapi import APIRouter, Depends
from pydantic import BaseModel

from api.deps import get_plugin_market_service, require_any_permission, require_permission
from app.schemas.common import CommonResponse
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
