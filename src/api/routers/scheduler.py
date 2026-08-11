"""
Scheduler Router — FastAPI 迁移
对应原 web/controllers/scheduler.py，复用 app/services/scheduler_service.py
"""

from fastapi import APIRouter, Depends
from pydantic import BaseModel

from api.deps import get_scheduler_service, require_any_permission, require_permission
from app.core.error_codes import ErrorCode
from app.schemas.common import CommonResponse
from app.schemas.scheduler import (
    DeleteSchedulerJobRequest,
    PauseSchedulerJobRequest,
    ResumeSchedulerJobRequest,
    RunSchedulerJobRequest,
    UpdateSchedulerJobRequest,
)
from app.services.scheduler_service import SchedulerService
from app.utils.response import fail, success

router = APIRouter()


# ---------------------------------------------------------------------------
# Request Models (兼容前端原始字段名)
# ---------------------------------------------------------------------------


class EmptyRequest(BaseModel):
    data: dict | None = None


class JobIdRequest(BaseModel):
    id: str | None = None


class UpdateJobRequest(BaseModel):
    id: str | None = None
    trigger: str | None = None
    seconds: int | None = None
    minutes: int | None = None
    hours: int | None = None
    cron: str | None = None
    run_date: str | None = None


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------


@router.post("/jobs/delete", response_model=CommonResponse, summary="删除定时任务")
def delete_scheduler_job(
    req: JobIdRequest,
    _: None = Depends(require_permission("service:manage")),
    svc: SchedulerService = Depends(get_scheduler_service),
):
    job_id = req.id or ""
    if not job_id:
        return fail(msg="任务ID不能为空")
    resp = svc.delete_job(DeleteSchedulerJobRequest(id=job_id))
    if resp.code == 0:
        return success(message=resp.msg)
    return fail(msg=resp.msg)


@router.post("/jobs", response_model=CommonResponse, summary="获取定时任务列表")
def get_scheduler_jobs(
    req: EmptyRequest = EmptyRequest(),
    _: None = Depends(require_any_permission("service:view", "service:manage")),
    svc: SchedulerService = Depends(get_scheduler_service),
):
    resp = svc.get_jobs()
    if resp.code != 0:
        return fail(msg="调度器未启动")
    return success(data=[job.model_dump() for job in resp.data])


@router.post("/jobs/pause", response_model=CommonResponse, summary="暂停定时任务")
def pause_scheduler_job(
    req: JobIdRequest,
    _: None = Depends(require_permission("service:manage")),
    svc: SchedulerService = Depends(get_scheduler_service),
):
    job_id = req.id or ""
    if not job_id:
        return fail(msg="任务ID不能为空")
    resp = svc.pause_job(PauseSchedulerJobRequest(id=job_id))
    if resp.code == 0:
        return success(message=resp.msg)
    return fail(msg=resp.msg)


@router.post("/jobs/resume", response_model=CommonResponse, summary="恢复定时任务")
def resume_scheduler_job(
    req: JobIdRequest,
    _: None = Depends(require_permission("service:manage")),
    svc: SchedulerService = Depends(get_scheduler_service),
):
    job_id = req.id or ""
    if not job_id:
        return fail(msg="任务ID不能为空")
    resp = svc.resume_job(ResumeSchedulerJobRequest(id=job_id))
    if resp.code == 0:
        return success(message=resp.msg)
    return fail(msg=resp.msg)


@router.post("/jobs/run", response_model=CommonResponse, summary="立即执行定时任务")
def run_scheduler_job(
    req: JobIdRequest,
    _: None = Depends(require_permission("service:manage")),
    svc: SchedulerService = Depends(get_scheduler_service),
):
    job_id = req.id or ""
    if not job_id:
        return fail(msg="任务ID不能为空")
    resp = svc.run_job(RunSchedulerJobRequest(id=job_id))
    if resp.code == 0:
        return success(message=resp.msg)
    return fail(msg=resp.msg)


@router.post("/jobs/update", response_model=CommonResponse, summary="更新定时任务")
def update_scheduler_job(
    req: UpdateJobRequest,
    _: None = Depends(require_permission("service:manage")),
    svc: SchedulerService = Depends(get_scheduler_service),
):
    job_id = req.id or ""
    if not job_id:
        return fail(msg="任务ID不能为空")
    try:
        dto = UpdateSchedulerJobRequest(
            id=job_id,
            trigger=req.trigger or "",
            seconds=req.seconds,
            minutes=req.minutes,
            hours=req.hours,
            cron=req.cron,
            run_date=req.run_date,
        )
    except Exception as e:
        return fail(code=ErrorCode.SCHEDULER_ERROR, msg=str(e))
    resp = svc.update_job(dto)
    if resp.code == 0:
        return success(message=resp.msg)
    return fail(msg=resp.msg)
