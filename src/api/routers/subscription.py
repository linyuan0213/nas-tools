"""
Subscription Router — FastAPI 迁移
对应原 web/controllers/rss.py，调用 subscribe/ 领域服务
"""

from fastapi import APIRouter, Depends, Request, Response
from pydantic import BaseModel

from api.deps import (
    get_apikey_service,
    get_current_user,
    get_subscribe_calendar_service,
    get_subscribe_history_service,
    get_subscribe_service,
    get_subscription_monitor,
    get_system_config_service,
    require_any_permission,
    require_permission,
)
from app.core.error_codes import ErrorCode
from app.core.system_config import SystemConfig
from app.domain.enums import SystemConfigKey
from app.domain.mediatypes import MediaType
from app.media import meta_info
from app.schemas.auth import UserContext
from app.schemas.common import CommonResponse
from app.services.apikey_service import APIKeyService
from app.services.subscribe.management.calendar_service import SubscribeCalendarService
from app.services.subscribe.management.history_service import SubscribeHistoryService
from app.services.subscribe.management.service import SubscribeService
from app.services.subscribe.monitor import SubscriptionMonitor
from app.utils.response import fail, success

router = APIRouter()


# ---------------------------------------------------------------------------
# Request Models
# ---------------------------------------------------------------------------


class EmptyRequest(BaseModel):
    data: dict | None = None


class AddRssMediaRequest(BaseModel):
    name: str | None = None
    year: str | None = None
    season: str | None = None
    type: str | None = None
    page: str | None = None
    rssid: int | None = None
    in_form: str | None = None
    keyword: str | None = None
    fuzzy_match: bool | None = None
    mediaid: str | int | None = None
    rss_sites: list | None = None
    search_sites: list | None = None
    over_edition: bool | None = None
    filter_restype: str | None = None
    filter_pix: str | None = None
    filter_team: str | None = None
    filter_rule: str | None = None
    filter_include: str | None = None
    filter_exclude: str | None = None
    filter_free: bool | None = None
    save_path: str | None = None
    download_setting: str | None = None
    total_ep: int | None = None
    current_ep: int | None = None
    image: str | None = None
    tmdbid: str | int | None = None


class SubscribeIdRequest(BaseModel):
    rssid: int | None = None


class RedoHistoryRequest(BaseModel):
    rssid: int | None = None
    type: str | None = None


class RefreshRssRequest(BaseModel):
    type: str | None = None
    rssid: int | None = None
    page: str | None = None


class RemoveRssMediaRequest(BaseModel):
    name: str | None = None
    type: str | None = None
    year: str | None = None
    season: str | None = None
    rssid: int | None = None
    tmdbid: str | int | None = None
    page: str | None = None


class SubscribeDetailRequest(BaseModel):
    rssid: int | None = None
    rsstype: str | None = None


class SubscribeSeasonsRequest(BaseModel):
    tmdbid: str | int | None = None
    name: str | None = None
    year: str | None = None


class GetDefaultSubscribeSettingRequest(BaseModel):
    mtype: str | None = None


class DefaultSubscribeSettingSaveRequest(BaseModel):
    mtype: str | None = None
    over_edition: str | None = None
    restype: str | None = None
    pix: str | None = None
    team: str | None = None
    rule: str | None = None
    include: str | None = None
    exclude: str | None = None
    free: bool | None = None
    download_setting: str | None = None
    rss_sites: list | None = None
    search_sites: list | None = None


class GetSubscribeHistoryRequest(BaseModel):
    type: str | None = None


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _build_add_kwargs(req: AddRssMediaRequest) -> dict:
    mtype = MediaType.MOVIE if MediaType.from_string(req.type or "") == MediaType.MOVIE else MediaType.TV
    channel = "R" if req.in_form == "manual" else "D"
    return {
        "mtype": mtype,
        "name": req.name,
        "year": req.year,
        "channel": channel,
        "keyword": req.keyword,
        "fuzzy_match": req.fuzzy_match,
        "mediaid": req.mediaid,
        "rss_sites": req.rss_sites,
        "search_sites": req.search_sites,
        "over_edition": req.over_edition,
        "filter_restype": req.filter_restype,
        "filter_pix": req.filter_pix,
        "filter_team": req.filter_team,
        "filter_rule": req.filter_rule,
        "filter_include": req.filter_include,
        "filter_exclude": req.filter_exclude,
        "filter_free": req.filter_free,
        "save_path": req.save_path,
        "download_setting": req.download_setting,
    }


def _build_update_kwargs(req: AddRssMediaRequest) -> dict:
    mtype = MediaType.MOVIE if MediaType.from_string(req.type or "") == MediaType.MOVIE else MediaType.TV
    return {
        "mtype": mtype,
        "rssid": req.rssid,
        "name": req.name,
        "year": req.year,
        "keyword": req.keyword,
        "fuzzy_match": req.fuzzy_match,
        "mediaid": req.mediaid,
        "rss_sites": req.rss_sites,
        "search_sites": req.search_sites,
        "over_edition": req.over_edition,
        "filter_restype": req.filter_restype,
        "filter_pix": req.filter_pix,
        "filter_team": req.filter_team,
        "filter_rule": req.filter_rule,
        "filter_include": req.filter_include,
        "filter_exclude": req.filter_exclude,
        "filter_free": req.filter_free,
        "save_path": req.save_path,
        "download_setting": req.download_setting,
        "image": req.image,
    }


def _normalize_season(season) -> str | None:
    """将季号统一为数据库存储格式 "S01"。

    前端传入的季号为纯数字（如 "1"、2），而数据库 SEASON 字段存储为 "S01"。
    """
    if season is None:
        return None
    s = str(season).strip()
    if not s:
        return None
    if s.upper().startswith("S"):
        return s.upper()
    if s.isdigit():
        return f"S{int(s):02d}"
    return s


def _invoke_for_seasons(
    season,
    kwargs: dict,
    invoke,
    total_ep=None,
    current_ep=None,
):
    """按季列表或单季调用 subscribe 方法，返回 (code, msg, media_info)."""
    code = 0
    msg = ""
    media_info = None
    if isinstance(season, list):
        for sea in season:
            kwargs["season"] = sea
            kwargs.pop("total_ep", None)
            kwargs.pop("current_ep", None)
            code, msg, media_info = invoke(**kwargs)
            if code != 0:
                break
    else:
        kwargs["season"] = season
        if total_ep is not None:
            kwargs["total_ep"] = total_ep
        if current_ep is not None:
            kwargs["current_ep"] = current_ep
        code, msg, media_info = invoke(**kwargs)
    return code, msg, media_info


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------


@router.post("/add", response_model=CommonResponse, summary="添加 RSS 订阅")
def add_rss_media(
    req: AddRssMediaRequest,
    user: str = Depends(require_any_permission("subscription:manage", "subscription:view")),
    svc: SubscribeService = Depends(get_subscribe_service),
):
    kwargs = _build_add_kwargs(req)
    code, msg, media_info = _invoke_for_seasons(req.season, kwargs, svc.add_rss_subscribe)

    # code 0=成功, 9=订阅已存在(幂等)；其余为真实失败，需上报而非伪装成功
    if code not in (0, 9):
        return fail(
            code=ErrorCode.SUBSCRIPTION_FAILED,
            msg=msg,
            page=req.page,
            name=req.name,
            rssid=None,
        )

    rssid = None
    if media_info:
        rssid = svc.get_subscribe_id(mtype=kwargs["mtype"], title=req.name or "", tmdbid=media_info.tmdb_id)

    return success(
        data={
            "msg": msg,
            "page": req.page,
            "name": req.name,
            "rssid": rssid,
        }
    )


@router.post("/update", response_model=CommonResponse, summary="更新 RSS 订阅")
def update_rss_media(
    req: AddRssMediaRequest,
    user: str = Depends(require_permission("subscription:manage")),
    svc: SubscribeService = Depends(get_subscribe_service),
):
    kwargs = _build_update_kwargs(req)
    if not req.rssid:
        return fail(code=ErrorCode.PARAM_VALIDATION_FAILED, msg="缺少订阅ID", page=req.page, name=req.name, rssid=None)

    code, msg, media_info = _invoke_for_seasons(
        req.season, kwargs, svc.update_rss_subscribe, req.total_ep, req.current_ep
    )

    if code == 0:
        return success(data={"page": req.page, "name": req.name, "rssid": req.rssid})
    return fail(
        code=ErrorCode.SUBSCRIPTION_FAILED,
        msg=msg,
        page=req.page,
        name=req.name,
        rssid=req.rssid,
    )


@router.post("/history/delete", response_model=CommonResponse, summary="删除 RSS 历史")
def delete_rss_history(
    req: SubscribeIdRequest,
    user: str = Depends(require_permission("subscription:manage")),
    svc: SubscribeHistoryService = Depends(get_subscribe_history_service),
):
    svc.delete(rssid=req.rssid)
    return success()


@router.post("/history/redo", response_model=CommonResponse, summary="重新执行 RSS 历史")
def re_rss_history(
    req: RedoHistoryRequest,
    user: str = Depends(require_permission("subscription:manage")),
    svc: SubscribeHistoryService = Depends(get_subscribe_history_service),
):
    parsed = MediaType.from_string(req.type or "")
    rtype = MediaType.MOVIE.value if parsed == MediaType.MOVIE else MediaType.TV.value
    code, msg = svc.redo(rssid=req.rssid, rtype=rtype)
    if code == 0:
        return success(message=msg)
    return fail(code=ErrorCode.SUBSCRIPTION_FAILED, msg=msg)


@router.post("/refresh", response_model=CommonResponse, summary="刷新 RSS 订阅")
def refresh_rss(
    req: RefreshRssRequest,
    user: str = Depends(require_permission("subscription:manage")),
    monitor: SubscriptionMonitor = Depends(get_subscription_monitor),
):
    monitor.refresh_subscription(mtype=req.type or "", rssid=req.rssid)
    return success(data=req.page)


@router.post("/remove", response_model=CommonResponse, summary="移除 RSS 订阅")
def remove_rss_media(
    req: RemoveRssMediaRequest,
    user: str = Depends(require_any_permission("subscription:manage", "subscription:view")),
    svc: SubscribeService = Depends(get_subscribe_service),
):
    tmdbid = req.tmdbid
    if not str(tmdbid).isdigit():
        tmdbid = None
    name = req.name
    if name:
        name = meta_info(title=name).get_name()
    rssid = req.rssid
    mtype = MediaType.from_string(req.type or "")
    if mtype == MediaType.MOVIE:
        svc.delete_subscribe(
            mtype=MediaType.MOVIE,
            title=name or "",
            year=req.year,
            rssid=rssid,
            tmdbid=tmdbid,
        )
    elif mtype == MediaType.TV:
        svc.delete_subscribe(
            mtype=MediaType.TV,
            title=name or "",
            season=_normalize_season(req.season),
            rssid=rssid,
            tmdbid=tmdbid,
        )
    elif rssid:
        # 前端简化接口只传了 rssid 时，尝试两边都删除
        svc.delete_subscribe(
            mtype=MediaType.MOVIE,
            rssid=rssid,
        )
        svc.delete_subscribe(
            mtype=MediaType.TV,
            rssid=rssid,
        )
    return success(data=req.page)


@router.post("/detail", response_model=CommonResponse, summary="获取 RSS 订阅详情")
def rss_detail(
    req: SubscribeDetailRequest,
    user: str = Depends(require_any_permission("subscription:view", "subscription:manage")),
    svc: SubscribeService = Depends(get_subscribe_service),
):
    parsed = MediaType.from_string(req.rsstype or "")
    if parsed == MediaType.MOVIE:
        rssdetail = svc.get_subscribe_movies(rid=req.rssid)
        mtype_value = MediaType.MOVIE.value
    else:
        rssdetail = svc.get_subscribe_tvs(rid=req.rssid)
        mtype_value = MediaType.ANIME.value if parsed == MediaType.ANIME else MediaType.TV.value
    if not rssdetail:
        return fail()
    detail = list(rssdetail.values())[0]
    detail["type"] = mtype_value
    return success(data=detail)


@router.post("/default_setting", response_model=CommonResponse, summary="获取默认 RSS 设置")
def get_default_rss_setting(
    req: GetDefaultSubscribeSettingRequest,
    user: str = Depends(require_any_permission("subscription:view", "subscription:manage")),
    svc: SubscribeService = Depends(get_subscribe_service),
):
    parsed = MediaType.from_string(req.mtype or "")
    if parsed in (MediaType.TV, MediaType.ANIME):
        setting = svc.default_subscribe_setting_tv
    elif parsed == MediaType.MOVIE:
        setting = svc.default_subscribe_setting_mov
    else:
        setting = {}
    if setting:
        return success(data=setting)
    return success(data={})


@router.post("/default_setting/save", response_model=CommonResponse, summary="保存默认 RSS 设置")
def save_default_rss_setting(
    req: DefaultSubscribeSettingSaveRequest,
    user: str = Depends(require_permission("subscription:manage")),
    cfg: SystemConfig = Depends(get_system_config_service),
):
    mtype = req.mtype
    data = req.model_dump()
    data.pop("mtype", None)
    parsed = MediaType.from_string(mtype or "")
    if parsed == MediaType.TV:
        cfg.set(key=SystemConfigKey.DefaultSubscribeSettingTV, value=data)
    elif parsed == MediaType.MOVIE:
        cfg.set(key=SystemConfigKey.DefaultSubscribeSettingMOV, value=data)
    return success()


@router.post("/calendar/ical", response_model=CommonResponse, summary="获取 RSS 日历事件")
def get_ical_events(
    req: EmptyRequest = EmptyRequest(),
    user: str = Depends(require_any_permission("subscription:view", "subscription:manage")),
    svc: SubscribeCalendarService = Depends(get_subscribe_calendar_service),
):
    events = svc.get_events()
    return success(data=events)


@router.post("/calendar/ical/download", summary="下载订阅日历 ICS 文件")
def download_ical(
    user: str = Depends(require_any_permission("subscription:view", "subscription:manage")),
    svc: SubscribeCalendarService = Depends(get_subscribe_calendar_service),
):
    ics = svc.generate_ics()
    return success(data=ics)


@router.get("/calendar/ical/webcal", summary="Webcal 订阅订阅日历")
def webcal_ical(
    request: Request,
    user: UserContext = Depends(get_current_user),
    svc: SubscribeCalendarService = Depends(get_subscribe_calendar_service),
):
    ics = svc.generate_ics()
    return Response(
        content=ics,
        media_type="text/calendar; charset=utf-8",
    )


@router.get("/calendar/webcal_url", response_model=CommonResponse, summary="获取订阅日历 Webcal URL")
def get_webcal_url(
    request: Request,
    user: UserContext = Depends(get_current_user),
    apikey_service: APIKeyService = Depends(get_apikey_service),
):
    token = apikey_service.get_or_create_system_key("CalendarSubscription")
    return success(data={"token": token})


@router.post("/movie/items", response_model=CommonResponse, summary="获取电影 RSS 订阅项")
def get_movie_rss_items(
    req: EmptyRequest = EmptyRequest(),
    user: str = Depends(require_any_permission("subscription:view", "subscription:manage")),
    svc: SubscribeCalendarService = Depends(get_subscribe_calendar_service),
):
    return success(data=svc.get_movie_items())


@router.post("/movie/list", response_model=CommonResponse, summary="获取电影 RSS 订阅列表")
def get_movie_rss_list(
    req: EmptyRequest = EmptyRequest(),
    user: str = Depends(require_any_permission("subscription:view", "subscription:manage")),
    svc: SubscribeService = Depends(get_subscribe_service),
):
    result = svc.get_subscribe_movies()
    return success(data=list(result.values()) if isinstance(result, dict) else result)


@router.post("/history", response_model=CommonResponse, summary="获取 RSS 历史")
def get_rss_history(
    req: GetSubscribeHistoryRequest,
    user: str = Depends(require_any_permission("subscription:view", "subscription:manage")),
    svc: SubscribeHistoryService = Depends(get_subscribe_history_service),
):
    parsed = MediaType.from_string(req.type or "")
    mtype = MediaType.MOVIE.value if parsed == MediaType.MOVIE else MediaType.TV.value
    return success(data=svc.get_history(mtype=mtype))


@router.post("/tv/items", response_model=CommonResponse, summary="获取电视剧 RSS 订阅项")
def get_tv_rss_items(
    req: EmptyRequest = EmptyRequest(),
    user: str = Depends(require_any_permission("subscription:view", "subscription:manage")),
    svc: SubscribeCalendarService = Depends(get_subscribe_calendar_service),
):
    return success(data=svc.get_tv_items())


@router.post("/tv/list", response_model=CommonResponse, summary="获取电视剧 RSS 订阅列表")
def get_tv_rss_list(
    req: EmptyRequest = EmptyRequest(),
    user: str = Depends(require_any_permission("subscription:view", "subscription:manage")),
    svc: SubscribeService = Depends(get_subscribe_service),
):
    result = svc.get_subscribe_tvs()
    return success(data=list(result.values()) if isinstance(result, dict) else result)


@router.post("/tv/seasons", response_model=CommonResponse, summary="获取电视剧已订阅季列表")
def get_tv_subscribed_seasons(
    req: SubscribeSeasonsRequest,
    user: str = Depends(require_any_permission("subscription:view", "subscription:manage")),
    svc: SubscribeService = Depends(get_subscribe_service),
):
    seasons = svc.get_subscribe_seasons(
        tmdbid=str(req.tmdbid) if req.tmdbid is not None else None,
        title=req.name,
        year=req.year,
    )
    return success(data={"seasons": seasons})


@router.post("/history/clear", response_model=CommonResponse, summary="清空 RSS 历史")
def truncate_rsshistory(
    req: EmptyRequest = EmptyRequest(),
    user: str = Depends(require_permission("subscription:manage")),
    svc: SubscribeHistoryService = Depends(get_subscribe_history_service),
):
    svc.truncate()
    return success()
