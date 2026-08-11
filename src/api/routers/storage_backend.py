"""Storage Backend Router — 存储后端配置 API"""

import json

from fastapi import APIRouter, Depends
from pydantic import BaseModel

from api.deps import get_storage_backend_service, require_any_permission, require_permission
from app.core.exceptions import DomainError, ServiceError
from app.schemas.common import CommonResponse
from app.services.storage_backend_service import StorageBackendService
from app.storage import StorageBackendFactory
from app.utils.response import fail, success

router = APIRouter()


# ---------------------------------------------------------------------------
# Request Models
# ---------------------------------------------------------------------------


class ListBackendsRequest(BaseModel):
    pass


class CreateBackendRequest(BaseModel):
    name: str
    type: str
    config: str
    enabled: int = 1


class UpdateBackendRequest(BaseModel):
    sid: int
    name: str | None = None
    type: str | None = None
    config: str | None = None
    enabled: int | None = None


class DeleteBackendRequest(BaseModel):
    sid: int


class GetBackendRequest(BaseModel):
    sid: int


class TestBackendRequest(BaseModel):
    type: str
    config: str


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------


@router.post("/list", response_model=CommonResponse, summary="获取存储后端列表")
def list_backends(
    req: ListBackendsRequest,
    user: str = Depends(require_any_permission("storage:view", "storage:manage")),
    svc: StorageBackendService = Depends(get_storage_backend_service),
):
    items = svc.list_backends()
    return success(data={"count": len(items), "items": items})


@router.post("/get", response_model=CommonResponse, summary="获取存储后端详情")
def get_backend(
    req: GetBackendRequest,
    user: str = Depends(require_any_permission("storage:view", "storage:manage")),
    svc: StorageBackendService = Depends(get_storage_backend_service),
):
    data = svc.get_backend(req.sid)
    if not data:
        return fail(msg="存储后端不存在")
    return success(data=data)


@router.post("/save", response_model=CommonResponse, summary="创建存储后端")
def create_backend(
    req: CreateBackendRequest,
    user: str = Depends(require_permission("storage:manage")),
    svc: StorageBackendService = Depends(get_storage_backend_service),
):
    sid = svc.create_backend(req.name, req.type, req.config, req.enabled)
    return success(data={"id": sid})


@router.post("/update", response_model=CommonResponse, summary="更新存储后端")
def update_backend(
    req: UpdateBackendRequest,
    user: str = Depends(require_permission("storage:manage")),
    svc: StorageBackendService = Depends(get_storage_backend_service),
):
    kwargs = {}
    if req.name is not None:
        kwargs["NAME"] = req.name
    if req.type is not None:
        kwargs["TYPE"] = req.type
    if req.config is not None:
        kwargs["CONFIG"] = req.config
    if req.enabled is not None:
        kwargs["ENABLED"] = req.enabled
    if not kwargs:
        return fail(msg="无更新内容")
    svc.update_backend(req.sid, **kwargs)
    return success()


@router.post("/delete", response_model=CommonResponse, summary="删除存储后端")
def delete_backend(
    req: DeleteBackendRequest,
    user: str = Depends(require_permission("storage:manage")),
    svc: StorageBackendService = Depends(get_storage_backend_service),
):
    svc.delete_backend(req.sid)
    return success()


@router.post("/test", response_model=CommonResponse, summary="测试存储后端连接")
def test_backend(
    req: TestBackendRequest,
    user: str = Depends(require_permission("storage:manage")),
):
    """测试存储后端连接"""
    info = StorageBackendFactory.get_config_info(req.type)
    if not info:
        return fail(msg=f"不支持的存储类型: {req.type}")
    stype, cls = info
    config = cls(id="test", name="test", type=stype, enabled=True)
    try:
        cfg_dict = json.loads(req.config) if req.config else {}
    except (ServiceError, DomainError) as e:
        return fail(msg=e.message)
    except Exception:
        return fail(msg="配置 JSON 格式错误")
    for k, v in cfg_dict.items():
        if hasattr(config, k):
            setattr(config, k, v)
    backend = StorageBackendFactory.create(config)
    ok, msg = backend.health_check()
    return success(data={"success": ok, "msg": msg}, message=msg)


@router.post("/types", response_model=CommonResponse, summary="获取存储后端类型")
def list_types(
    user: str = Depends(require_any_permission("storage:view", "storage:manage")),
):
    return success(data={"items": StorageBackendFactory.get_type_schema()})
