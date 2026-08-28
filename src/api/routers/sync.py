"""
Sync Router — FastAPI 迁移
对应原 web/controllers/sync.py，复用 app/services/sync_service.py
"""

import os.path

from fastapi import APIRouter, Depends
from pydantic import BaseModel

import log
from api.deps import (
    get_filetransfer_service,
    get_sync_service,
    get_thread_executor,
    require_any_permission,
    require_permission,
)
from app.core.constants import RMT_MEDIAEXT
from app.core.error_codes import ErrorCode
from app.core.exceptions import (
    DomainError,
    ResourceNotFoundError,
    ServiceError,
    ValidationError,
)
from app.schemas.common import CommonResponse
from app.services.filetransfer_service import FileTransferService as FileTransfer
from app.services.sync_service import SyncService
from app.utils import ExceptionUtils
from app.utils.response import fail, success

router = APIRouter()


# ---------------------------------------------------------------------------
# Request Models
# ---------------------------------------------------------------------------


class EmptyRequest(BaseModel):
    data: dict | None = None


class AddOrEditSyncPathRequest(BaseModel):
    sid: int | None = None
    source: str | None = None
    dest: str | None = None
    unknown: str | None = None
    mode: str | None = None
    operation: str | None = None
    src_backend: str | None = None
    dst_backend: str | None = None
    compatibility: int | None = None
    rename: int | None = None
    enabled: int | None = None


class CheckSyncPathRequest(BaseModel):
    sid: int | None = None
    flag: str | None = None
    checked: bool | None = None


class DelUnknownPathRequest(BaseModel):
    id: int | list[int] | None = None
    ids: list[int] | None = None


class DeleteFilesRequest(BaseModel):
    files: list[str] | None = None
    backend_id: str = "local"


class DeleteSyncPathRequest(BaseModel):
    id: int | None = None


class GetSubPathRequest(BaseModel):
    directory: str | None = None
    filter: str | None = "ALL"


class RenameRequest(BaseModel):
    logid: int | None = None
    unknown_id: int | None = None
    syncmod: str | None = None
    tmdb: int | None = None
    type: str | None = None
    season: int | None = None
    episode_format: str | None = None
    episode_details: str | None = None
    episode_part: str | None = None
    episode_offset: str | None = None
    min_filesize: int | None = None


class RenameFileRequest(BaseModel):
    path: str | None = None
    name: str | None = None


class RenameUdfRequest(BaseModel):
    inpath: str | None = None
    outpath: str | None = None
    syncmod: str | None = None
    tmdb: int | None = None
    type: str | None = None
    season: int | None = None
    episode_format: str | None = None
    episode_details: str | None = None
    episode_part: str | None = None
    episode_offset: str | None = None
    min_filesize: int | None = None
    src_backend_id: str | None = None


class RunDirectorySyncRequest(BaseModel):
    sid: int | None = None


class TestConnectionRequest(BaseModel):
    command: str | None = None


class UpdateDirectoryRequest(BaseModel):
    oper: str | None = None
    key: str | None = None
    value: str | None = None
    replace_value: str | None = None


class DeleteHistoryRequest(BaseModel):
    logids: list[int] | None = None
    flag: str | None = None


class GetSyncPathRequest(BaseModel):
    sid: int | None = None


class ReIdentificationRequest(BaseModel):
    flag: str | None = None
    ids: list[int] | None = None


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------


@router.post("/paths/save", response_model=CommonResponse, summary="保存同步路径")
def add_or_edit_sync_path(
    req: AddOrEditSyncPathRequest,
    user: str = Depends(require_permission("setting:update")),
    svc: SyncService = Depends(get_sync_service),
):
    try:
        svc.add_or_edit_sync_path(
            sid=req.sid or 0,
            source=req.source or "",
            dest=req.dest or "",
            unknown=req.unknown or "",
            mode=req.mode or "",
            operation=req.operation or "",
            src_backend=req.src_backend or "",
            dst_backend=req.dst_backend or "",
            compatibility=req.compatibility or 0,
            rename=req.rename or 0,
            enabled=req.enabled or 0,
        )
        return success()
    except (ValidationError, ResourceNotFoundError) as e:
        return fail(msg=e.message)
    except (ServiceError, DomainError) as e:
        return fail(msg=e.message)


@router.post("/paths/check", response_model=CommonResponse, summary="检查同步路径")
def check_sync_path(
    req: CheckSyncPathRequest,
    user: str = Depends(require_permission("setting:update")),
    svc: SyncService = Depends(get_sync_service),
):
    try:
        svc.check_sync_path(sid=req.sid or 0, flag=req.flag or "", checked=req.checked or False)
        return success()
    except (ValidationError, ResourceNotFoundError) as e:
        return fail(msg=e.message)
    except (ServiceError, DomainError) as e:
        return fail(msg=e.message)


@router.post("/unknown/delete", response_model=CommonResponse, summary="删除未识别路径")
def del_unknown_path(
    req: DelUnknownPathRequest,
    user: str = Depends(require_permission("setting:update")),
    ft: FileTransfer = Depends(get_filetransfer_service),
):
    tid = req.id if req.id is not None else req.ids
    if isinstance(tid, list):
        valid_tids = [t for t in tid if t]
        if valid_tids:
            ft.delete_transfer_unknowns(valid_tids)
        return success()
    else:
        retcode = ft.delete_transfer_unknown(tid)
        if retcode == 0:
            return success()
        return fail(code=ErrorCode.SYNC_FAILED)


@router.post("/files/delete", response_model=CommonResponse, summary="删除文件")
def delete_files(
    req: DeleteFilesRequest,
    user: str = Depends(require_permission("setting:update")),
    ft: FileTransfer = Depends(get_filetransfer_service),
):
    files = req.files
    if files:
        for file in files:
            try:
                ft.delete_media_file(
                    filedir=os.path.dirname(file),
                    filename=os.path.basename(file),
                    backend_id=req.backend_id,
                )
                log.info(f"[Delete]删除成功: {file}")
            except (ValidationError, ResourceNotFoundError, ServiceError) as e:
                log.error(f"[Delete]删除失败: {file} - {e.message}")
    return success()


@router.post("/paths/delete", response_model=CommonResponse, summary="删除同步路径")
def delete_sync_path(
    req: DeleteSyncPathRequest,
    user: str = Depends(require_permission("setting:update")),
    svc: SyncService = Depends(get_sync_service),
):
    svc.delete_sync_path(req.id or 0)
    return success()


@router.post("/paths/sub", response_model=CommonResponse, summary="获取子路径")
def get_sub_path(
    req: GetSubPathRequest,
    user: str = Depends(require_any_permission("setting:view", "setting:update")),
    svc: SyncService = Depends(get_sync_service),
):
    try:
        ft = req.filter or "ALL"
        r = svc.get_sub_path(directory=req.directory or "", ft=ft)
    except (ServiceError, DomainError) as e:
        return fail(code=ErrorCode.SYNC_FAILED, msg=e.message)
    except Exception as e:
        ExceptionUtils.exception_traceback(e)
        return fail(code=ErrorCode.SYNC_FAILED, msg=f"加载路径失败: {e!s}")
    return success(data={"count": len(r), "items": r})


@router.post("/rename", response_model=CommonResponse, summary="手动转移")
def rename(
    req: RenameRequest,
    user: str = Depends(require_permission("setting:update")),
    svc: SyncService = Depends(get_sync_service),
    ft: FileTransfer = Depends(get_filetransfer_service),
):
    path = dest_dir = None
    syncmod = req.syncmod or ""
    logid = req.logid
    if logid:
        transinfo = svc.get_transfer_info_by_id(logid)
        if transinfo:
            path = os.path.join(str(transinfo.SOURCE_PATH), str(transinfo.SOURCE_FILENAME))
            dest_dir = str(transinfo.DEST)
        else:
            return fail(code=ErrorCode.RESOURCE_NOT_FOUND, msg="未查询到转移日志记录")
    else:
        unknown_id = req.unknown_id
        if unknown_id:
            unknowninfo = svc.get_unknown_info_by_id(unknown_id)
            if unknowninfo:
                path = str(unknowninfo.PATH)
                dest_dir = str(unknowninfo.DEST)
            else:
                return fail(code=ErrorCode.RESOURCE_NOT_FOUND, msg="未查询到未识别记录")
    if not dest_dir:
        dest_dir = ""
    if not path:
        return fail(code=ErrorCode.PARAM_VALIDATION_FAILED, msg="输入路径有误")

    tmdbid = req.tmdb
    mtype = req.type
    season = req.season
    episode_format = req.episode_format
    episode_details = req.episode_details
    episode_part = req.episode_part
    episode_offset = req.episode_offset
    min_filesize = req.min_filesize
    media_type = svc.build_media_type(mtype or "")
    need_fix_all = False
    if os.path.splitext(path)[-1].lower() in RMT_MEDIAEXT and episode_format:
        path = os.path.dirname(path)
        need_fix_all = True

    result = svc.manual_transfer(
        inpath=path,
        syncmod=syncmod,
        outpath=dest_dir,
        media_type=media_type,
        episode_format=episode_format,
        episode_details=episode_details,
        episode_part=episode_part,
        episode_offset=episode_offset,
        min_filesize=min_filesize,
        tmdbid=tmdbid,
        season=season,
        need_fix_all=need_fix_all,
    )
    if result.success:
        if not need_fix_all and not logid:
            ft.update_transfer_unknown_state(path)
        return success(message="转移成功")
    return fail(code=ErrorCode.SYNC_FAILED, msg=result.message)


@router.post("/rename/file", response_model=CommonResponse, summary="重命名文件")
def rename_file(
    req: RenameFileRequest,
    user: str = Depends(require_permission("setting:update")),
    svc: SyncService = Depends(get_sync_service),
):
    result = svc.rename_file(path=req.path or "", name=req.name or "")
    if result.success:
        return success()
    return fail(code=ErrorCode.SYNC_FAILED, msg=result.message)


@router.post("/rename/udf", response_model=CommonResponse, summary="自定义转移")
def rename_udf(
    req: RenameUdfRequest,
    user: str = Depends(require_permission("setting:update")),
    svc: SyncService = Depends(get_sync_service),
):
    inpath = req.inpath
    src_backend_id = req.src_backend_id or "local"
    if src_backend_id == "local":
        if not os.path.exists(inpath or ""):
            return fail(code=ErrorCode.PARAM_VALIDATION_FAILED, msg="输入路径不存在")
    else:
        if not svc.remote_path_exists(inpath or "", src_backend_id):
            return fail(code=ErrorCode.PARAM_VALIDATION_FAILED, msg="输入路径不存在")
    outpath = req.outpath
    syncmod = req.syncmod or ""
    tmdbid = req.tmdb
    mtype = req.type
    season = req.season
    episode_format = req.episode_format
    episode_details = req.episode_details
    episode_part = req.episode_part
    episode_offset = req.episode_offset
    min_filesize = req.min_filesize
    media_type = svc.build_media_type(mtype or "")

    result = svc.manual_transfer(
        inpath=inpath or "",
        syncmod=syncmod,
        outpath=outpath,
        media_type=media_type,
        episode_format=episode_format,
        episode_details=episode_details,
        episode_part=episode_part,
        episode_offset=episode_offset,
        min_filesize=min_filesize,
        tmdbid=tmdbid,
        season=season,
        src_backend_id=src_backend_id,
    )
    if result.success:
        return success(message="转移成功")
    return fail(code=ErrorCode.SYNC_FAILED, msg=result.message)


@router.post("/run", response_model=CommonResponse, summary="执行目录同步")
def run_directory_sync(
    req: RunDirectorySyncRequest,
    user: str = Depends(require_permission("setting:update")),
    svc: SyncService = Depends(get_sync_service),
    thread_executor=Depends(get_thread_executor),
):
    thread_executor.submit(svc.transfer_sync, req.sid)
    return success(message="执行成功")


@router.post("/paths/test_connection", response_model=CommonResponse, summary="测试连接")
def test_connection(
    req: TestConnectionRequest,
    user: str = Depends(require_permission("setting:update")),
    svc: SyncService = Depends(get_sync_service),
):
    result = svc.test_connection(command=req.command)
    if result.success:
        return success()
    return fail(code=ErrorCode.OPERATION_FAILED)


@router.post("/directories/update", response_model=CommonResponse, summary="更新目录")
def update_directory(
    req: UpdateDirectoryRequest,
    user: str = Depends(require_permission("setting:update")),
    svc: SyncService = Depends(get_sync_service),
):
    result = svc.update_directory(
        oper=req.oper or "",
        key=req.key or "",
        value=req.value or "",
        replace_value=req.replace_value,
    )
    if result.success:
        return success()
    return fail()


@router.post("/history/delete", response_model=CommonResponse, summary="删除同步历史")
def delete_history(
    req: DeleteHistoryRequest,
    user: str = Depends(require_permission("setting:update")),
    svc: FileTransfer = Depends(get_filetransfer_service),
):
    logids = req.logids or []
    flag = req.flag
    svc.delete_history(logids=logids, flag=flag)
    return success()


@router.post("/paths", response_model=CommonResponse, summary="获取同步路径")
def get_sync_path(
    req: GetSyncPathRequest,
    user: str = Depends(require_any_permission("setting:view", "setting:update")),
    svc: SyncService = Depends(get_sync_service),
):
    sync_path = svc.get_sync_paths(sid=str(req.sid) if req.sid is not None else None)
    return success(data=sync_path)


@router.post("/reidentify", response_model=CommonResponse, summary="重新识别")
def re_identification(
    req: ReIdentificationRequest,
    user: str = Depends(require_permission("setting:update")),
    svc: SyncService = Depends(get_sync_service),
):
    result = svc.re_identify_items(flag=req.flag or "", ids=req.ids or [])
    if result.success:
        return success(message=result.message)
    return fail(code=ErrorCode.SYNC_FAILED, msg=result.message)
