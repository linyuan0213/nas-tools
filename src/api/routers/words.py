from fastapi import APIRouter, Depends
from pydantic import BaseModel

from api.deps import get_words_service, require_any_permission, require_permission
from app.core.exceptions import (
    DomainError,
    ResourceAlreadyExistsError,
    ResourceNotFoundError,
    ServiceError,
    ValidationError,
)
from app.db.repositories.category_repo_adapter import CategoryConfigRepositoryAdapter
from app.domain.mediatypes import MediaType
from app.schemas.common import CommonResponse
from app.services.words_service import WordsService
from app.utils import ExceptionUtils
from app.utils.response import fail, success

router = APIRouter()


# ---------- Request Models ----------


class AddCustomWordGroupRequest(BaseModel):
    tmdb_id: int
    tmdb_type: str


class AddOrEditCustomWordRequest(BaseModel):
    id: int | None = None
    gid: int
    group_type: str
    new_replaced: str
    new_replace: str
    new_front: str
    new_back: str
    new_offset: str
    new_help: str
    type: str
    season: int | None = None
    enabled: int
    regex: int


class AnalyseImportCodeRequest(BaseModel):
    import_code: str


class CheckCustomWordsRequest(BaseModel):
    ids_info: list[str] | None = None
    flag: str | None = None


class DeleteCustomWordGroupRequest(BaseModel):
    gid: int


class DeleteCustomWordsRequest(BaseModel):
    ids_info: list[str] | None = None


class ExportCustomWordsRequest(BaseModel):
    ids_info: str | None = None
    note: str | None = None


class GetCustomWordRequest(BaseModel):
    wid: int


class ImportCustomWordsRequest(BaseModel):
    import_code: str
    ids_info: str


class GetCategoriesRequest(BaseModel):
    type: str
    id: str | None = None
    value: str | None = None


# ---------- Endpoints ----------


@router.post("/groups/add", response_model=CommonResponse, summary="添加自定义识别词组")
def add_custom_word_group(
    req: AddCustomWordGroupRequest,
    current_user: str = Depends(require_permission("setting:update")),
    svc: WordsService = Depends(get_words_service),
):
    try:
        svc.add_word_group(tmdb_id=req.tmdb_id, tmdb_type=req.tmdb_type)
        return success()
    except (ResourceAlreadyExistsError, ResourceNotFoundError, ValidationError) as e:
        return fail(msg=e.message)
    except (ServiceError, DomainError) as e:
        return fail(msg=e.message)
    except Exception as e:
        ExceptionUtils.exception_traceback(e)
        return fail(msg=f"操作失败: {str(e)}")


@router.post("/words/save", response_model=CommonResponse, summary="保存自定义识别词")
def add_or_edit_custom_word(
    req: AddOrEditCustomWordRequest,
    current_user: str = Depends(require_permission("setting:update")),
    svc: WordsService = Depends(get_words_service),
):
    try:
        svc.add_or_edit_word(
            wid=req.id or 0,
            gid=req.gid,
            group_type=req.group_type,
            replaced=req.new_replaced,
            replace=req.new_replace,
            front=req.new_front,
            back=req.new_back,
            offset=req.new_offset,
            whelp=req.new_help,
            wtype=req.type,
            season=req.season if req.season is not None else -2,
            enabled=req.enabled,
            regex=req.regex,
        )
        return success()
    except (ResourceAlreadyExistsError, ResourceNotFoundError, ValidationError) as e:
        return fail(msg=e.message)
    except (ServiceError, DomainError) as e:
        return fail(msg=e.message)
    except Exception as e:
        ExceptionUtils.exception_traceback(e)
        return fail(msg=f"操作失败: {str(e)}")


@router.post("/words/analyse", response_model=CommonResponse, summary="分析导入代码")
def analyse_import_custom_words_code(
    req: AnalyseImportCodeRequest,
    current_user: str = Depends(require_any_permission("setting:view", "setting:update")),
    svc: WordsService = Depends(get_words_service),
):
    try:
        groups, note = svc.analyse_import_code(req.import_code)
        return success(
            data={
                "groups": [
                    {
                        "id": g.id,
                        "name": g.name,
                        "link": g.link,
                        "type": g.type,
                        "seasons": g.seasons,
                        "words": g.words,
                    }
                    for g in groups
                ],
                "note_string": note,
            }
        )
    except (ServiceError, DomainError) as e:
        return fail(msg=e.message)
    except Exception as e:
        ExceptionUtils.exception_traceback(e)
        return fail(msg=f"操作失败: {str(e)}")


@router.post("/words/check", response_model=CommonResponse, summary="切换识别词状态")
def check_custom_words(
    req: CheckCustomWordsRequest,
    current_user: str = Depends(require_permission("setting:update")),
    svc: WordsService = Depends(get_words_service),
):
    try:
        svc.toggle_words(ids_info=req.ids_info or [], flag=req.flag or "")
        return success()
    except (ResourceAlreadyExistsError, ResourceNotFoundError, ValidationError) as e:
        return fail(msg=e.message)
    except (ServiceError, DomainError) as e:
        return fail(msg=e.message)
    except Exception as e:
        ExceptionUtils.exception_traceback(e)
        return fail(msg="识别词状态设置失败")


@router.post("/groups/delete", response_model=CommonResponse, summary="删除识别词组")
def delete_custom_word_group(
    req: DeleteCustomWordGroupRequest,
    current_user: str = Depends(require_permission("setting:update")),
    svc: WordsService = Depends(get_words_service),
):
    try:
        svc.delete_word_group(req.gid)
        return success(message="")
    except (ServiceError, DomainError) as e:
        return fail(msg=e.message)
    except Exception as e:
        ExceptionUtils.exception_traceback(e)
        return fail(msg=f"操作失败: {str(e)}")


@router.post("/words/delete", response_model=CommonResponse, summary="删除识别词")
def delete_custom_words(
    req: DeleteCustomWordsRequest,
    current_user: str = Depends(require_permission("setting:update")),
    svc: WordsService = Depends(get_words_service),
):
    try:
        svc.delete_words_by_ids(req.ids_info or [])
        return success(message="")
    except (ServiceError, DomainError) as e:
        return fail(msg=e.message)
    except Exception as e:
        ExceptionUtils.exception_traceback(e)
        return fail(msg=f"操作失败: {str(e)}")


@router.post("/words/export", response_model=CommonResponse, summary="导出识别词")
def export_custom_words(
    req: ExportCustomWordsRequest,
    current_user: str = Depends(require_permission("setting:update")),
    svc: WordsService = Depends(get_words_service),
):
    try:
        encoded, _ = svc.export_words(
            ids_info=req.ids_info,
            note=req.note or "",
        )
        return success(data=encoded)
    except (ServiceError, DomainError) as e:
        return fail(msg=e.message)
    except Exception as e:
        ExceptionUtils.exception_traceback(e)
        return fail(msg=f"操作失败: {str(e)}")


@router.post("/words/detail", response_model=CommonResponse, summary="获取识别词详情")
def get_custom_word(
    req: GetCustomWordRequest,
    current_user: str = Depends(require_any_permission("setting:view", "setting:update")),
    svc: WordsService = Depends(get_words_service),
):
    try:
        word = svc.get_word_by_id(req.wid)
        if word:
            return success(
                data={
                    "id": word.id,
                    "replaced": word.replaced,
                    "replace": word.replace,
                    "front": word.front,
                    "back": word.back,
                    "offset": word.offset,
                    "type": word.type,
                    "group_id": word.group_id,
                    "season": word.season,
                    "enabled": word.enabled,
                    "regex": word.regex,
                    "help": word.help,
                }
            )
        return success(data={})
    except (ServiceError, DomainError) as e:
        return fail(msg=e.message)
    except Exception as e:
        ExceptionUtils.exception_traceback(e)
        return fail(msg="查询识别词失败")


@router.post("/words/import", response_model=CommonResponse, summary="导入识别词")
def import_custom_words(
    req: ImportCustomWordsRequest,
    current_user: str = Depends(require_permission("setting:update")),
    svc: WordsService = Depends(get_words_service),
):
    try:
        svc.import_words(import_code=req.import_code, ids_info=req.ids_info)
        return success()
    except (ResourceAlreadyExistsError, ResourceNotFoundError, ValidationError) as e:
        return fail(msg=e.message)
    except (ServiceError, DomainError) as e:
        return fail(msg=e.message)
    except Exception as e:
        ExceptionUtils.exception_traceback(e)
        return fail(msg=f"操作失败: {str(e)}")


@router.post("/categories", response_model=CommonResponse, summary="获取分类")
def get_categories(
    req: GetCategoriesRequest,
    current_user: str = Depends(require_any_permission("setting:view", "setting:update")),
):
    adapter = CategoryConfigRepositoryAdapter()
    entities = adapter.get_all()
    parsed = MediaType.from_string(req.type)
    media_type_map = {MediaType.MOVIE: "movie", MediaType.TV: "tv", MediaType.ANIME: "anime"}
    target = media_type_map.get(parsed, "")
    categories = [e.name for e in entities if e.media_type == target]
    return success(
        data={
            "category": list(categories),
            "id": req.id,
            "value": req.value,
        }
    )


@router.post("/words", response_model=CommonResponse, summary="获取识别词列表")
def get_customwords(
    current_user: str = Depends(require_any_permission("setting:view", "setting:update")),
    svc: WordsService = Depends(get_words_service),
):
    try:
        groups = svc.get_all_word_groups()
        return success(data=groups)
    except (ServiceError, DomainError) as e:
        return fail(msg=e.message)
    except Exception as e:
        ExceptionUtils.exception_traceback(e)
        return fail(msg=f"操作失败: {str(e)}")
