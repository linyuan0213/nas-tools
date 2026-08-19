"""
Site Router — FastAPI 迁移
对应原 web/controllers/site.py，复用 app/services/site_service.py
"""

from fastapi import APIRouter, Depends
from pydantic import BaseModel

from api.deps import get_indexer_service, get_site_service, require_any_permission, require_permission
from app.core.error_codes import ErrorCode
from app.core.exceptions import DomainError, ServiceError  # noqa: F401
from app.infrastructure.thread import ThreadExecutor
from app.schemas.common import CommonResponse
from app.services.indexer_service import IndexerService
from app.services.site_service import SiteService
from app.utils.response import fail, success

router = APIRouter()


# ---------------------------------------------------------------------------
# Request Models
# ---------------------------------------------------------------------------


class SiteIdRequest(BaseModel):
    id: str | None = None


class SiteBatchTestRequest(BaseModel):
    ids: list[str] = []


class SiteUrlRequest(BaseModel):
    url: str | None = None


class SiteNameRequest(BaseModel):
    name: str | None = None


class SiteDaysRequest(BaseModel):
    days: int | None = None
    end_day: str | None = None


class SiteUpdateRequest(BaseModel):
    site_id: str | None = None
    site_name: str | None = None
    site_pri: str | None = None
    site_rssurl: str | None = None
    site_signurl: str | None = None
    site_cookie: str | None = None
    site_api_key: str | None = None
    site_bearer_token: str | None = None
    site_headers: str | None = None
    site_note: str | None = None
    site_include: str | None = None
    rss_enable: bool | None = None
    brush_enable: bool | None = None
    statistic_enable: bool | None = None


class SiteCookieUaRequest(BaseModel):
    site_id: str | None = None
    site_cookie: str | None = None
    site_ua: str | None = None


class SiteFilterRequest(BaseModel):
    rss: bool | None = False
    brush: bool | None = False
    statistic: bool | None = False
    basic: bool | None = False
    source: str | None = None


class SiteCaptchaRequest(BaseModel):
    code: str | None = None
    value: str | None = None


class SiteUserStatisticsRequest(BaseModel):
    sites: list | None = None
    encoding: str | None = "RAW"
    sort_by: str | None = None
    sort_on: str | None = None
    site_hash: str | None = None


class SiteResourcesRequest(BaseModel):
    id: str | None = None
    page: int | None = None
    page_size: int | None = None
    keyword: str | None = None


class IndexerSiteConfigUpdateRequest(BaseModel):
    site_name: str
    enabled: bool | None = None
    download_setting: int | None = None
    default_settings: dict | None = None


class IndexerSiteConfigSyncRequest(BaseModel):
    client_id: str


class IndexerSiteConfigBatchRequest(BaseModel):
    sites: list[dict] | None = None


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------


@router.post("/sites/check_attr", response_model=CommonResponse, summary="检查站点属性")
def check_site_attr(
    req: SiteUrlRequest,
    user: str = Depends(require_any_permission("site:view", "site:manage")),
    svc: SiteService = Depends(get_site_service),
):
    dto = svc.check_site_attr(req.url)
    return success(data={"site_free": dto.site_free, "site_2xfree": dto.site_2xfree, "site_hr": dto.site_hr})


@router.post("/sites/delete", response_model=CommonResponse, summary="删除站点")
def del_site(
    req: SiteIdRequest,
    user: str = Depends(require_permission("site:manage")),
    svc: SiteService = Depends(get_site_service),
):
    tid = req.id
    if tid:
        ret = svc.delete_site(tid)
        if ret:
            return success()
        return fail(msg="删除失败")
    return fail(msg="站点ID不能为空")


@router.post("/sites/detail", response_model=CommonResponse, summary="获取站点详情")
def get_site(
    req: SiteIdRequest,
    user: str = Depends(require_any_permission("site:view", "site:manage")),
    svc: SiteService = Depends(get_site_service),
):
    dto = svc.get_site(req.id)
    return success(
        data={"site": dto.site, "site_free": dto.site_free, "site_2xfree": dto.site_2xfree, "site_hr": dto.site_hr}
    )


@router.post("/sites/activity", response_model=CommonResponse, summary="获取站点活跃度")
def get_site_activity(
    req: SiteNameRequest,
    user: str = Depends(require_any_permission("site:view", "site:manage")),
    svc: SiteService = Depends(get_site_service),
):
    if not req.name:
        return fail(msg="查询参数错误")
    dto = svc.get_site_activity(req.name)
    return success(data={"dataset": dto.dataset})


@router.post("/sites/favicon", response_model=CommonResponse, summary="获取站点图标")
def get_site_favicon(
    req: SiteNameRequest,
    user: str = Depends(require_any_permission("site:view", "site:manage")),
    svc: SiteService = Depends(get_site_service),
):
    return success(data=svc.get_site_favicon(req.name))


@router.post("/sites/history", response_model=CommonResponse, summary="获取站点历史数据")
def get_site_history(
    req: SiteDaysRequest,
    user: str = Depends(require_any_permission("site:view", "site:manage")),
    svc: SiteService = Depends(get_site_service),
):
    if req.days is None or not isinstance(req.days, int):
        return fail(msg="查询参数错误")
    dto = svc.get_site_history(days=req.days, end_day=req.end_day)
    return success(data={"dataset": dto.dataset})


@router.post("/sites/statistics/daily", response_model=CommonResponse, summary="获取站点日统计")
def get_site_daily_history(
    req: SiteDaysRequest,
    user: str = Depends(require_any_permission("site:view", "site:manage")),
    svc: SiteService = Depends(get_site_service),
):
    if req.days is None or not isinstance(req.days, int):
        return fail(msg="查询参数错误")
    result = svc.get_site_daily_history(days=req.days, end_day=req.end_day)
    return success(data=result)


@router.post("/sites/seeding", response_model=CommonResponse, summary="获取站点做种信息")
def get_site_seeding_info(
    req: SiteNameRequest,
    user: str = Depends(require_any_permission("site:view", "site:manage")),
    svc: SiteService = Depends(get_site_service),
):
    if not req.name:
        return fail(msg="查询参数错误")
    dto = svc.get_site_seeding_info(req.name)
    return success(data={"dataset": dto.dataset})


class SiteRefreshRequest(BaseModel):
    sites: list | None = None


@router.post("/sites/statistics/refresh", response_model=CommonResponse, summary="刷新站点统计数据")
def refresh_site_statistics(
    req: SiteRefreshRequest,
    user: str = Depends(require_any_permission("site:view", "site:manage")),
    svc: SiteService = Depends(get_site_service),
):
    ThreadExecutor(name="site_refresh").submit(svc.refresh_site_data_now, req.sites)
    return success(data={"message": "站点数据刷新已启动，请稍候"})


@router.post("/sites/definitions", response_model=CommonResponse, summary="获取所有可添加的站点定义")
def get_site_definitions(
    user: str = Depends(require_any_permission("site:view", "site:manage")),
    svc: SiteService = Depends(get_site_service),
):
    defs = svc.get_site_definitions()
    data = [
        {
            "id": d.id,
            "name": d.name,
            "domain": d.domain,
            "type": d.type,
            "public": d.public,
            "domain_aliases": d.domain_aliases,
            "encoding": d.encoding,
            "detail_page_url": d.detail_page_url,
        }
        for d in defs
    ]
    return success(data=data)


@router.post("/sites", response_model=CommonResponse, summary="获取站点列表")
def get_sites(
    req: SiteFilterRequest,
    user: str = Depends(require_any_permission("site:view", "site:manage")),
    svc: SiteService = Depends(get_site_service),
):
    sites = svc.get_sites(
        rss=bool(req.rss),
        brush=bool(req.brush),
        statistic=bool(req.statistic),
        basic=bool(req.basic),
        source=req.source,
    )
    return success(data=sites)


@router.post("/sites/captcha", response_model=CommonResponse, summary="设置站点验证码")
def set_site_captcha_code(
    req: SiteCaptchaRequest,
    user: str = Depends(require_permission("site:manage")),
    svc: SiteService = Depends(get_site_service),
):
    svc.set_captcha_code(code=req.code or "", value=req.value or "")
    return success()


@router.post("/sites/test", response_model=CommonResponse, summary="测试站点连接")
def test_site(
    req: SiteIdRequest,
    user: str = Depends(require_permission("site:manage")),
    svc: SiteService = Depends(get_site_service),
):
    dto = svc.test_site(req.id or "")
    if dto.code == 0:
        return success(message=dto.msg, time=dto.times)
    return fail(code=ErrorCode.SITE_REQUEST_FAILED, msg=dto.msg, time=dto.times)


@router.post("/sites/test_batch", response_model=CommonResponse, summary="批量测试站点连接")
def test_sites_batch(
    req: SiteBatchTestRequest,
    user: str = Depends(require_permission("site:manage")),
    svc: SiteService = Depends(get_site_service),
):
    results = svc.test_sites_batch(req.ids or [])
    return success(data=results)


@router.post("/sites/update", response_model=CommonResponse, summary="更新站点配置")
def update_site(
    req: SiteUpdateRequest,
    user: str = Depends(require_permission("site:manage")),
    svc: SiteService = Depends(get_site_service),
):
    dto = svc.update_site(req.model_dump())
    if dto.code == 0:
        return success(message=dto.msg or "")
    return fail(code=ErrorCode.OPERATION_FAILED, msg=dto.msg or "")


@router.post("/sites/cookie_ua", response_model=CommonResponse, summary="更新站点 Cookie 和 UA")
def update_site_cookie_ua(
    req: SiteCookieUaRequest,
    user: str = Depends(require_permission("site:manage")),
    svc: SiteService = Depends(get_site_service),
):
    svc.update_site_cookie_ua(siteid=req.site_id or "", cookie=req.site_cookie or "", ua=req.site_ua or "")
    return success(data={"messages": "请求发送成功"})


@router.post("/sites/statistics", response_model=CommonResponse, summary="获取站点用户统计")
def get_site_user_statistics(
    req: SiteUserStatisticsRequest,
    user: str = Depends(require_any_permission("site:view", "site:manage")),
    svc: SiteService = Depends(get_site_service),
):
    # 强制使用 DICT 编码，确保返回可序列化的字典格式
    statistics = svc.get_site_user_statistics(
        sites=req.sites, encoding="DICT", sort_by=req.sort_by, sort_on=req.sort_on, site_hash=req.site_hash
    )
    return success(data=statistics)


@router.post("/sites/resources", response_model=CommonResponse, summary="获取站点资源列表")
def list_site_resources(
    req: SiteResourcesRequest,
    user: str = Depends(require_any_permission("site:view", "site:manage")),
    svc: SiteService = Depends(get_site_service),
):
    resources = svc.list_site_resources(
        index_id=req.id or "",
        page=req.page or 0,
        page_size=req.page_size or 100,
        keyword=req.keyword or "",
    )
    if not resources.success:
        return fail(msg=resources.msg)
    return success(data=resources.data)


@router.post("/sites/indexer-config/update", response_model=CommonResponse, summary="更新第三方站点配置")
def update_indexer_site_config(
    req: IndexerSiteConfigUpdateRequest,
    user: str = Depends(require_permission("site:manage")),
    idx_svc: IndexerService = Depends(get_indexer_service),
):
    if req.enabled is not None:
        idx_svc.update_site_enabled(req.site_name, req.enabled)
    if req.download_setting is not None:
        idx_svc.update_site_download_setting(req.site_name, req.download_setting)
    if req.default_settings is not None:
        idx_svc.update_site_default_settings(req.site_name, req.default_settings)
    return success()


@router.post("/sites/indexer-config/sync", response_model=CommonResponse, summary="同步第三方索引器站点")
def sync_indexer_sites(
    req: IndexerSiteConfigSyncRequest,
    user: str = Depends(require_permission("site:manage")),
    idx_svc: IndexerService = Depends(get_indexer_service),
):
    ok = idx_svc.sync_third_party_sites(req.client_id)
    if not ok:
        return fail(msg="同步失败")
    return success()


@router.post("/sites/indexer-config/batch", response_model=CommonResponse, summary="批量更新第三方站点配置")
def batch_update_indexer_site_config(
    req: IndexerSiteConfigBatchRequest,
    user: str = Depends(require_permission("site:manage")),
    idx_svc: IndexerService = Depends(get_indexer_service),
):
    for item in req.sites or []:
        site_name = item.get("site_name")
        if not site_name:
            continue
        if "enabled" in item:
            idx_svc.update_site_enabled(site_name, bool(item.get("enabled")))
        if "download_setting" in item:
            idx_svc.update_site_download_setting(site_name, item.get("download_setting"))
        if "default_settings" in item:
            idx_svc.update_site_default_settings(site_name, item.get("default_settings"))
    return success()
