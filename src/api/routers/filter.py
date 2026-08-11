"""
Filter Router — FastAPI 迁移
对应原 web/controllers/filter.py，复用 app/services/filter_service.py
"""

from fastapi import APIRouter, Depends
from pydantic import BaseModel

from api.deps import get_config_service, get_filter_service, require_any_permission
from app.core.error_codes import ErrorCode
from app.core.exceptions import (
    DomainError,
    ResourceNotFoundError,
    ServiceError,
    ValidationError,
)
from app.schemas.common import CommonResponse
from app.services.filter_service import FilterService as Filter
from app.utils.response import fail, success

router = APIRouter()


def _get_script_path(config_service=Depends(get_config_service)):
    """获取脚本路径（兼容层）"""
    return config_service.get_script_path()


# ---------------------------------------------------------------------------
# Request Models
# ---------------------------------------------------------------------------


class EmptyRequest(BaseModel):
    data: dict | None = None


class AddFilterGroupRequest(BaseModel):
    name: str | None = None
    default: str | None = None


class AddFilterRuleRequest(BaseModel):
    rule_id: int | None = None
    group_id: int | None = None
    rule_name: str | None = None
    rule_pri: str | None = None
    rule_include: str | None = None
    rule_exclude: str | None = None
    rule_sizelimit: str | None = None
    rule_free: str | None = None


class IdRequest(BaseModel):
    id: int | None = None


class FilterRuleDetailRequest(BaseModel):
    groupid: int | None = None
    ruleid: int | None = None


class ImportFilterGroupRequest(BaseModel):
    content: str | None = None


class RestoreFilterGroupRequest(BaseModel):
    groupids: list[int] | None = None
    init_rulegroups: list | None = None


class RuleTestRequest(BaseModel):
    title: str | None = None
    subtitle: str | None = None
    size: str | None = None
    rulegroup: str | None = None


class SetDefaultFilterGroupRequest(BaseModel):
    id: int | None = None


class ShareFilterGroupRequest(BaseModel):
    id: int | None = None


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------


@router.post("/groups/add", response_model=CommonResponse, summary="添加过滤规则组")
def add_filtergroup(
    req: AddFilterGroupRequest,
    user: str = Depends(require_any_permission("setting:view", "setting:update")),
    filter_service: Filter = Depends(get_filter_service),
):
    name = req.name
    if not name:
        return fail(code=ErrorCode.PARAM_VALIDATION_FAILED)
    filter_service.add_group(name, req.default or "N")
    return success()


@router.post("/rules/add", response_model=CommonResponse, summary="添加过滤规则")
def add_filterrule(
    req: AddFilterRuleRequest,
    user: str = Depends(require_any_permission("setting:view", "setting:update")),
    filter_service: Filter = Depends(get_filter_service),
):
    item = {
        "group": req.group_id,
        "name": req.rule_name,
        "pri": req.rule_pri,
        "include": req.rule_include,
        "exclude": req.rule_exclude,
        "size": req.rule_sizelimit,
        "free": req.rule_free,
    }
    filter_service.add_filter_rule(ruleid=req.rule_id, item=item)
    return success()


@router.post("/groups/delete", response_model=CommonResponse, summary="删除过滤规则组")
def del_filtergroup(
    req: IdRequest,
    user: str = Depends(require_any_permission("setting:view", "setting:update")),
    filter_service: Filter = Depends(get_filter_service),
):
    filter_service.delete_filtergroup(req.id)
    return success()


@router.post("/rules/delete", response_model=CommonResponse, summary="删除过滤规则")
def del_filterrule(
    req: IdRequest,
    user: str = Depends(require_any_permission("setting:view", "setting:update")),
    filter_service: Filter = Depends(get_filter_service),
):
    filter_service.delete_filterrule(req.id)
    return success()


@router.post("/rules/detail", response_model=CommonResponse, summary="获取过滤规则详情")
def filterrule_detail(
    req: FilterRuleDetailRequest,
    user: str = Depends(require_any_permission("setting:view", "setting:update")),
    filter_service: Filter = Depends(get_filter_service),
):
    ruleinfo = filter_service.get_rule_detail(groupid=req.groupid, ruleid=req.ruleid)
    return success(data=ruleinfo)


@router.post("/groups/import", response_model=CommonResponse, summary="导入过滤规则组")
def import_filtergroup(
    req: ImportFilterGroupRequest,
    user: str = Depends(require_any_permission("setting:view", "setting:update")),
    filter_service: Filter = Depends(get_filter_service),
):
    try:
        filter_service.import_filter_group(req.content or "")
        return success()
    except (ValidationError, ResourceNotFoundError) as e:
        return fail(msg=e.message)
    except (ServiceError, DomainError) as e:
        return fail(msg=e.message)


@router.post("/groups/restore", response_model=CommonResponse, summary="恢复过滤规则组")
def restore_filtergroup(
    req: RestoreFilterGroupRequest,
    user: str = Depends(require_any_permission("setting:view", "setting:update")),
    filter_service: Filter = Depends(get_filter_service),
):
    filter_service.restore_filter_group(groupids=req.groupids or [], init_rulegroups=req.init_rulegroups or [])
    return success()


@router.post("/rules/test", response_model=CommonResponse, summary="测试过滤规则")
def rule_test(
    req: RuleTestRequest,
    user: str = Depends(require_any_permission("setting:view", "setting:update")),
    filter_service: Filter = Depends(get_filter_service),
):
    title = req.title
    if not title:
        return fail(code=ErrorCode.PARAM_VALIDATION_FAILED)
    match_flag, text, order = filter_service.test_rule(
        title=title, subtitle=req.subtitle, size=req.size, rulegroup=req.rulegroup
    )
    return success(data={"flag": match_flag, "text": text, "order": order})


@router.post("/groups/default", response_model=CommonResponse, summary="设置默认过滤规则组")
def set_default_filtergroup(
    req: SetDefaultFilterGroupRequest,
    user: str = Depends(require_any_permission("setting:view", "setting:update")),
    filter_service: Filter = Depends(get_filter_service),
):
    groupid = req.id
    if not groupid:
        return fail(code=ErrorCode.PARAM_VALIDATION_FAILED)
    filter_service.set_default_filtergroup(groupid)
    return success()


@router.post("/groups/share", response_model=CommonResponse, summary="分享过滤规则组")
def share_filtergroup(
    req: ShareFilterGroupRequest,
    user: str = Depends(require_any_permission("setting:view", "setting:update")),
    filter_service: Filter = Depends(get_filter_service),
):
    try:
        json_string = filter_service.share_filter_group(req.id)
        return success(data=json_string)
    except (ValidationError, ResourceNotFoundError) as e:
        return fail(msg=e.message)
    except (ServiceError, DomainError) as e:
        return fail(msg=e.message)


@router.post("/rules", response_model=CommonResponse, summary="获取过滤规则")
def get_filterrules(
    req: EmptyRequest = EmptyRequest(),
    user: str = Depends(require_any_permission("setting:view", "setting:update")),
    filter_service: Filter = Depends(get_filter_service),
    script_path: str = Depends(_get_script_path),
):
    rule_groups, _init_rule_groups = filter_service.get_filterrules(script_path)
    return success(data=rule_groups)
