import contextlib
import os
import urllib.parse
from concurrent.futures import ThreadPoolExecutor

from fastapi import APIRouter, Depends, File, Form, Query, UploadFile
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

import log
from api.deps import (
    get_downloader_service,
    get_file_index_service,
    get_media_config_service,
    get_media_file_service,
    get_media_info_service,
    get_media_library_service,
    get_media_recommendation_service,
    get_search_result_service,
    get_searcher_service,
    get_sync_service,
    get_tmdb_blacklist_service,
    get_transfer_history_service,
    require_any_permission,
    require_permission,
)
from app.core.error_codes import ErrorCode
from app.core.exceptions import (
    DomainError,
    ResourceNotFoundError,
    ServiceError,
    ValidationError,
)
from app.domain.mediatypes import MediaType
from app.infrastructure.cache_system import TokenCache
from app.schemas.common import CommonResponse
from app.services.downloader_core import DownloaderCore as Downloader
from app.services.file_index_service import FileIndexService
from app.services.media_config_service import MediaConfigService
from app.services.media_service import (
    MediaFileService,
    MediaInfoService,
    MediaLibraryService,
    MediaRecommendationService,
    SearchResultService,
    TransferHistoryService,
)
from app.services.search_service import Searcher
from app.services.transfer.name_format import FIELD_CATALOG, field_groups, render_path, validate
from app.utils.response import fail, success

router = APIRouter()


# ---------- Request Models ----------


class DownloadSubtitleRequest(BaseModel):
    path: str
    name: str


class GetSeasonEpisodesRequest(BaseModel):
    tmdbid: int
    title: str | None = None
    year: str | None = None
    season: int | None = None


class GetTvSeasonListRequest(BaseModel):
    tmdbid: str | int
    title: str | None = None


class MediaInfoRequest(BaseModel):
    id: str | None = None
    type: str | None = None
    title: str | None = None
    year: str | None = None
    page: str | None = None
    rssid: str | None = None


class MediaPathScrapRequest(BaseModel):
    path: str
    backend_id: str = "local"


class MediaPersonRequest(BaseModel):
    tmdbid: str | None = None
    type: str | None = None
    keyword: str | None = None


class MediaRecommendationsRequest(BaseModel):
    tmdbid: str
    type: str | None = None
    page: int | None = 1


class MediaSimilarRequest(BaseModel):
    tmdbid: str
    type: str | None = None
    page: int | None = 1


class MovieCalendarRequest(BaseModel):
    id: str | None = None
    rssid: str | None = None


class NameTestRequest(BaseModel):
    name: str
    subtitle: str | None = None


class PersonMediasRequest(BaseModel):
    personid: int
    type: str | None = None
    page: int | None = 1


class StartMediasyncRequest(BaseModel):
    librarys: list[str] | None = None


class TvCalendarRequest(BaseModel):
    id: str | None = None
    season: int | None = None
    name: str | None = None
    rssid: str | None = None


class GetCategoryConfigRequest(BaseModel):
    pass


class GetDownloadedRequest(BaseModel):
    page: int | None = None
    page_size: int | None = Field(default=30, ge=1, le=200)


class GetTransferHistoryRequest(BaseModel):
    keyword: str | None = None
    page: int | None = None
    pagenum: int | None = None


class GetTransferStatisticsRequest(BaseModel):
    days: int | None = None


class GetUnknownListByPageRequest(BaseModel):
    keyword: str | None = None
    page: int | None = None
    pagenum: int | None = None


class MediaDetailRequest(BaseModel):
    tmdbid: str
    type: str | None = None


class SearchMediaInfosRequest(BaseModel):
    keyword: str
    searchtype: str | None = None


class UpdateCategoryConfigRequest(BaseModel):
    config: list | None = None


class DirListRequest(BaseModel):
    path: str | None = None
    filter: str | None = None
    backend_id: str | None = None


class MkdirRequest(BaseModel):
    path: str
    name: str
    backend_id: str = "local"


class FileBatchRequest(BaseModel):
    files: list[str]
    dest_dir: str
    backend_id: str = "local"


class TmdbBlacklistRequest(BaseModel):
    tmdb_id: str | None = None
    media_type: str | None = None


# ---------- Endpoints ----------


@router.post("/subtitle/download", response_model=CommonResponse, summary="下载字幕")
def download_subtitle(
    req: DownloadSubtitleRequest,
    current_user=Depends(require_permission("library:manage")),
    svc: MediaFileService = Depends(get_media_file_service),
):
    try:
        svc.download_subtitle(path=req.path, name=req.name)
        return success(message="字幕下载任务已提交，正在后台运行。")
    except (ResourceNotFoundError, ServiceError, DomainError) as e:
        return fail(code=ErrorCode.OPERATION_FAILED, msg=e.message)


@router.post("/season/episodes", response_model=CommonResponse, summary="获取剧集列表")
def get_season_episodes(
    req: GetSeasonEpisodesRequest,
    current_user=Depends(require_any_permission("library:view", "library:manage")),
    svc: MediaInfoService = Depends(get_media_info_service),
):
    if not req.tmdbid:
        return fail(msg="TMDBID为空")
    season = 1 if req.season is None else req.season
    result = svc.get_season_episodes(tmdbid=req.tmdbid, title=req.title, year=req.year, season=season)
    return success(data=result.episodes)


@router.post("/season/list", response_model=CommonResponse, summary="获取电视剧季列表")
def get_tvseason_list(
    req: GetTvSeasonListRequest,
    current_user=Depends(require_any_permission("library:view", "library:manage")),
    svc: MediaInfoService = Depends(get_media_info_service),
):
    seasons = svc.get_tvseason_list(tmdbid=req.tmdbid, title=req.title)
    return success(data=seasons)


@router.post("/info", response_model=CommonResponse, summary="获取媒体信息")
def media_info(
    req: MediaInfoRequest,
    current_user=Depends(require_any_permission("library:view", "library:manage")),
    svc: MediaInfoService = Depends(get_media_info_service),
):
    result = svc.get_media_info_detail(
        mediaid=req.id,
        mtype=req.type,
        title=req.title,
        year=req.year,
        page=req.page,
        rssid=req.rssid,
    )
    return success(
        data={
            "type": result.type,
            "type_str": result.type_str,
            "page": result.page,
            "title": result.title,
            "vote_average": result.vote_average,
            "poster_path": result.poster_path,
            "release_date": result.release_date,
            "year": result.year,
            "overview": result.overview,
            "link_url": result.link_url,
            "tmdbid": result.tmdbid,
            "rssid": result.rssid,
            "seasons": result.seasons,
        }
    )


@router.post("/scrap", response_model=CommonResponse, summary="刮削媒体路径")
def media_path_scrap(
    req: MediaPathScrapRequest,
    current_user=Depends(require_permission("library:manage")),
    svc: MediaFileService = Depends(get_media_file_service),
):
    msg = svc.scrap_media_path(path=req.path, backend_id=req.backend_id)
    if msg.startswith("请"):
        return fail(code=ErrorCode.OPERATION_FAILED, msg=msg)
    return success(message=msg)


@router.post("/person", response_model=CommonResponse, summary="获取演员信息")
def media_person(
    req: MediaPersonRequest,
    current_user=Depends(require_any_permission("library:view", "library:manage")),
    svc: MediaInfoService = Depends(get_media_info_service),
):
    if not req.tmdbid and not req.keyword:
        return fail(msg="未指定TMDBID或关键字")
    result = svc.get_media_person(tmdbid=req.tmdbid, mtype_str=req.type, keyword=req.keyword)
    return success(data=result)


@router.post("/recommendations", response_model=CommonResponse, summary="获取媒体推荐")
def media_recommendations(
    req: MediaRecommendationsRequest,
    current_user=Depends(require_any_permission("library:view", "library:manage")),
    svc: MediaInfoService = Depends(get_media_info_service),
):
    if not req.tmdbid:
        return fail(msg="未指定TMDBID")
    result = svc.get_media_recommendations(tmdbid=req.tmdbid, mtype_str=req.type, page=req.page or 1)
    return success(data=result)


@router.post("/similar", response_model=CommonResponse, summary="获取相似媒体")
def media_similar(
    req: MediaSimilarRequest,
    current_user=Depends(require_any_permission("library:view", "library:manage")),
    svc: MediaInfoService = Depends(get_media_info_service),
):
    if not req.tmdbid:
        return fail(msg="未指定TMDBID")
    result = svc.get_media_similar(tmdbid=req.tmdbid, mtype_str=req.type, page=req.page or 1)
    return success(data=result)


@router.post("/sync/state", response_model=CommonResponse, summary="获取媒体同步状态")
def mediasync_state(
    current_user=Depends(require_permission("library:manage")),
    svc: MediaLibraryService = Depends(get_media_library_service),
):
    text = svc.get_sync_state()
    return success(data=text)


@router.post("/calendar/movie", response_model=CommonResponse, summary="获取电影日历")
def movie_calendar_data(
    req: MovieCalendarRequest,
    current_user=Depends(require_any_permission("library:view", "library:manage")),
    svc: MediaInfoService = Depends(get_media_info_service),
):
    result = svc.get_movie_calendar(tid=req.id, rssid=req.rssid)
    if not result:
        return fail(msg="无法查询到信息或上映日期不正确")
    return success(data=result)


@router.post("/name_test", response_model=CommonResponse, summary="名称测试")
def name_test(
    req: NameTestRequest,
    current_user=Depends(require_any_permission("library:view", "library:manage")),
    svc: MediaInfoService = Depends(get_media_info_service),
):
    if not req.name:
        return fail(code=ErrorCode.PARAM_VALIDATION_FAILED)
    result = svc.name_test(name=req.name, subtitle=req.subtitle)
    return success(data=result)


@router.post("/person/medias", response_model=CommonResponse, summary="获取演员作品")
def person_medias(
    req: PersonMediasRequest,
    current_user=Depends(require_any_permission("library:view", "library:manage")),
    svc: MediaInfoService = Depends(get_media_info_service),
):
    if not req.personid:
        return fail(msg="未指定演员ID")
    result = svc.get_person_medias(personid=req.personid, mtype_str=req.type, page=req.page or 1)
    return success(data=result)


@router.post("/sync/start", response_model=CommonResponse, summary="启动媒体同步")
def start_mediasync(
    req: StartMediasyncRequest,
    current_user=Depends(require_permission("library:manage")),
    svc: MediaLibraryService = Depends(get_media_library_service),
):
    svc.start_sync(librarys=req.librarys or [])
    return success()


@router.post("/calendar/tv", response_model=CommonResponse, summary="获取电视剧日历")
def tv_calendar_data(
    req: TvCalendarRequest,
    current_user=Depends(require_any_permission("library:view", "library:manage")),
    svc: MediaInfoService = Depends(get_media_info_service),
):
    result = svc.get_tv_calendar(tid=req.id, season=req.season, name=req.name, rssid=req.rssid)
    if not result:
        return fail(msg="无法查询到信息或上映日期不正确")
    return success(data=result)


@router.post("/history/clear", response_model=CommonResponse, summary="清空转移历史")
def clear_history(
    current_user=Depends(require_permission("library:manage")),
    svc: TransferHistoryService = Depends(get_transfer_history_service),
):
    svc.clear_history()
    return success()


@router.post("/category/config", response_model=CommonResponse, summary="获取分类配置")
def get_category_config(
    req: GetCategoryConfigRequest,
    current_user=Depends(require_permission("library:manage")),
    svc: MediaFileService = Depends(get_media_file_service),
):
    try:
        result = svc.get_category_config()
        return success(data=result)
    except (ResourceNotFoundError, ServiceError, DomainError) as e:
        return fail(msg=e.message)


@router.post("/library/downloaded", response_model=CommonResponse, summary="获取已下载列表")
def get_downloaded(
    req: GetDownloadedRequest,
    current_user=Depends(require_any_permission("library:view", "library:manage")),
    svc: Downloader = Depends(get_downloader_service),
):
    items = svc.get_download_history(page=req.page or 1, num=req.page_size or 30)
    if items:
        return success(
            data=[
                {
                    "id": item.TMDBID,
                    "orgid": item.TMDBID,
                    "tmdbid": item.TMDBID,
                    "title": item.TITLE,
                    "type": MediaType.from_string(item.TYPE or "").value,
                    "media_type": MediaType.from_string(item.TYPE or "").display_name,
                    "year": item.YEAR,
                    "vote": item.VOTE,
                    "image": item.POSTER,
                    "overview": item.TORRENT,
                    "enclosure": item.ENCLOSURE,
                    "season_episode": item.SE or "",
                    "date": item.DATE,
                    "site": item.SITE,
                }
                for item in items
            ]
        )
    return success(data=[])


@router.post("/library/count", response_model=CommonResponse, summary="获取媒体库统计")
def get_library_mediacount(
    current_user=Depends(require_any_permission("library:view", "library:manage")),
    svc: MediaLibraryService = Depends(get_media_library_service),
):
    result = svc.get_media_count()
    if result:
        return success(data=result)
    return fail(code=ErrorCode.MEDIA_SERVER_ERROR, msg="媒体库服务器连接失败")


@router.post("/library/history", response_model=CommonResponse, summary="获取播放历史")
def get_library_playhistory(
    current_user=Depends(require_any_permission("library:view", "library:manage")),
    svc: MediaLibraryService = Depends(get_media_library_service),
):
    return success(data=svc.get_play_history())


@router.post("/library/space", response_model=CommonResponse, summary="获取媒体库空间")
def get_library_spacesize(
    current_user=Depends(require_any_permission("library:view", "library:manage")),
    svc: MediaLibraryService = Depends(get_media_library_service),
):
    result = svc.get_space_info()
    return success(
        data={
            "UsedPercent": result.used_percent,
            "FreeSpace": result.free_space,
            "UsedSapce": result.used_space,
            "TotalSpace": result.total_space,
        }
    )


@router.post("/library/home", response_model=CommonResponse, summary="获取媒体库首页")
def get_library_home(
    current_user=Depends(require_any_permission("library:view", "library:manage")),
    svc: MediaLibraryService = Depends(get_media_library_service),
):
    # 6 项数据均为独立的媒体服务器请求，并发获取以降低整体耗时
    def _media_counts():
        try:
            return svc.get_media_count() or None
        except Exception as e:  # noqa: BLE001
            log.debug(f"[MediaLibrary]获取媒体数量失败: {e}")
            return None

    def _activity():
        with contextlib.suppress(Exception):
            return svc.get_play_history() or []
        return []

    def _spaces():
        try:
            space_info = svc.get_space_info()
            return {
                "UsedPercent": space_info.used_percent,
                "FreeSpace": space_info.free_space,
                "UsedSpace": space_info.used_space,
                "TotalSpace": space_info.total_space,
            }
        except Exception as e:  # noqa: BLE001
            log.debug(f"[MediaLibrary]获取空间信息失败: {e}")
            return {}

    def _libraries():
        with contextlib.suppress(Exception):
            return svc.get_libraries() or []
        return []

    def _resumes():
        with contextlib.suppress(Exception):
            return svc.get_resume() or []
        return []

    def _latests():
        with contextlib.suppress(Exception):
            return svc.get_latest() or []
        return []

    with ThreadPoolExecutor(max_workers=6) as executor:
        f_counts = executor.submit(_media_counts)
        f_activity = executor.submit(_activity)
        f_spaces = executor.submit(_spaces)
        f_libraries = executor.submit(_libraries)
        f_resumes = executor.submit(_resumes)
        f_latests = executor.submit(_latests)

        counts_result = f_counts.result()
        server_success = counts_result is not None
        media_counts = counts_result or {}
        activity = f_activity.result()
        library_spaces = f_spaces.result()
        libraries = f_libraries.result()
        resumes = f_resumes.result()
        latests = f_latests.result()

    return success(
        data={
            "server_success": server_success,
            "media_counts": {
                "Movie": media_counts.get("Movie", 0),
                "Series": media_counts.get("Series", 0),
                "Music": media_counts.get("Music", 0),
                "Episodes": media_counts.get("Episodes", 0),
                "User": media_counts.get("User", 0),
            },
            "user_count": media_counts.get("User", 0),
            "activitys": activity,
            "library_spaces": library_spaces,
            "librarys": libraries,
            "resumes": resumes,
            "latests": latests,
        }
    )


@router.post("/recommend", response_model=CommonResponse, summary="获取推荐")
def get_recommend(
    req: dict,
    current_user=Depends(require_any_permission("library:view", "library:manage")),
    svc: MediaRecommendationService = Depends(get_media_recommendation_service),
):
    # 兼容前端 ajax_post 格式 {data: params}
    data = req.get("data", req)
    res_list = svc.get_recommend_items(data)
    return success(data=res_list)


@router.post("/search/results", response_model=CommonResponse, summary="获取搜索结果")
def get_search_result(
    req: dict | None = None,
    current_user=Depends(require_any_permission("library:view", "library:manage")),
    svc: Searcher = Depends(get_searcher_service),
    result_svc: SearchResultService = Depends(get_search_result_service),
):
    req = req or {}
    session_id = req.get("session_id") or TokenCache.get(f"search_session:{current_user.user_id}")
    search_results = svc.get_search_results(session_id)
    result = result_svc.group_search_results(search_results)
    return success(data={"total": result.total, "result": result.result})


@router.post("/transfer/history", response_model=CommonResponse, summary="获取转移历史")
def get_transfer_history(
    req: GetTransferHistoryRequest,
    current_user=Depends(require_any_permission("library:view", "library:manage")),
    svc: TransferHistoryService = Depends(get_transfer_history_service),
):
    result = svc.get_transfer_history_page(search_str=req.keyword, page=req.page, page_num=req.pagenum)
    return success(
        data={
            "total": result.total,
            "result": result.result,
            "totalPage": result.total_page,
            "pageNum": result.page_num,
            "currentPage": result.current_page,
        }
    )


@router.post("/transfer/statistics", response_model=CommonResponse, summary="获取转移统计")
def get_transfer_statistics(
    req: GetTransferStatisticsRequest,
    current_user=Depends(require_any_permission("library:view", "library:manage")),
    svc: TransferHistoryService = Depends(get_transfer_history_service),
):
    result = svc.get_transfer_statistics(days=req.days if req.days is not None else 90)
    return success(data=result)


@router.post("/unknown", response_model=CommonResponse, summary="获取未识别列表")
def get_unknown_list(
    current_user=Depends(require_any_permission("library:view", "library:manage")),
    svc: TransferHistoryService = Depends(get_transfer_history_service),
):
    items = svc.get_unknown_list()
    return success(data=items)


@router.post("/unknown/paged", response_model=CommonResponse, summary="分页获取未识别列表")
def get_unknown_list_by_page(
    req: GetUnknownListByPageRequest,
    current_user=Depends(require_any_permission("library:view", "library:manage")),
    svc: TransferHistoryService = Depends(get_transfer_history_service),
):
    result = svc.get_unknown_list_by_page(search_str=req.keyword, page=req.page, page_num=req.pagenum)
    return success(
        data={
            "total": result.total,
            "items": result.items,
            "totalPage": result.total_page,
            "pageNum": result.page_num,
            "currentPage": result.current_page,
        }
    )


@router.post("/detail", response_model=CommonResponse, summary="获取媒体详情")
def media_detail(
    req: MediaDetailRequest,
    current_user=Depends(require_any_permission("library:view", "library:manage")),
    svc: MediaInfoService = Depends(get_media_info_service),
):
    tmdbid = urllib.parse.unquote(req.tmdbid) if req.tmdbid else req.tmdbid
    if not tmdbid:
        return fail(msg="未指定媒体ID")
    result = svc.get_media_detail(tmdbid=tmdbid, mtype_str=req.type)
    if not result:
        return fail(msg="无法查询到TMDB信息")
    return success(data=result)


@router.post("/search", response_model=CommonResponse, summary="搜索媒体")
def search_media_infos(
    req: SearchMediaInfosRequest,
    current_user=Depends(require_any_permission("library:view", "library:manage")),
    svc: MediaInfoService = Depends(get_media_info_service),
):
    if not req.keyword:
        return success(data=[])
    result = svc.search_media_infos(keyword=req.keyword, source=req.searchtype, page=1)
    return success(data=result)


@router.post("/unknown/list", response_model=CommonResponse, summary="重新识别未识别项")
def unidentification(
    current_user=Depends(require_any_permission("library:view", "library:manage")),
    svc: TransferHistoryService = Depends(get_transfer_history_service),
):
    svc.re_identify_unknown()
    return success()


@router.post("/category/config/update", response_model=CommonResponse, summary="更新分类配置")
def update_category_config(
    req: UpdateCategoryConfigRequest,
    current_user=Depends(require_permission("library:manage")),
    svc: MediaFileService = Depends(get_media_file_service),
):
    msg = svc.update_category_config(items=req.config or [])
    return success(message=msg)


@router.post("/dir/list", response_model=CommonResponse, summary="获取目录列表")
def dir_list(
    req: DirListRequest,
    current_user=Depends(require_permission("library:manage")),
    svc: MediaFileService = Depends(get_media_file_service),
):
    """目录列表（JSON格式，供前端文件管理器使用）"""
    try:
        result = svc.get_dir_list(req.path or "", req.backend_id or "")
        return success(data=result)
    except (ValidationError, ResourceNotFoundError, ServiceError, DomainError) as e:
        return fail(msg=e.message)


@router.post("/dir/mkdir", response_model=CommonResponse, summary="创建目录")
def make_dir(
    req: MkdirRequest,
    current_user=Depends(require_permission("library:manage")),
    svc: MediaFileService = Depends(get_media_file_service),
):
    try:
        target = svc.make_dir(parent=req.path, name=req.name, backend_id=req.backend_id)
        return success(data={"path": target}, message="创建成功")
    except (ValidationError, ResourceNotFoundError, ServiceError, DomainError) as e:
        return fail(msg=e.message)


@router.post("/files/move", response_model=CommonResponse, summary="移动文件")
def move_files(
    req: FileBatchRequest,
    current_user=Depends(require_permission("library:manage")),
    svc: MediaFileService = Depends(get_media_file_service),
):
    try:
        msg = svc.move_or_copy_files(req.files, req.dest_dir, backend_id=req.backend_id, move=True)
        return success(message=msg)
    except (ValidationError, ResourceNotFoundError, ServiceError, DomainError) as e:
        return fail(msg=e.message)


@router.post("/files/copy", response_model=CommonResponse, summary="复制文件")
def copy_files(
    req: FileBatchRequest,
    current_user=Depends(require_permission("library:manage")),
    svc: MediaFileService = Depends(get_media_file_service),
):
    try:
        msg = svc.move_or_copy_files(req.files, req.dest_dir, backend_id=req.backend_id, move=False)
        return success(message=msg)
    except (ValidationError, ResourceNotFoundError, ServiceError, DomainError) as e:
        return fail(msg=e.message)


@router.get("/file/download", summary="下载文件")
def download_file(
    path: str = Query(..., min_length=1),
    backend_id: str = Query("local"),
    current_user=Depends(require_permission("library:manage")),
    svc: MediaFileService = Depends(get_media_file_service),
):
    stream, _info = svc.open_download(path, backend_id)

    def _iter():
        try:
            while chunk := stream.read(1024 * 1024):
                yield chunk
        finally:
            stream.close()

    quoted = urllib.parse.quote(os.path.basename(path))
    return StreamingResponse(
        _iter(),
        media_type="application/octet-stream",
        headers={"Content-Disposition": f"attachment; filename*=utf-8''{quoted}"},
    )


@router.post("/file/upload", response_model=CommonResponse, summary="上传文件")
async def upload_file(
    file: UploadFile = File(...),
    path: str = Form(...),
    backend_id: str = Form("local"),
    current_user=Depends(require_permission("library:manage")),
    svc: MediaFileService = Depends(get_media_file_service),
):
    try:
        target = svc.save_upload(dest_dir=path, name=file.filename or "", stream=file.file, backend_id=backend_id)
        return success(data={"path": target}, message="上传成功")
    except (ValidationError, ResourceNotFoundError, ServiceError, DomainError) as e:
        return fail(msg=e.message)


@router.post("/library/paths", response_model=CommonResponse, summary="获取媒体库路径")
def get_library_paths(
    current_user=Depends(require_any_permission("library:view", "library:manage")),
    media_svc=Depends(get_media_config_service),
    sync_svc=Depends(get_sync_service),
    media_file_svc: MediaFileService = Depends(get_media_file_service),
):
    """获取媒体库目录 + 同步源目录（从数据库 CONFIG_MEDIA 读取）"""
    media = media_svc.get_config()
    result = media_file_svc.get_library_paths(
        media=media,
        sync_svc=sync_svc,
    )
    return success(data=result)


@router.get("/tmdb_blacklist/list", response_model=CommonResponse, summary="获取 TMDB 黑名单")
def get_tmdb_blacklist(
    page: int = Query(1, ge=1),
    count: int = Query(30, ge=1, le=100),
    s: str | None = Query(""),
    current_user=Depends(require_any_permission("library:view", "library:manage")),
    tmdb_svc=Depends(get_tmdb_blacklist_service),
):
    items, total = tmdb_svc.get_blacklist(tmdb_id=s if s else None, page=page, count=count)
    return success(
        data={
            "items": items,
            "total": total,
            "page": page,
            "count": count,
        }
    )


@router.post("/tmdb_blacklist/add", response_model=CommonResponse, summary="添加 TMDB 黑名单")
def add_tmdb_blacklist(
    req: TmdbBlacklistRequest,
    current_user=Depends(require_permission("library:manage")),
    tmdb_svc=Depends(get_tmdb_blacklist_service),
):
    if not tmdb_svc.is_blacklisted(req.tmdb_id, req.media_type):
        tmdb_svc.add_to_blacklist(tmdb_id=req.tmdb_id, media_type=req.media_type)
    return success()


@router.post("/tmdb_blacklist/delete", response_model=CommonResponse, summary="删除 TMDB 黑名单")
def delete_tmdb_blacklist(
    req: TmdbBlacklistRequest,
    current_user=Depends(require_permission("library:manage")),
    tmdb_svc=Depends(get_tmdb_blacklist_service),
):
    if tmdb_svc.is_blacklisted(req.tmdb_id, req.media_type):
        tmdb_svc.remove_from_blacklist(tmdb_id=req.tmdb_id, media_type=req.media_type)
    return success()


@router.post("/tmdb_blacklist/clear", response_model=CommonResponse, summary="清空 TMDB 黑名单")
def clear_tmdb_blacklist(
    current_user=Depends(require_permission("library:manage")),
    tmdb_svc=Depends(get_tmdb_blacklist_service),
):
    if tmdb_svc.get_blacklist():
        tmdb_svc.clear_blacklist()
    return success()


@router.get("/search/files", response_model=CommonResponse, summary="搜索文件")
def search_files(
    keyword: str = Query(..., min_length=1),
    limit: int = Query(100, ge=1, le=500),
    svc: FileIndexService = Depends(get_file_index_service),
    current_user=Depends(require_any_permission("library:view", "library:manage")),
):
    """全局搜索媒体库 + 同步源目录中的文件（基于后台索引，O(1) 响应）"""
    results = svc.search(keyword, limit=limit)
    return success(
        data={
            "items": results,
            "total": len(results),
            "ready": svc.is_ready,
            "indexed": svc.indexed_count,
        }
    )


class MediaPathAddRequest(BaseModel):
    path_type: str
    path: str
    backend: str = "local"


class MediaPathRemoveRequest(BaseModel):
    path_type: str
    path: str


class MediaPathUpdateRequest(BaseModel):
    path_type: str
    old_path: str
    new_path: str
    backend: str = "local"


@router.post("/library/path", response_model=CommonResponse, summary="获取媒体库配置")
def get_media_library_config(
    current_user=Depends(require_any_permission("library:view", "library:manage")),
    svc: MediaConfigService = Depends(get_media_config_service),
):
    """获取媒体库路径配置（DB 优先，YAML 回退）"""
    return success(data=svc.get_config())


@router.post("/library/path/add", response_model=CommonResponse, summary="添加媒体库路径")
def add_media_library_path(
    req: MediaPathAddRequest,
    current_user=Depends(require_permission("library:manage")),
    svc: MediaConfigService = Depends(get_media_config_service),
):
    """添加媒体库路径"""
    svc.add_path(req.path_type, req.path, req.backend)
    return success()


@router.post("/library/path/remove", response_model=CommonResponse, summary="移除媒体库路径")
def remove_media_library_path(
    req: MediaPathRemoveRequest,
    current_user=Depends(require_permission("library:manage")),
    svc: MediaConfigService = Depends(get_media_config_service),
):
    """移除媒体库路径"""
    svc.remove_path(req.path_type, req.path)
    return success()


@router.post("/library/path/update", response_model=CommonResponse, summary="更新媒体库路径")
def update_media_library_path(
    req: MediaPathUpdateRequest,
    current_user=Depends(require_permission("library:manage")),
    svc: MediaConfigService = Depends(get_media_config_service),
):
    """更新媒体库路径"""
    svc.update_path(req.path_type, req.old_path, req.new_path, req.backend)
    return success()


# ---------- 重命名格式：字段目录 / 校验 / 预览 ----------


class NameFormatPreviewRequest(BaseModel):
    format: str
    media_type: str = "tv"
    values: dict = {}


class NameFormatValidateRequest(BaseModel):
    format: str


@router.get("/name_format/fields", response_model=CommonResponse, summary="重命名格式字段目录")
def name_format_fields(
    current_user=Depends(require_any_permission("setting:view", "setting:update")),
):
    """返回可按分组插入的占位符字段目录。"""
    return success(data={"groups": field_groups(), "fields": FIELD_CATALOG})


@router.post("/name_format/validate", response_model=CommonResponse, summary="校验重命名格式")
def name_format_validate(
    req: NameFormatValidateRequest,
    current_user=Depends(require_any_permission("setting:view", "setting:update")),
):
    return success(data=validate(req.format))


@router.post("/name_format/preview", response_model=CommonResponse, summary="预览重命名格式")
def name_format_preview(
    req: NameFormatPreviewRequest,
    current_user=Depends(require_any_permission("setting:view", "setting:update")),
):
    mtype = "movie" if str(req.media_type).lower() in ("movie", "电影") else "tv"
    return success(
        data={
            "segments": render_path(req.format, mtype, req.values),
            "validate": validate(req.format),
        }
    )
