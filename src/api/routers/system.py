"""
System Router — FastAPI 迁移
对应原 web/controllers/system.py，复用 app/services/system_service.py
"""

import asyncio
import json
import os
import time
import uuid
from pathlib import Path

from fastapi import APIRouter, Depends, File, Query, Request, UploadFile
from fastapi.responses import FileResponse, Response, StreamingResponse
from pydantic import BaseModel

import log
from api.deps import (
    get_backup_restore_service,
    get_config_reloader,
    get_config_service,
    get_config_update_service,
    get_current_user,
    get_indexer_config_service,
    get_indexer_service,
    get_media_server_config_service,
    get_message_sender_service,
    get_message_service,
    get_net_test_service,
    get_progress_service,
    get_system_config_service,
    get_system_info_service,
    get_system_lifecycle_service,
    get_system_scheduler_service,
    get_thread_executor,
    get_user_manage_service,
    get_web_search_service,
    require_any_permission,
    require_permission,
)
from app.agent.providers import list_embedding_models, validate_api_url
from app.agent.providers.base import ProviderConfig
from app.agent.providers.gemini import GeminiProvider
from app.agent.providers.ollama import OllamaProvider
from app.agent.providers.openai import OpenAIProvider
from app.core.error_codes import ErrorCode
from app.core.exceptions import AuthError, DomainError, PermissionDenied, ResourceNotFoundError, ServiceError
from app.core.root_path import get_project_root
from app.core.system_config import SystemConfig
from app.domain.enums import SystemConfigKey
from app.indexer.registry import get_all_clients as get_all_indexers
from app.infrastructure.cache_system import TokenCache
from app.infrastructure.cache_system.manager import get_cache_manager
from app.infrastructure.progress import ProgressTracker
from app.infrastructure.security import generate_password_hash
from app.infrastructure.temp import temp_manager
from app.mediaserver.registry import get_all_clients as get_all_mediaservers
from app.message.registry import get_all_clients
from app.message.switches import MESSAGE_SWITCHES
from app.message.templates import DEFAULT_MESSAGE_TEMPLATES
from app.schemas.auth import UserContext
from app.schemas.common import CommonResponse
from app.services.auth_service import AuthService
from app.services.config_reloader import ConfigReloader
from app.services.indexer_service import IndexerService
from app.services.log_search_service import LogSearchService
from app.services.log_streaming_service import LogStreamingService
from app.services.site_config_updater import SiteConfigUpdater
from app.services.system.config import IndexerConfigService
from app.services.system.lifecycle import SystemLifecycleService
from app.services.system_service import (
    MessageClientService,
    MessageSenderService,
    SystemInfoService,
    get_commands,
    restart_server,
)
from app.services.system_service import (
    backup as do_backup,
)
from app.utils import ExceptionUtils
from app.utils.response import fail, success
from app.utils.system_utils import SystemUtils
from log import LOG_BUFFER

router = APIRouter()


# ---------------------------------------------------------------------------
# Pydantic Request Models
# ---------------------------------------------------------------------------


class EmptyRequest(BaseModel):
    """兼容前端 payload 中无 data 字段或 data 为空的情况"""

    data: dict | None = None


class MessageClientRequest(BaseModel):
    flag: str | None = None
    cid: int | None = None
    type: str | None = None
    checked: bool | None = None
    name: str | None = None
    config: str | None = None
    switches: str | None = None
    interactive: int | None = None
    enabled: int | None = None
    templates: str | None = None


class NetTestRequest(BaseModel):
    target: str | None = None


class IndexerConfigRequest(BaseModel):
    data: dict


class MediaServerConfigRequest(BaseModel):
    data: dict


class SchedulerRequest(BaseModel):
    item: str | None = None


class SearchRequest(BaseModel):
    search_word: str | None = None
    unident: bool | None = None
    filters: dict | None = None
    tmdbid: str | int | None = None
    media_type: str | None = None


class SystemConfigRequest(BaseModel):
    key: str | None = None
    value: str | None = None


class ScraperConfigRequest(BaseModel):
    scraper_nfo: dict | None = None
    scraper_pic: dict | None = None


class TestMessageClientRequest(BaseModel):
    type: str | None = None
    config: str | None = None


class UpdateAllConfigRequest(BaseModel):
    conf: dict | None = None
    db: dict | None = None
    test: bool | None = None


class UpdateConfigRequest(BaseModel):
    data: dict


class BackupRequest(BaseModel):
    file_name: str | None = None


class UserManagerRequest(BaseModel):
    oper: str | None = None
    name: str | None = None
    password: str | None = None
    pris: str | None = None


class ProgressRequest(BaseModel):
    type: str | None = None


class SendCustomMessageRequest(BaseModel):
    message_clients: list | None = None
    title: str | None = None
    text: str | None = None
    image: str | None = None


class SendPluginMessageRequest(BaseModel):
    title: str | None = None
    text: str | None = None
    image: str | None = None


class AgentModelsRequest(BaseModel):
    provider_name: str
    api_url: str | None = None
    api_key: str | None = None


class DocReadRequest(BaseModel):
    """读取内置文档请求"""

    name: str


# ---------------------------------------------------------------------------
# 辅助函数：统一从 payload 中提取 data
# ---------------------------------------------------------------------------


def _extract_data(payload: BaseModel) -> dict:
    """从 Pydantic 模型中提取 data 字段，若不存在则返回模型本身的 dict"""
    d = payload.model_dump()
    if "data" in d and d["data"] is not None:
        return d["data"]
    return d


# ---------------------------------------------------------------------------
# Router Endpoints
# ---------------------------------------------------------------------------


@router.post("/info", response_model=CommonResponse, summary="获取系统基本信息")
def system_info(
    current_user: UserContext = Depends(require_any_permission("setting:view", "setting:update")),
    svc: SystemInfoService = Depends(get_system_info_service),
):
    """获取系统基本信息（版本、运行时长、Python版本等）"""
    info = svc.get_system_info()
    return success(
        data={
            "version": info.version,
            "python_version": info.python_version,
            "platform": info.platform,
            "uptime": info.uptime,
            "uptime_seconds": info.uptime_seconds,
            "start_time": info.start_time,
            "memory_mb": info.memory_mb,
        }
    )


@router.post("/check_message_client", response_model=CommonResponse, summary="切换消息客户端设置")
def check_message_client(
    req: MessageClientRequest,
    current_user: UserContext = Depends(require_any_permission("setting:view", "setting:update")),
    svc: MessageClientService = Depends(get_message_service),
):
    flag = req.flag
    if flag == "interactive":
        svc.toggle_interactive(cid=req.cid or 0, ctype=req.type or "", checked=req.checked or False)
        return success()
    elif flag == "enable":
        svc.toggle_enable(cid=req.cid or 0, checked=req.checked or False)
        return success()
    else:
        return fail()


@router.post("/message_clients/delete", response_model=CommonResponse, summary="删除消息客户端")
def delete_message_client(
    req: MessageClientRequest,
    current_user: UserContext = Depends(require_permission("setting:update")),
    svc: MessageClientService = Depends(get_message_service),
):
    if svc.delete_client(cid=req.cid or 0):
        return success()
    else:
        return fail()


@router.post("/message_clients", response_model=CommonResponse, summary="获取消息客户端列表")
def get_message_client(
    req: MessageClientRequest,
    current_user: UserContext = Depends(require_permission("setting:update")),
    svc: MessageClientService = Depends(get_message_service),
):
    data = svc.get_client(cid=req.cid)
    # 确保 switches 始终是列表（兼容旧脏数据）
    all_switch_keys = set(MESSAGE_SWITCHES.keys())
    if isinstance(data, dict):
        for client in data.values():
            switches = client.get("switches")
            if isinstance(switches, str):
                client["switches"] = [
                    s.strip() for s in switches.split(",") if s.strip() and s.strip() in all_switch_keys
                ]
            elif not isinstance(switches, list):
                client["switches"] = []
    return success(data=data)


@router.post("/message_clients/config", response_model=CommonResponse, summary="获取消息客户端配置模板")
def get_message_client_config(
    current_user: UserContext = Depends(require_permission("setting:update")),
):
    """获取消息通知配置模板（channels + switches），field.id 统一为 config key"""
    clients = {}
    for cls in get_all_clients():
        if not hasattr(cls, "schema") or not cls.schema:
            continue
        schema_dict = (
            cls.config_schema.to_dict()
            if hasattr(cls, "config_schema") and cls.config_schema
            else {"name": cls.schema, "config": {}}
        )
        clients[cls.schema] = schema_dict
    switches = dict(MESSAGE_SWITCHES)
    return success(
        data={
            "channels": clients,
            "switches": switches,
        }
    )


@router.get("/message_clients/templates/defaults", response_model=CommonResponse, summary="获取消息通知默认模板")
def get_message_client_default_templates(
    current_user: UserContext = Depends(require_permission("setting:update")),
):
    """获取消息通知默认模板"""
    return success(data=DEFAULT_MESSAGE_TEMPLATES)


@router.post("/net_test", response_model=CommonResponse, summary="网络连通性测试")
def net_test(
    req: NetTestRequest,
    current_user: UserContext = Depends(require_any_permission("setting:view", "setting:update")),
    svc=Depends(get_net_test_service),
):
    result = svc.test(target=req.target or "")
    return success(data={"res": result.success, "time": f"{result.time_ms} 毫秒"})


@router.post("/db/reset_version", response_model=CommonResponse, summary="重置数据库版本")
def reset_db_version(
    req: EmptyRequest = EmptyRequest(),
    current_user: UserContext = Depends(require_permission("setting:update")),
    svc=Depends(get_system_config_service),
):
    try:
        svc.reset_db_version()
        return success()
    except (ServiceError, DomainError) as e:
        return fail(msg=e.message)
    except Exception as e:
        ExceptionUtils.exception_traceback(e)
        return fail(msg=str(e))


@router.post("/restart", response_model=CommonResponse, summary="重启系统")
def restart(
    req: EmptyRequest = EmptyRequest(),
    current_user: UserContext = Depends(require_permission("setting:update")),
    svc: SystemLifecycleService = Depends(get_system_lifecycle_service),
):
    restart_server(system_lifecycle_service=svc)
    return success()


@router.post("/backup", summary="备份配置文件")
def backup(
    current_user: UserContext = Depends(require_permission("setting:update")),
):
    """备份配置文件"""

    zip_file = do_backup()
    if not zip_file:
        return fail(msg="创建备份失败")
    return FileResponse(zip_file, filename=os.path.basename(zip_file))


@router.post("/backup/upload", response_model=CommonResponse, summary="上传备份文件")
async def backup_upload(
    file: UploadFile = File(...),
    current_user: UserContext = Depends(require_permission("setting:update")),
):
    """上传备份文件"""
    try:
        file_path = Path(temp_manager.get_temp_path()) / (file.filename or "")
        contents = await file.read()
        with open(file_path, "wb") as f:
            f.write(contents)
        return success(data={"filepath": str(file_path)})
    except (ServiceError, DomainError) as e:
        return fail(msg=e.message)
    except Exception as e:
        return fail(msg=str(e))


@router.post("/backup/restore", response_model=CommonResponse, summary="恢复备份")
def restory_backup(
    req: BackupRequest,
    current_user: UserContext = Depends(require_permission("setting:update")),
    svc=Depends(get_backup_restore_service),
):
    filename = req.file_name
    result = svc.restore_from_backup(filename)
    if result.success:
        return success(data=[], message=result.message)
    return fail(msg=result.message)


@router.post("/indexers", response_model=CommonResponse, summary="获取索引器配置信息")
def get_indexers(
    current_user: UserContext = Depends(require_permission("setting:update")),
    idx_svc: IndexerService = Depends(get_indexer_service),
    cfg: SystemConfig = Depends(get_system_config_service),
    idx_config_svc: IndexerConfigService = Depends(get_indexer_config_service),
):
    """获取索引器配置信息（外部索引器配置、内置站点列表、当前配置）"""
    indexers = idx_svc.get_builtin_indexers(check=False)
    indexer_list = [vars(item) for item in indexers]
    private_count = len([item for item in indexer_list if not item.get("public")])
    public_count = len([item for item in indexer_list if item.get("public")])
    indexer_sites = cfg.get(SystemConfigKey.UserIndexerSites) or []
    search_indexer = cfg.get(SystemConfigKey.SearchIndexer) or "builtin"

    all_configs = idx_config_svc.get_all_configs()

    # 索引器状态：{ client_id: { enabled, configured } }
    indexer_status: dict[str, dict] = {}
    for c in all_configs:
        item_cfg = c.get("config") or {}
        configured = c["client_id"] == "builtin" or bool(item_cfg.get("host"))
        indexer_status[c["client_id"]] = {
            "enabled": c["enabled"],
            "configured": configured,
        }
    # 未配置的注册索引器也加入列表中
    for cls in get_all_indexers():
        cid = getattr(cls, "client_id", "")
        if cid and cid not in indexer_status:
            indexer_status[cid] = {"enabled": False, "configured": cid == "builtin"}

    # 构建 indexer_config 兼容格式
    indexer_config = {}
    for c in all_configs:
        if c["config"]:
            indexer_config[c["client_id"]] = c["config"]

    return success(
        data={
            "indexers": indexer_list,
            "private_count": private_count,
            "public_count": public_count,
            "indexer_conf": {
                cls.client_id: cls.config_schema.to_dict()
                for cls in get_all_indexers()
                if hasattr(cls, "client_id") and cls.client_id and hasattr(cls, "config_schema") and cls.config_schema
            },
            "indexer_sites": indexer_sites,
            "indexer_status": indexer_status,
            "search_indexer": search_indexer,
            "indexer_config": indexer_config,
            "third_party_sites": idx_svc.get_third_party_sites(),
        }
    )


@router.post("/indexers/test", response_model=CommonResponse, summary="测试索引器连接")
def test_indexer(
    req: IndexerConfigRequest,
    current_user: UserContext = Depends(require_permission("setting:update")),
    svc=Depends(get_indexer_config_service),
):
    """测试索引器连接"""
    data = dict(req.data)
    data["test"] = True
    result = svc.save_config(data)
    if result.success:
        return success(message=result.msg)
    return fail(msg=result.msg)


@router.post("/indexers/config", response_model=CommonResponse, summary="保存索引器配置")
def save_indexer_config(
    req: IndexerConfigRequest,
    current_user: UserContext = Depends(require_permission("setting:update")),
    svc=Depends(get_indexer_config_service),
):
    result = svc.save_config(req.data)
    if result.success:
        return success()
    return fail(msg=result.msg)


@router.post("/mediaservers", response_model=CommonResponse, summary="获取媒体服务器配置信息")
def get_mediaservers(
    current_user: UserContext = Depends(require_permission("setting:update")),
    svc=Depends(get_media_server_config_service),
):
    """获取媒体服务器配置信息"""
    info = svc.get_media_servers_info()
    mediaserver_conf = {}
    for cls in get_all_mediaservers():
        if hasattr(cls, "client_id") and cls.client_id and hasattr(cls, "config_schema") and cls.config_schema:
            mediaserver_conf[cls.client_id] = cls.config_schema.to_dict()
    return success(
        data={
            "servers": info["servers"],
            "default_server": info["default_server"],
            "mediaserver_conf": mediaserver_conf,
        }
    )


@router.post("/mediaservers/test", response_model=CommonResponse, summary="测试媒体服务器连接")
def test_mediaserver(
    req: MediaServerConfigRequest,
    current_user: UserContext = Depends(require_permission("setting:update")),
    svc=Depends(get_media_server_config_service),
):
    """测试媒体服务器连接"""
    data = dict(req.data)
    data["test"] = True
    result = svc.save_config(data)
    if result.success:
        return success(message=result.msg)
    return fail(msg=result.msg)


@router.post("/mediaservers/config", response_model=CommonResponse, summary="保存媒体服务器配置")
def save_mediaserver_config(
    req: MediaServerConfigRequest,
    current_user: UserContext = Depends(require_permission("setting:update")),
    svc=Depends(get_media_server_config_service),
):
    result = svc.save_config(req.data)
    if result.success:
        return success()
    return fail(msg=result.msg)


@router.post("/scheduler/run", response_model=CommonResponse, summary="运行定时任务")
def sch(
    req: SchedulerRequest,
    current_user: UserContext = Depends(require_permission("setting:update")),
    svc=Depends(get_system_scheduler_service),
):
    try:
        msg = svc.start_service(item=req.item)
        return success(data={"msg": msg, "item": req.item})
    except ResourceNotFoundError as e:
        return fail(msg=e.message)


@router.post("/search", response_model=CommonResponse, summary="WEB资源搜索")
def search(
    req: SearchRequest,
    current_user: UserContext = Depends(require_any_permission("setting:view", "setting:update")),
    svc=Depends(get_web_search_service),
    executor=Depends(get_thread_executor),
):
    """
    WEB资源搜索（后台执行，前端轮询进度和结果）
    """
    session_id = str(uuid.uuid4())
    TokenCache.delete("search")
    TokenCache.set(f"search_session:{current_user.user_id}", session_id, ttl=1800)
    search_word = req.search_word
    ident_flag = not req.unident
    executor.submit(
        svc.search,
        search_word=search_word,
        ident_flag=ident_flag,
        filters=req.filters,
        tmdbid=req.tmdbid,
        media_type=req.media_type,
        session_id=session_id,
    )
    return success(data={"session_id": session_id})


@router.get("/search/progress/{session_id}", summary="SSE 搜索进度")
async def search_progress(session_id: str):
    """以 SSE 流推送搜索进度（per-session + 全局详细进度）"""

    async def event_stream():
        tracker = ProgressTracker()
        last_val = -1
        loop = asyncio.get_running_loop()
        deadline = loop.time() + 600
        missing_since: float | None = None
        while loop.time() < deadline:
            detail = tracker.get_process(f"search:{session_id}")
            if not detail:
                # 会话无进度记录：后端重启后内存进度已清空，或会话早已结束。
                # 宽限 3s 覆盖“SSE 先于搜索任务启动”的竞态，超时关闭流让前端回源已持久化的结果
                now = loop.time()
                if missing_since is None:
                    missing_since = now
                elif now - missing_since > 3:
                    break
                await asyncio.sleep(0.3)
                continue
            missing_since = None
            val = detail.get("value", 0)
            if val != last_val:
                last_val = val
                yield f"data: {json.dumps(detail, ensure_ascii=False)}\n\n"
            # 已结束（enable=False 且 value>=100）→ 关闭流
            if not detail.get("enable") and val >= 100:
                break
            await asyncio.sleep(0.3)

    return StreamingResponse(event_stream(), media_type="text/event-stream")


@router.get("/caches", response_model=CommonResponse, summary="获取缓存列表与统计")
def list_caches(
    current_user: UserContext = Depends(require_permission("setting:view")),
):
    """列出所有缓存及其键数/占用统计"""
    manager = get_cache_manager()
    stats = manager.get_stats()
    names = manager.get_all_cache_names()
    data = []
    for name in names:
        stat = stats.get(name) or {}
        if isinstance(stat, dict) and "error" in stat:
            data.append({"name": name, "keys": 0, "error": stat["error"]})
        else:
            data.append({"name": name, **stat})
    return success(data=data)


class CacheClearRequest(BaseModel):
    name: str | None = None


@router.post("/caches/clear", response_model=CommonResponse, summary="清理缓存（按名或全部）")
def clear_cache(
    req: CacheClearRequest,
    current_user: UserContext = Depends(require_permission("setting:update")),
):
    """按缓存名清理，未指定则清空全部缓存"""
    manager = get_cache_manager()
    if req.name:
        cleared = manager.cache_clear(req.name)
        if not cleared:
            return fail(msg=f"缓存不存在: {req.name}")
        return success(message=f"已清理缓存: {req.name}")
    manager.clear_all()
    return success(message="已清理全部缓存")


def _flatten_config(cfg: dict, prefix: str = "") -> dict:
    """将嵌套配置字典扁平化为 dot-notation 键值对"""
    result = {}
    for key, value in cfg.items():
        full_key = f"{prefix}.{key}" if prefix else key
        if isinstance(value, dict):
            result.update(_flatten_config(value, full_key))
        else:
            result[full_key] = value
    return result


@router.post("/config", response_model=CommonResponse, summary="设置系统配置")
def set_system_config(
    req: SystemConfigRequest,
    current_user: UserContext = Depends(require_permission("setting:update")),
    svc=Depends(get_system_config_service),
):
    if svc.set_config(req.key, req.value):
        return success()
    return fail()


@router.post("/config/all", response_model=CommonResponse, summary="获取所有系统配置")
def get_all_config(
    current_user: UserContext = Depends(require_any_permission("setting:view", "setting:update")),
    svc=Depends(get_config_service),
):
    """获取所有系统配置（扁平化，供基础设置页面使用）"""
    cfg = svc.get_config() or {}
    flat = _flatten_config(cfg)
    # 代理特殊处理：http:// 去掉 scheme 展示，其他（https/socks5）保留
    proxies = cfg.get("app", {}).get("proxies", {})
    http_proxy = proxies.get("http") if isinstance(proxies, dict) else None
    if http_proxy:
        flat["app.proxies"] = http_proxy.removeprefix("http://")
    return success(data=flat)


@router.post("/config/scraper", response_model=CommonResponse, summary="获取刮削配置")
def get_scraper_config(
    current_user: UserContext = Depends(require_any_permission("setting:view", "setting:update")),
    svc=Depends(get_system_config_service),
):
    cfg = svc.get(SystemConfigKey.UserScraperConf)
    if isinstance(cfg, str):
        try:
            cfg = json.loads(cfg)
            # 兼容旧版双重 JSON 编码
            if isinstance(cfg, str):
                cfg = json.loads(cfg)
        except Exception:
            cfg = None
    return success(data=cfg or {})


@router.post("/config/scraper/save", response_model=CommonResponse, summary="设置刮削配置")
def set_scraper_config(
    req: ScraperConfigRequest,
    current_user: UserContext = Depends(require_permission("setting:update")),
    svc=Depends(get_system_config_service),
):
    value = req.dict(exclude_none=True)
    svc.set(SystemConfigKey.UserScraperConf, value)
    return success()


@router.post("/message_clients/test", response_model=CommonResponse, summary="测试消息客户端连接")
def test_message_client(
    req: TestMessageClientRequest,
    current_user: UserContext = Depends(require_permission("setting:update")),
    svc: MessageClientService = Depends(get_message_service),
):
    config = json.loads(req.config) if req.config else {}
    if svc.test_connection(ctype=req.type or "", config=config):
        return success()
    else:
        return fail()


@router.post("/config/update", response_model=CommonResponse, summary="更新系统配置")
def update_config(
    req: UpdateConfigRequest,
    current_user: UserContext = Depends(require_permission("setting:update")),
    svc=Depends(get_config_update_service),
    reloader: ConfigReloader = Depends(get_config_reloader),
):
    result = svc.update_config(req.data)
    if result.success and not result.test_mode:
        reloader.reload()
    if result.success:
        return success()
    return fail()


@router.post("/agent/models", response_model=CommonResponse, summary="查询 LLM 模型列表")
def list_agent_models(
    req: AgentModelsRequest,
    current_user: UserContext = Depends(require_permission("setting:update")),
):
    """查询 LLM Provider 支持的模型列表"""

    if not req.api_url or not req.api_key:
        return success(data=[])

    try:
        validate_api_url(req.api_url)
    except ValueError as e:
        return fail(msg=str(e))

    config = ProviderConfig(
        name=req.provider_name,
        api_url=req.api_url,
        api_key=req.api_key,
        model="",
    )

    try:
        if req.provider_name == "ollama":
            provider = OllamaProvider(config)
        elif req.provider_name == "gemini":
            provider = GeminiProvider(config)
        else:
            provider = OpenAIProvider(config)
        models = provider.list_models()
        return success(data=models)
    except (ServiceError, DomainError) as e:
        return fail(msg=e.message)
    except Exception as e:
        log.warn(f"[Agent]查询模型列表失败: {e}")
        return fail(msg=str(e))


@router.post("/agent/embedding_models", response_model=CommonResponse, summary="查询 Embedding 模型列表")
def list_agent_embedding_models(
    req: AgentModelsRequest,
    current_user: UserContext = Depends(require_permission("setting:update")),
):
    """查询 Embedding Provider 支持的模型列表（动态拉取，失败回退精选）"""
    models = list_embedding_models(
        provider_name=req.provider_name,
        api_url=req.api_url or "",
        api_key=req.api_key or "",
    )
    return success(data=models)


@router.post("/docs/read", response_model=CommonResponse, summary="读取内置文档 Markdown")
def read_system_doc(
    req: DocReadRequest,
    current_user: UserContext = Depends(require_permission("agent:view")),
):
    """读取内置 docs/*.md 文档内容（供消息中心"相关文档"链接查看，防目录穿越）"""
    name = Path(req.name).name
    if not name.endswith(".md"):
        name = f"{name}.md"
    doc_path = get_project_root() / "docs" / name
    if not doc_path.is_file():
        return fail(msg=f"文档不存在: {name}")
    return success(data={"name": name, "content": doc_path.read_text(encoding="utf-8")})


@router.post("/message_clients/update", response_model=CommonResponse, summary="更新消息客户端")
def update_message_client(
    req: MessageClientRequest,
    current_user: UserContext = Depends(require_permission("setting:update")),
    svc: MessageClientService = Depends(get_message_service),
):
    svc.upsert_client(
        name=req.name or "",
        cid=req.cid or 0,
        ctype=req.type or "",
        config=req.config or "",
        switches=req.switches or "",
        interactive=req.interactive or 0,
        enabled=req.enabled or 0,
        templates=req.templates or "",
    )
    return success()


@router.post("/users/legacy", response_model=CommonResponse, summary="用户管理")
def user_manager(
    req: UserManagerRequest,
    current_user: UserContext = Depends(require_permission("setting:update")),
    svc=Depends(get_user_manage_service),
):
    oper = req.oper
    name = req.name
    if oper == "add":
        password = generate_password_hash(str(req.password))
        result = svc.add_user(name=name, password=password)
    else:
        result = svc.delete_user(name=name)

    if result.success:
        return success(data={"success": False})
    return fail(code=ErrorCode.OPERATION_FAILED, success=False, message=result.message or "操作失败")


@router.post("/commands", response_model=CommonResponse, summary="获取系统命令列表")
def system_commands(
    current_user: UserContext = Depends(require_any_permission("setting:view", "setting:update")),
):
    """获取系统命令列表"""
    cmds = get_commands()
    return success(data=cmds)


@router.post("/status", response_model=CommonResponse, summary="获取系统状态")
def system_status(
    req: EmptyRequest = EmptyRequest(),
    current_user: UserContext = Depends(require_any_permission("setting:view", "setting:update")),
    info_svc=Depends(get_system_info_service),
):
    info = info_svc.get_system_info()
    return success(
        data={
            "version": info.version,
            "uptime": info.uptime_seconds,
            "python_version": info.python_version,
        }
    )


@router.post("/refresh", response_model=CommonResponse, summary="获取任务进度")
def refresh_process(
    req: ProgressRequest,
    user: str = Depends(require_any_permission("setting:view", "setting:update")),
    svc=Depends(get_progress_service),
):
    result = svc.get_progress(ptype=req.type)
    return success(
        data={
            "value": result.value,
            "text": result.text or "正在处理...",
            "enable": result.enable,
            "exists": result.exists,
        }
    )


@router.post("/messages/send", response_model=CommonResponse, summary="发送自定义消息")
def send_custom_message(
    req: SendCustomMessageRequest,
    user: str = Depends(require_permission("setting:update")),
    svc: MessageSenderService = Depends(get_message_sender_service),
):
    result = svc.send_custom_message(
        clients=req.message_clients or [],
        title=req.title or "",
        text=req.text or "",
        image=req.image or "",
    )
    if result.success:
        return success()
    return fail(msg=result.message)


@router.post("/messages/send_plugin", response_model=CommonResponse, summary="发送插件消息")
def send_plugin_message(
    req: SendPluginMessageRequest,
    user: str = Depends(require_permission("setting:update")),
    svc: MessageSenderService = Depends(get_message_sender_service),
):
    svc.send_plugin_message(
        title=req.title or "",
        text=req.text or "",
        image=req.image or "",
    )
    return success()


class LogsRequest(BaseModel):
    source: str | None = None
    level: str | None = None
    limit: int | None = 1000


@router.post("/logs", response_model=CommonResponse, summary="获取日志")
def get_logs(
    req: LogsRequest,
    user: str = Depends(require_permission("log:view")),
):
    logs, _ = LOG_BUFFER.get_logs(source=req.source)
    if req.level:
        logs = [lg for lg in logs if lg.get("level") == req.level]
    if req.limit and req.limit > 0:
        logs = logs[-req.limit :]
    return success(data=logs)


class LogsSearchRequest(BaseModel):
    keyword: str | None = None
    level: str | None = None
    source: str | None = None
    page: int = 1
    page_size: int = 1000
    hours: int | None = 24


@router.post("/logs/search", response_model=CommonResponse, summary="全文搜索日志")
def search_logs(
    req: LogsSearchRequest,
    user: str = Depends(require_permission("log:view")),
):
    """搜索磁盘日志文件（含轮转文件）中的日志，支持分页；默认仅检索最近一天."""
    result = LogSearchService().search(
        keyword=req.keyword,
        level=req.level,
        source=req.source,
        page=req.page,
        page_size=req.page_size,
        hours=req.hours,
    )
    return success(data=result)


@router.post("/logs/sources", response_model=CommonResponse, summary="获取日志来源列表")
def list_log_sources(
    req: EmptyRequest = EmptyRequest(),
    user: str = Depends(require_permission("log:view")),
):
    """返回日志中出现过的全部来源，供前端来源下拉框使用（默认仅统计最近一天）."""
    return success(data=LogSearchService().list_sources())


@router.post("/logs/export", response_model=None, summary="导出日志")
def export_logs(
    req: LogsSearchRequest,
    user: str = Depends(require_permission("log:view")),
):
    """导出匹配日志为文本文件下载（默认仅最近一天的日志）."""
    text = LogSearchService().export_text(
        keyword=req.keyword,
        level=req.level,
        source=req.source,
        hours=req.hours,
    )
    filename = f"nexus-media-logs-{time.strftime('%Y%m%d-%H%M%S')}.txt"
    return Response(
        content=text,
        media_type="text/plain; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@router.post("/processes", response_model=CommonResponse, summary="获取进程列表")
def processes(
    req: EmptyRequest = EmptyRequest(),
    user: str = Depends(require_any_permission("setting:view", "setting:update")),
):
    return success(data=SystemUtils.get_all_processes())


# ---------------------------------------------------------------------------
# 日志流 (SSE)
# ---------------------------------------------------------------------------


@router.get("/stream-logging", summary="实时日志流")
def stream_logging(
    request: Request,
    source: str | None = Query(""),
    token: str | None = Query(""),
):
    """实时日志 EventSource 响应
    兼容 EventSource 无法携带自定义 Header 的限制，支持从 query param 传入 token，
    同时也支持 Authorization header。
    """
    user_ctx = None
    auth_header = request.headers.get("authorization", "")
    if auth_header and auth_header.startswith("Bearer "):
        user_ctx = AuthService.verify_token(auth_header[7:])
    if not user_ctx and token:
        user_ctx = AuthService.verify_token(token)
    if not user_ctx:
        raise AuthError(
            "认证失败，请检查登录状态或 Token",
            errcode=ErrorCode.UNAUTHORIZED,
            http_status=401,
        )

    # 权限检查
    if "log:view" not in user_ctx.permissions:
        raise PermissionDenied("权限不足，需要日志查看权限")

    log_streaming_service = LogStreamingService(sleep_interval=0.3)
    return StreamingResponse(log_streaming_service.stream(source or ""), media_type="text/event-stream")


@router.get("/site-config/version", response_model=CommonResponse, summary="获取站点配置版本")
def get_site_config_version():
    """获取站点配置版本信息"""
    try:
        info = SiteConfigUpdater().get_version_info()
        return success(info)
    except (ServiceError, DomainError) as e:
        return fail(msg=e.message)
    except Exception as e:
        log.error(f"[System]获取站点配置版本失败: {e!s}")
        return fail(msg=str(e))


@router.post("/site-config/update", response_model=CommonResponse, summary="手动更新站点配置")
def update_site_config(
    user: UserContext = Depends(get_current_user),
    payload: EmptyRequest | None = None,
):
    """手动触发站点配置更新"""
    if "setting:update" not in user.permissions:
        raise PermissionDenied("需要站点配置更新权限")

    try:
        force = bool(payload and payload.data and payload.data.get("force"))
        result = SiteConfigUpdater().update(force=force)
        if result["success"]:
            return success(result)
        return fail(msg=result.get("message", ""))
    except (ServiceError, DomainError) as e:
        return fail(msg=e.message)
    except Exception as e:
        log.error(f"[System]手动更新站点配置失败: {e!s}")
        return fail(msg=str(e))


@router.post("/config/reload", response_model=CommonResponse, summary="手动触发配置重载")
def reload_config(
    current_user: UserContext = Depends(require_permission("setting:update")),
    reloader: ConfigReloader = Depends(get_config_reloader),
):
    """手动触发全量配置重载（通过 ConfigReloader 按优先级 reset 各 provider）"""
    try:
        result = reloader.reload()
        if result["failed"]:
            return fail(msg=f"配置重载部分失败: {result['failed']}")
        return success(data={"version": result["version"], "steps": result["results"]})
    except Exception as e:
        log.error(f"[System]配置重载失败: {e!s}")
        return fail(msg=str(e))
