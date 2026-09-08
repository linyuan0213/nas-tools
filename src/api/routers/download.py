"""
Download Router — FastAPI 迁移
对应原 web/controllers/download.py，复用 app/services/download_service.py
"""

import json
import os
import queue

from fastapi import APIRouter, Depends
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

import log
from api.deps import (
    get_download_service,
    get_downloader_service,
    get_filetransfer_service,
    get_indexer_service,
    get_site_service,
    require_any_permission,
    require_permission,
)
from app.core.exceptions import (
    DomainError,
    ResourceNotFoundError,
    ServiceError,
    ValidationError,
)
from app.downloader.client_factory import DownloadClientFactory
from app.downloader.registry import get_all_clients
from app.downloader.status import TORRENT_STATUS_LABELS
from app.events.constants import DOWNLOAD_FAILED
from app.infrastructure.thread import ThreadExecutor
from app.schemas.auth import UserContext
from app.schemas.common import CommonResponse
from app.services.download_event_queue import download_event_queue
from app.services.download_service import DownloadService
from app.services.downloader_core import DownloaderCore as Downloader
from app.services.filetransfer_service import FileTransferService as FileTransfer
from app.services.indexer_service import IndexerService
from app.services.site_service import SiteService
from app.utils import ExceptionUtils, SystemUtils
from app.utils.json_utils import JsonUtils
from app.utils.response import fail, success

router = APIRouter()


# ---------------------------------------------------------------------------
# Request Models
# ---------------------------------------------------------------------------


class EmptyRequest(BaseModel):
    data: dict | None = None


class AutoRemoveTorrentsRequest(BaseModel):
    tid: str | int | None = None


class CheckDownloaderRequest(BaseModel):
    did: str | None = None
    checked: bool | None = None
    flag: str | None = None


class DelDownloaderRequest(BaseModel):
    did: str | None = None


class DeleteDownloadSettingRequest(BaseModel):
    sid: str | None = None


class DeleteTorrentRemoveTaskRequest(BaseModel):
    tid: str | int | None = None


class DownloadRequest(BaseModel):
    id: int | None = None
    dir: str | None = None
    setting: str | None = None


class DownloadLinkRequest(BaseModel):
    site: str | None = None
    enclosure: str | None = None
    title: str | None = None
    description: str | None = None
    page_url: str | None = None
    size: str | None = None
    seeders: str | None = None
    uploadvolumefactor: str | None = None
    downloadvolumefactor: str | None = None
    dl_dir: str | None = None
    dl_setting: str | None = None


class DownloadTorrentRequest(BaseModel):
    files: list | None = None
    urls: list | None = None
    dl_dir: str | None = None
    dl_setting: str | None = None
    page_url: str | None = None
    upload_volume_factor: float | None = None
    download_volume_factor: float | None = None
    title: str | None = None
    description: str | None = None
    site: str | None = None
    size: int | None = None


class FindHardlinksRequest(BaseModel):
    files: list | None = None
    dir: str | None = None


class ResolveDownloadUrlRequest(BaseModel):
    page_url: str | None = None
    enclosure: str | None = None


class GetDownloadDirsRequest(BaseModel):
    sid: str | None = None
    site: str | None = None


class GetDownloadSettingRequest(BaseModel):
    sid: str | None = None


class GetDownloadersRequest(BaseModel):
    did: str | None = None
    brush: bool = False


class SetDefaultDownloaderRequest(BaseModel):
    did: str | None = None


class SetDefaultDownloadSettingRequest(BaseModel):
    sid: str | None = None


class GetRemoveTorrentsRequest(BaseModel):
    tid: str | int | None = None


class GetTorrentRemoveTaskRequest(BaseModel):
    tid: str | int | None = None


class PtInfoRequest(BaseModel):
    ids: str | None = None


class PtIdRequest(BaseModel):
    id: str | None = None


class BatchIdsRequest(BaseModel):
    ids: list[str] = []
    delete_files: bool = False


class TestDownloaderRequest(BaseModel):
    type: str | None = None
    config: str | None = None


class BrowseDownloaderDirsRequest(BaseModel):
    type: str | None = None
    config: str | dict | None = None


class UpdateDownloadSettingRequest(BaseModel):
    sid: str | int | None = None
    name: str | None = None
    category: str | None = None
    tags: str | None = None
    is_paused: int | bool | None = None
    upload_limit: int | str | None = 0
    download_limit: int | str | None = 0
    ratio_limit: int | str | None = 0
    seeding_time_limit: int | str | None = 0
    downloader: str | None = None


class UpdateDownloaderRequest(BaseModel):
    did: str | None = None
    name: str | None = None
    type: str | None = None
    enabled: int | None = None
    transfer: int | None = None
    only_nexus_media: int | None = None
    match_path: int | None = None
    rmt_mode: str | None = None
    config: str | None = None
    download_dir: str | None = None


class UpdateTorrentRemoveTaskRequest(BaseModel):
    data: dict


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------


@router.post("/torrent-remove-tasks/run", response_model=CommonResponse, summary="执行自动删种任务")
def auto_remove_torrents(
    req: AutoRemoveTorrentsRequest,
    user: str = Depends(require_permission("download:manage")),
    svc: DownloadService = Depends(get_download_service),
):
    ThreadExecutor.named("torrent_remove").submit(svc.auto_remove_torrents, taskids=req.tid)
    return success()


@router.post("/downloaders/check", response_model=CommonResponse, summary="切换下载器设置")
def check_downloader(
    req: CheckDownloaderRequest,
    user: str = Depends(require_permission("download:manage")),
    svc: Downloader = Depends(get_downloader_service),
):
    did = req.did
    if not did:
        return fail()
    checked = req.checked
    flag = req.flag
    enabled = transfer = only_nexus_media = match_path = None
    if flag == "enabled":
        enabled = 1 if checked else 0
    elif flag == "transfer":
        transfer = 1 if checked else 0
    elif flag == "only_nexus_media":
        only_nexus_media = 1 if checked else 0
    elif flag == "match_path":
        match_path = 1 if checked else 0
    svc.check_downloader(
        did=did, enabled=enabled, transfer=transfer, only_nexus_media=only_nexus_media, match_path=match_path
    )
    return success()


@router.post("/downloaders/delete", response_model=CommonResponse, summary="删除下载器")
def del_downloader(
    req: DelDownloaderRequest,
    user: str = Depends(require_permission("download:manage")),
    svc: Downloader = Depends(get_downloader_service),
):
    svc.delete_downloader(did=req.did)
    return success()


@router.post("/settings/delete", response_model=CommonResponse, summary="删除下载设置")
def delete_download_setting(
    req: DeleteDownloadSettingRequest,
    user: str = Depends(require_permission("download:manage")),
    svc: Downloader = Depends(get_downloader_service),
):
    svc.delete_download_setting(sid=req.sid)
    return success()


@router.post("/torrent-remove-tasks/delete", response_model=CommonResponse, summary="删除删种任务")
def delete_torrent_remove_task(
    req: DeleteTorrentRemoveTaskRequest,
    user: str = Depends(require_permission("download:manage")),
    svc: DownloadService = Depends(get_download_service),
):
    try:
        svc.delete_torrent_remove_task(taskid=req.tid)
        return success()
    except (ValidationError, ResourceNotFoundError) as e:
        return fail(msg=e.message)
    except (ServiceError, DomainError) as e:
        return fail(msg=e.message)


@router.post("/tasks/add", response_model=CommonResponse, summary="添加下载任务")
def download(
    req: DownloadRequest,
    user: UserContext = Depends(require_permission("download:manage")),
    svc: DownloadService = Depends(get_download_service),
):
    if req.id is None:
        return fail(msg="缺少下载ID")

    def _do_download():
        try:
            svc.download_from_search_results(
                dl_id=req.id or 0,
                dl_dir=req.dir or "",
                dl_setting=req.setting or "",
                user_name=user.nickname or user.username,
            )
        except Exception as e:
            ExceptionUtils.exception_traceback(e)
            download_event_queue.put(
                {"event": DOWNLOAD_FAILED, "data": {"title": f"下载ID:{req.id}", "reason": str(e)}}
            )

    ThreadExecutor(name="download").submit(_do_download)
    return success(message="下载任务已提交")


@router.post("/tasks/add_link", response_model=CommonResponse, summary="添加链接下载任务")
def download_link(
    req: DownloadLinkRequest,
    user: UserContext = Depends(require_permission("download:manage")),
    svc: DownloadService = Depends(get_download_service),
):
    def _do_download():
        try:
            svc.download_from_link(
                site=req.site or "",
                enclosure=req.enclosure or "",
                title=req.title or "",
                description=req.description or "",
                page_url=req.page_url or "",
                size=req.size or "",
                seeders=req.seeders or "",
                uploadvolumefactor=req.uploadvolumefactor or "",
                downloadvolumefactor=req.downloadvolumefactor or "",
                dl_dir=req.dl_dir or "",
                dl_setting=req.dl_setting or "",
                user_name=user.nickname or user.username,
            )
        except Exception as e:
            ExceptionUtils.exception_traceback(e)
            download_event_queue.put({"event": DOWNLOAD_FAILED, "data": {"title": req.title or "", "reason": str(e)}})

    ThreadExecutor(name="download").submit(_do_download)
    return success(message="下载任务已提交")


@router.post("/tasks/resolve_url", response_model=CommonResponse, summary="解析下载链接")
def resolve_download_url(
    req: ResolveDownloadUrlRequest,
    user: str = Depends(require_any_permission("download:view", "download:manage")),
    svc: DownloadService = Depends(get_download_service),
):
    url = svc.resolve_download_url(page_url=req.page_url or "", enclosure=req.enclosure)
    if not url:
        return fail(msg="无法获取下载链接")
    return success(data={"url": url})


@router.post("/tasks/add_torrent", response_model=CommonResponse, summary="添加种子下载任务")
def download_torrent(
    req: DownloadTorrentRequest,
    user: UserContext = Depends(require_permission("download:manage")),
    svc: DownloadService = Depends(get_download_service),
):
    # 快速校验
    if not req.urls and not req.files:
        return fail(msg="没有种子文件或者种子链接")

    # 后台线程执行下载（避免网络 IO 阻塞 API 响应）
    def _do_download():
        try:
            result = svc.download_from_torrent_files_or_urls(
                files=req.files or [],
                urls=req.urls or [],
                dl_dir=req.dl_dir or "",
                dl_setting=req.dl_setting or "",
                user_name=user.nickname or user.username,
                page_url=req.page_url or "",
                upload_volume_factor=req.upload_volume_factor,
                download_volume_factor=req.download_volume_factor,
                title=req.title or "",
                description=req.description or "",
                site=req.site or "",
                size=req.size,
            )
            if not result.success:
                log.warn(f"[Download]下载失败: {result.message}")
                download_event_queue.put(
                    {"event": DOWNLOAD_FAILED, "data": {"title": req.title, "reason": result.message}}
                )
            else:
                log.info(f"[Download]下载成功: {req.title or req.urls}")
        except (ServiceError, DomainError) as e:
            ExceptionUtils.exception_traceback(e)
        except Exception as e:
            ExceptionUtils.exception_traceback(e)

    ThreadExecutor(name="download").submit(_do_download)
    return success(message="下载任务已提交")


@router.post("/tools/hardlinks", response_model=CommonResponse, summary="查找硬链接")
def find_hardlinks(
    req: FindHardlinksRequest,
    user: str = Depends(require_any_permission("download:view", "download:manage")),
):
    files = req.files
    file_dir = req.dir
    if not files:
        return success(data=[])
    if not file_dir and os.name != "nt":
        file_dir = os.path.commonpath(files).replace("\\", "/")
        if file_dir != "/":
            file_dir = "/" + str(file_dir).split("/")[1]
        else:
            return success(data=[])
    hardlinks = {}
    if files:
        try:
            for file in files:
                hardlinks[os.path.basename(file)] = SystemUtils().find_hardlinks(file=file, fdir=file_dir)
        except (ServiceError, DomainError) as e:
            return fail(msg=e.message)
        except Exception as e:
            ExceptionUtils.exception_traceback(e)
            return fail()
    return success(data=hardlinks)


@router.post("/downloaders/dirs", response_model=CommonResponse, summary="获取下载目录")
def get_download_dirs(
    req: GetDownloadDirsRequest,
    user: str = Depends(require_any_permission("download:view", "download:manage")),
    site_svc: SiteService = Depends(get_site_service),
    downloader_svc: Downloader = Depends(get_downloader_service),
):
    sid = req.sid
    site = req.site
    if not sid and site:
        sid = site_svc.get_site_download_setting(site_name=site)
    dirs = downloader_svc.get_download_dirs(setting=sid)
    return success(data=dirs)


@router.post("/settings", response_model=CommonResponse, summary="获取下载设置")
def get_download_setting(
    req: GetDownloadSettingRequest,
    user: str = Depends(require_any_permission("download:view", "download:manage")),
    svc: Downloader = Depends(get_downloader_service),
):
    sid = req.sid
    if sid:
        download_setting = svc.get_download_setting(sid=sid)
    else:
        download_setting = list(svc.get_download_setting().values())
    return success(data=download_setting)


@router.post("/downloaders", response_model=CommonResponse, summary="获取下载器配置")
def get_downloaders(
    req: GetDownloadersRequest,
    user: str = Depends(require_any_permission("download:view", "download:manage")),
    svc: Downloader = Depends(get_downloader_service),
):
    data = svc.get_downloader_conf(did=req.did)
    data = data or {}
    if req.brush:
        # 刷流仅支持 PT 站，过滤不支持 PT 的下载器（aria2/thunder 等）
        data = {k: v for k, v in data.items() if DownloadClientFactory._supports_brush(v.get("type"))}
    return success(data=data)


@router.post("/downloaders/simple", response_model=CommonResponse, summary="获取下载器列表")
def get_downloaders_simple(
    user: str = Depends(require_any_permission("download:view", "download:manage")),
    svc: Downloader = Depends(get_downloader_service),
    brush: int = 0,
):
    data = svc.get_downloader_conf_simple(brush=bool(brush))
    return success(data=[{"id": v["id"], "name": v["name"]} for v in data.values()])


@router.post("/downloaders/default", response_model=CommonResponse, summary="设置默认下载器")
def set_default_downloader(
    req: SetDefaultDownloaderRequest,
    user: str = Depends(require_permission("download:manage")),
    svc: Downloader = Depends(get_downloader_service),
):
    """设置默认下载器"""
    if not req.did:
        return fail(msg="下载器ID不能为空")
    if svc.set_default_downloader_id(req.did):
        return success()
    return fail(msg="设置失败，下载器不存在")


@router.post("/downloaders/types", response_model=CommonResponse, summary="获取下载器类型配置")
def get_downloader_types(
    user: str = Depends(require_any_permission("download:view", "download:manage")),
):
    """获取支持的下载器类型配置"""
    return success(data={cls.client_id: cls.config_schema.to_dict() for cls in get_all_clients()})


@router.post("/indexers/statistics", response_model=CommonResponse, summary="获取索引器统计")
def get_indexer_statistics(
    req: EmptyRequest = EmptyRequest(),
    user: str = Depends(require_any_permission("download:view", "download:manage")),
    svc: DownloadService = Depends(get_download_service),
):
    stats, dataset = svc.get_indexer_statistics()
    return success(
        data={
            "stats": [
                {"name": s.name, "total": s.total, "fail": s.fail, "success": s.success, "avg": s.avg} for s in stats
            ],
            "dataset": dataset,
        }
    )


@router.post("/indexers", response_model=CommonResponse, summary="获取用户索引器")
def get_indexers(
    req: EmptyRequest = EmptyRequest(),
    user: str = Depends(require_any_permission("download:view", "download:manage")),
    svc: IndexerService = Depends(get_indexer_service),
):
    indexers = svc.get_all_user_indexers()
    return success(data=[{"id": i.id, "name": i.name} for i in indexers])


@router.post("/torrent-remove-tasks/candidates", response_model=CommonResponse, summary="获取可删除种子列表")
def get_remove_torrents(
    req: GetRemoveTorrentsRequest,
    user: str = Depends(require_any_permission("download:view", "download:manage")),
    svc: DownloadService = Depends(get_download_service),
):
    try:
        torrents = svc.get_remove_torrents(taskid=req.tid)
        return success(data=torrents or [])
    except (ResourceNotFoundError, ValidationError) as e:
        return fail(msg=e.message)
    except (ServiceError, DomainError) as e:
        return fail(msg=e.message)


@router.post("/torrent-remove-tasks", response_model=CommonResponse, summary="获取删种任务")
def get_torrent_remove_task(
    req: GetTorrentRemoveTaskRequest,
    user: str = Depends(require_any_permission("download:view", "download:manage")),
    svc: DownloadService = Depends(get_download_service),
):
    return success(data=svc.get_torrent_remove_tasks(taskid=req.tid))


@router.get("/torrent-remove-tasks/seed-statuses", response_model=CommonResponse, summary="获取种子状态列表")
def get_seed_statuses(
    user: str = Depends(require_any_permission("download:view", "download:manage")),
):
    statuses = [{"label": label, "value": status.name} for status, label in TORRENT_STATUS_LABELS.items()]
    return success(data=statuses)


@router.post("/tasks/info", response_model=CommonResponse, summary="获取下载任务信息")
def pt_info(
    req: PtInfoRequest,
    user: str = Depends(require_any_permission("download:view", "download:manage")),
    svc: Downloader = Depends(get_downloader_service),
):
    torrents = svc.get_downloading_progress(ids=req.ids)
    return success(data=torrents)


@router.post("/tasks/remove", response_model=CommonResponse, summary="删除下载任务")
def pt_remove(
    req: PtIdRequest,
    user: str = Depends(require_any_permission("download:view", "download:manage")),
    svc: Downloader = Depends(get_downloader_service),
):
    tid = req.id
    if tid:
        svc.delete_torrents(ids=tid, delete_file=True)
    return success(data=tid)


@router.post("/tasks/start", response_model=CommonResponse, summary="开始下载任务")
def pt_start(
    req: PtIdRequest,
    user: str = Depends(require_permission("download:manage")),
    svc: Downloader = Depends(get_downloader_service),
):
    tid = req.id
    if tid:
        svc.start_torrents(ids=tid)
    return success(data=tid)


@router.post("/tasks/stop", response_model=CommonResponse, summary="停止下载任务")
def pt_stop(
    req: PtIdRequest,
    user: str = Depends(require_permission("download:manage")),
    svc: Downloader = Depends(get_downloader_service),
):
    tid = req.id
    if tid:
        svc.stop_torrents(ids=tid)
    return success(data=tid)


@router.post("/tasks/batch/start", response_model=CommonResponse, summary="批量开始下载任务")
def pt_batch_start(
    req: BatchIdsRequest,
    _user: str = Depends(require_permission("download:manage")),
    svc: Downloader = Depends(get_downloader_service),
):
    if req.ids:
        svc.start_torrents(ids=req.ids)
    return success(data=req.ids)


@router.post("/tasks/batch/stop", response_model=CommonResponse, summary="批量停止下载任务")
def pt_batch_stop(
    req: BatchIdsRequest,
    _user: str = Depends(require_permission("download:manage")),
    svc: Downloader = Depends(get_downloader_service),
):
    if req.ids:
        svc.stop_torrents(ids=req.ids)
    return success(data=req.ids)


@router.post("/tasks/batch/remove", response_model=CommonResponse, summary="批量删除下载任务")
def pt_batch_remove(
    req: BatchIdsRequest,
    _user: str = Depends(require_any_permission("download:view", "download:manage")),
    svc: Downloader = Depends(get_downloader_service),
):
    if req.ids:
        for tid in req.ids:
            svc.delete_torrents(ids=tid, delete_file=req.delete_files)
    return success(data=req.ids)


@router.post("/downloaders/test", response_model=CommonResponse, summary="测试下载器连接")
def test_downloader(
    req: TestDownloaderRequest,
    user: str = Depends(require_permission("download:manage")),
    svc: Downloader = Depends(get_downloader_service),
):
    config = json.loads(req.config) if req.config else {}
    try:
        res = svc.get_status(dtype=req.type, config=config)
        if res:
            return success(data={"success": True, "message": "连接成功"})
        return success(data={"success": False, "message": "连接失败，请检查地址、端口及认证信息"})
    except (ServiceError, DomainError) as e:
        return success(data={"success": False, "message": e.message})
    except Exception as e:
        return success(data={"success": False, "message": f"连接异常：{e!s}"})


@router.post("/downloaders/browse_dirs", response_model=CommonResponse, summary="浏览下载器目录")
def browse_downloader_dirs(
    req: BrowseDownloaderDirsRequest,
    user: str = Depends(require_permission("download:manage")),
    svc: Downloader = Depends(get_downloader_service),
):
    """通过下载器 API 读取其已知目录（默认保存路径、分类路径、已有种子路径）"""
    if not req.type:
        return fail(msg="下载器类型不能为空")
    if isinstance(req.config, dict):
        config = req.config
    else:
        try:
            config = json.loads(req.config) if req.config else {}
        except json.JSONDecodeError:
            return fail(msg="下载器配置格式错误")
    try:
        dirs = svc.get_remote_dirs(dtype=req.type, config=config)
        return success(data={"count": len(dirs), "items": dirs})
    except (ServiceError, DomainError) as e:
        return fail(msg=e.message)
    except Exception as e:
        ExceptionUtils.exception_traceback(e)
        return fail(msg=f"读取下载器目录失败: {e!s}")


@router.post("/settings/update", response_model=CommonResponse, summary="更新下载设置")
def update_download_setting(
    req: UpdateDownloadSettingRequest,
    user: str = Depends(require_permission("download:manage")),
    svc: Downloader = Depends(get_downloader_service),
):
    svc.update_download_setting(
        sid=req.sid,
        name=req.name,
        category=req.category,
        tags=req.tags,
        is_paused=req.is_paused,
        upload_limit=req.upload_limit or 0,
        download_limit=req.download_limit or 0,
        ratio_limit=req.ratio_limit or 0,
        seeding_time_limit=req.seeding_time_limit or 0,
        downloader=req.downloader,
    )
    return success()


@router.post("/settings/default", response_model=CommonResponse, summary="设置默认下载设置")
def set_default_download_setting(
    req: SetDefaultDownloadSettingRequest,
    user: str = Depends(require_permission("download:manage")),
    svc: Downloader = Depends(get_downloader_service),
):
    """设置默认下载设置"""
    if not req.sid:
        return fail(msg="下载设置ID不能为空")
    if svc.set_default_download_setting_id(req.sid):
        return success()
    return fail(msg="设置失败")


@router.post("/downloaders/update", response_model=CommonResponse, summary="更新下载器配置")
def update_downloader(
    req: UpdateDownloaderRequest,
    user: str = Depends(require_permission("download:manage")),
    svc: Downloader = Depends(get_downloader_service),
):
    did = req.did
    name = req.name
    dtype = req.type
    enabled = req.enabled
    transfer = req.transfer
    only_nexus_media = req.only_nexus_media
    match_path = req.match_path
    rmt_mode = req.rmt_mode
    config = req.config
    if config and not isinstance(config, str):
        config = json.dumps(config)
    download_dir = req.download_dir
    if download_dir and not isinstance(download_dir, str):
        download_dir = json.dumps(download_dir)
    svc.update_downloader(
        did=did,
        name=name,
        dtype=dtype,
        enabled=enabled,
        transfer=transfer,
        only_nexus_media=only_nexus_media,
        match_path=match_path,
        rmt_mode=rmt_mode,
        config=config,
        download_dir=download_dir,
    )
    return success()


@router.post("/torrent-remove-tasks/save", response_model=CommonResponse, summary="保存删种任务")
def update_torrent_remove_task(
    req: UpdateTorrentRemoveTaskRequest,
    user: str = Depends(require_permission("download:manage")),
    svc: DownloadService = Depends(get_download_service),
):
    try:
        svc.update_torrent_remove_task(data=req.data)
        return success()
    except (ValidationError, ResourceNotFoundError) as e:
        return fail(msg=e.message)
    except (ServiceError, DomainError) as e:
        return fail(msg=e.message)


@router.post("/tasks", response_model=CommonResponse, summary="获取下载中任务列表")
def get_downloading(
    req: EmptyRequest = EmptyRequest(),
    page: int = 0,
    page_size: int = 0,
    user: str = Depends(require_any_permission("download:view", "download:manage")),
    svc: DownloadService = Depends(get_download_service),
):
    # 未传分页参数时返回旧格式（兼容未重构的前端）
    if page < 1:
        torrents = svc.get_downloading_with_media_info(page=1, page_size=999)["items"]
        return success(data=torrents)
    page = max(1, page)
    page_size = min(max(1, page_size), 200)
    result = svc.get_downloading_with_media_info(page=page, page_size=page_size)
    return success(data=result)


@router.post("/statistics", response_model=CommonResponse, summary="获取下载器实时速率统计")
def get_downloader_statistics(
    req: EmptyRequest = EmptyRequest(),
    user: str = Depends(require_any_permission("download:view", "download:manage")),
    svc: DownloadService = Depends(get_download_service),
):
    return success(data=svc.get_downloader_speed_statistics())


@router.post("/tools/blacklist/clear", response_model=CommonResponse, summary="清空转移黑名单")
def truncate_blacklist(
    req: EmptyRequest = EmptyRequest(),
    user: str = Depends(require_permission("download:manage")),
    svc: FileTransfer = Depends(get_filetransfer_service),
):
    svc.truncate_transfer_blacklist()
    return success()


def _event_stream_generator(q):
    log.info(f"[SSE]客户端已连接下载事件流 (queue_id={hex(id(q))})")
    while True:
        try:
            item = q.get(timeout=1)
            log.debug(f"[SSE]推送事件: {item.get('event')}")
            yield f"event: {item['event']}\ndata: {JsonUtils.dumps(item['data'])}\n\n"
        except queue.Empty:
            yield ": keepalive\n\n"


@router.get("/events", summary="下载事件实时推送 (SSE)")
def download_events(
    user: UserContext = Depends(require_any_permission("download:view", "download:manage")),
):
    return StreamingResponse(_event_stream_generator(download_event_queue), media_type="text/event-stream")
