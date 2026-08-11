"""
Brush Router — FastAPI 迁移
对应原 web/controllers/brush.py，复用 app/services/brush_service.py
"""

from fastapi import APIRouter, Depends
from pydantic import BaseModel, field_validator

from api.deps import get_brush_service, require_any_permission, require_permission
from app.core.exceptions import DomainError, ServiceError
from app.infrastructure.thread import ThreadExecutor
from app.schemas.common import CommonResponse
from app.services.brush_service import BrushService
from app.utils import ExceptionUtils
from app.utils.response import fail, success

router = APIRouter()


# ---------------------------------------------------------------------------
# Request Models
# ---------------------------------------------------------------------------


class EmptyRequest(BaseModel):
    data: dict | None = None


class AddBrushTaskRequest(BaseModel):
    brushtask_id: int | None = None
    brushtask_name: str | None = None
    brushtask_site: str | None = None
    brushtask_free: str | None = None
    brushtask_rssurl: str | None = None
    brushtask_interval: int | str | None = None

    @field_validator("brushtask_interval", mode="before")
    @classmethod
    def validate_interval(cls, v):
        if v is None or v == "":
            return None
        if isinstance(v, (int, float)):
            v = int(v)
            if v < 5:
                raise ValueError("间隔时间不能小于5分钟")
            return str(v)
        if isinstance(v, str):
            if v.isdigit():
                n = int(v)
                if n < 5:
                    raise ValueError("间隔时间不能小于5分钟")
                return str(n)
            parts = v.strip().split()
            if len(parts) == 5:
                return v
            raise ValueError("cron表达式格式不正确，应为5位：[分 时 日 月 星期]")
        return v

    brushtask_downloader: str | None = None
    brushtask_totalsize: str | None = None
    brushtask_time_range: str | None = None
    brushtask_active_weekdays: str | None = None
    brushtask_download_switch: str | None = None
    brushtask_remove_switch: str | None = None
    brushtask_stop_switch: str | None = None
    brushtask_daily_delete_limit: str | None = None
    brushtask_max_seeding: str | None = None
    brushtask_hr_limit: str | None = None
    brushtask_label: str | None = None
    brushtask_savepath: str | None = None
    brushtask_transfer: int | None = None
    brushtask_state: str | None = None
    brushtask_sendmessage: int | None = None
    brushtask_rule_id: int | None = None
    brushtask_rss_rule_id: int | None = None
    brushtask_remove_rule_id: int | None = None
    brushtask_stop_rule_id: int | None = None
    brushtask_hr: str | None = None
    brushtask_torrent_size: str | None = None
    brushtask_include: str | None = None
    brushtask_exclude: str | None = None
    brushtask_category_include: str | None = None
    brushtask_category_exclude: str | None = None
    brushtask_label_include: str | None = None
    brushtask_label_exclude: str | None = None
    brushtask_dlcount: str | None = None
    brushtask_peercount: str | None = None
    brushtask_pubdate: str | None = None
    brushtask_upspeed: str | None = None
    brushtask_downspeed: str | None = None
    brushtask_exclude_subscribe: str | bool | None = None
    brushtask_mode: str | None = None
    brushtask_seedtime: str | None = None
    brushtask_hr_seedtime: str | None = None
    brushtask_seedratio: str | None = None
    brushtask_seedsize: str | None = None
    brushtask_dltime: str | None = None
    brushtask_avg_upspeed: str | None = None
    brushtask_upspeed: str | None = None
    brushtask_iatime: str | None = None
    brushtask_pending_time: str | None = None
    brushtask_freespace: str | None = None
    brushtask_freestatus: str | bool | None = None
    brushtask_alive_time: str | None = None
    brushtask_tracker_error: str | None = None
    brushtask_stopfree: int | None = None


class BrushTaskIdRequest(BaseModel):
    id: int | None = None


class UpdateBrushTaskStateRequest(BaseModel):
    state: str | None = None
    ids: list | None = None


class BrushRuleIdRequest(BaseModel):
    id: int | None = None


class SaveBrushRuleRequest(BaseModel):
    id: int | None = None
    name: str | None = None
    type: str | None = None
    json_rule: dict | None = None
    rss_rule: dict | None = None
    remove_rule: dict | None = None
    stop_rule: dict | None = None


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------


@router.post("/tasks/add", response_model=CommonResponse, summary="添加刷流任务")
def add_brushtask(
    req: AddBrushTaskRequest,
    _: None = Depends(require_permission("brush:manage")),
    svc: BrushService = Depends(get_brush_service),
):
    svc.add_or_update_task(req.model_dump())
    return success()


@router.post("/tasks/update", response_model=CommonResponse, summary="更新刷流任务")
def update_brushtask(
    req: AddBrushTaskRequest,
    _: None = Depends(require_permission("brush:manage")),
    svc: BrushService = Depends(get_brush_service),
):
    svc.add_or_update_task(req.model_dump())
    return success()


@router.post("/tasks/detail", response_model=CommonResponse, summary="获取刷流任务详情")
def brushtask_detail(
    req: BrushTaskIdRequest,
    _: None = Depends(require_any_permission("brush:view", "brush:manage")),
    svc: BrushService = Depends(get_brush_service),
):
    dto = svc.get_task(req.id)
    if not dto.task:
        return fail(data={"task": {}})
    return success(data={"task": dto.task})


@router.post("/tasks", response_model=CommonResponse, summary="获取刷流任务列表")
def list_brushtasks(
    req: EmptyRequest = EmptyRequest(),
    _: None = Depends(require_any_permission("brush:view", "brush:manage")),
    svc: BrushService = Depends(get_brush_service),
):
    return success(data=svc.get_tasks())


@router.post("/tasks/delete", response_model=CommonResponse, summary="删除刷流任务")
def del_brushtask(
    req: BrushTaskIdRequest,
    _: None = Depends(require_permission("brush:manage")),
    svc: BrushService = Depends(get_brush_service),
):
    brush_id = req.id
    if brush_id:
        svc.delete_task(brush_id)
        return success()
    return fail()


@router.post("/tasks/torrents", response_model=CommonResponse, summary="获取刷流任务种子")
def list_brushtask_torrents(
    req: BrushTaskIdRequest,
    _: None = Depends(require_any_permission("brush:view", "brush:manage")),
    svc: BrushService = Depends(get_brush_service),
):
    dto = svc.get_torrents(req.id)
    if not dto.torrents:
        return success(data={"list": []})
    return success(data={"list": dto.torrents})


@router.post("/tasks/run", response_model=CommonResponse, summary="运行刷流任务")
def run_brushtask(
    req: BrushTaskIdRequest,
    _: None = Depends(require_permission("brush:manage")),
    svc: BrushService = Depends(get_brush_service),
):
    ThreadExecutor(name="brush_run").submit(svc.run_task, req.id)
    return success()


@router.post("/tasks/state", response_model=CommonResponse, summary="更新刷流任务状态")
def update_brushtask_state(
    req: UpdateBrushTaskStateRequest,
    _: None = Depends(require_permission("brush:manage")),
    svc: BrushService = Depends(get_brush_service),
):
    try:
        svc.update_task_state(state=req.state, task_ids=req.ids)
        return success(message="")
    except (ServiceError, DomainError) as e:
        return fail(msg=e.message)
    except Exception as e:
        ExceptionUtils.exception_traceback(e)
        return fail(msg="刷流任务设置失败")


# ---------------------------------------------------------------------------
# Brush Rule Endpoints
# ---------------------------------------------------------------------------


@router.post("/rules", response_model=CommonResponse, summary="获取刷流规则")
def list_brush_rules(
    req: EmptyRequest = EmptyRequest(),
    _: None = Depends(require_any_permission("brush:view", "brush:manage")),
    svc: BrushService = Depends(get_brush_service),
):
    return success(data=svc.get_rules())


@router.post("/rules/detail", response_model=CommonResponse, summary="获取刷流规则详情")
def brush_rule_detail(
    req: BrushRuleIdRequest,
    _: None = Depends(require_any_permission("brush:view", "brush:manage")),
    svc: BrushService = Depends(get_brush_service),
):
    data = svc.get_rule(req.id or 0)
    if not data:
        return fail(msg="规则不存在")
    return success(data=data)


@router.post("/rules/save", response_model=CommonResponse, summary="保存刷流规则")
def save_brush_rule(
    req: SaveBrushRuleRequest,
    _: None = Depends(require_permission("brush:manage")),
    svc: BrushService = Depends(get_brush_service),
):
    if not req.name:
        return fail(msg="规则名称不能为空")
    if req.id:
        svc.update_rule(req.id, req.model_dump())
        return success(message="规则已更新")
    rid = svc.add_rule(req.model_dump())
    return success(data={"id": rid}, message="规则已创建")


@router.post("/rules/delete", response_model=CommonResponse, summary="删除刷流规则")
def delete_brush_rule(
    req: BrushRuleIdRequest,
    _: None = Depends(require_permission("brush:manage")),
    svc: BrushService = Depends(get_brush_service),
):
    if req.id:
        svc.delete_rule(req.id)
        return success()
    return fail(msg="规则ID不能为空")


class BrushEventRequest(BaseModel):
    task_id: int | None = None
    action: str | None = None
    page: int = 1
    page_size: int = 50


@router.post("/events", response_model=CommonResponse, summary="获取刷流事件日志")
def get_brush_events(
    req: BrushEventRequest,
    _: None = Depends(require_any_permission("brush:view", "brush:manage")),
    svc: BrushService = Depends(get_brush_service),
):
    total, rows = svc.get_events(req.task_id, req.action, req.page, req.page_size)
    return success(data={"total": total, "rows": [r.as_dict() for r in rows]})
