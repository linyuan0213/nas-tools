"""
消息客户端 Webhook Router
处理 Telegram / WeChat / SynologyChat / Slack 等消息平台的回调
"""

import asyncio
import threading

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status

import log
from api.deps import get_apikey_service, get_app_context, get_message
from app.di.context import AppContext
from app.domain.enums import SearchType
from app.infrastructure.security import SecurityChecker
from app.message import Message
from app.services.apikey_service import APIKeyService
from app.services.search_message_service import MessageSearchService
from app.services.system_service import MessageCommandHandler

router = APIRouter()


def _verify_webhook_ip(channel: SearchType, request: Request, message: Message) -> None:
    """从对应消息客户端配置读取 IP 白名单并进行校验。"""
    entry = message.get_interactive_client(channel)
    if entry and entry.get("client"):
        allow_ips = entry["client"].get_webhook_allow_ip()
    else:
        allow_ips = {"ipv4": "0.0.0.0/0", "ipv6": "::/0"}
    client_ip = request.client.host if request.client else ""
    if not SecurityChecker.allow_access(allow_ips, client_ip):
        log.warn(f"[Webhook]{channel.value} IP 白名单拒绝: {client_ip}")
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="IP not allowed")


_MESSAGE_INITIALIZED = False


def _ensure_message_initialized(message: Message):
    """确保消息客户端已初始化（懒加载触发）"""
    global _MESSAGE_INITIALIZED
    if not _MESSAGE_INITIALIZED:
        _ = message.active_clients
        _MESSAGE_INITIALIZED = True


def _verify_apikey(request: Request, service: APIKeyService):
    """验证 API Key（使用数据库管理的 API Key）"""
    api_key = request.query_params.get("apikey") or request.query_params.get("api_key")
    if not api_key:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Missing API Key")

    key = service.validate_key(api_key)
    if not key:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Invalid API Key")


def _get_user_id_from_update(update: dict, channel: SearchType) -> str:
    """从各平台消息中提取用户ID"""
    if channel == SearchType.TG:
        msg = update.get("message") or update.get("edited_message", {})
        user = msg.get("from", {})
        return str(user.get("id", ""))
    if channel == SearchType.WX:
        return update.get("FromUserName", "")
    if channel == SearchType.SYNOLOGY:
        return update.get("user_id", "")
    if channel == SearchType.SLACK:
        return update.get("user", "")
    return ""


def _get_text_from_update(update: dict, channel: SearchType) -> str:
    """从各平台消息中提取文本"""
    if channel == SearchType.TG:
        msg = update.get("message") or update.get("edited_message", {})
        text = msg.get("text", "")
        # 处理命令（如 /start）
        if text.startswith("/"):
            entities = msg.get("entities", [])
            for ent in entities:
                if ent.get("type") == "bot_command":
                    offset = ent.get("offset", 0)
                    length = ent.get("length", 0)
                    text = text[offset : offset + length]
                    break
        return text
    if channel == SearchType.WX:
        return update.get("Content", "")
    if channel == SearchType.SYNOLOGY:
        return update.get("text", "")
    if channel == SearchType.SLACK:
        # Slack 消息可能 text 为空，用 blocks 或 command
        text = update.get("text", "")
        if not text:
            text = update.get("command", "")
        return text
    return ""


_handlers_lock = threading.Lock()
_search_service: MessageSearchService | None = None
_command_handler: MessageCommandHandler | None = None


def _get_handlers(app_context: AppContext, message: Message) -> MessageCommandHandler:
    """搜索/命令处理器单例。

    交互式搜索的分页缓存随实例存活，必须跨消息复用同一实例，
    否则列表消息发出后回复序号时缓存已随实例销毁。
    """
    global _search_service, _command_handler
    with _handlers_lock:
        if _search_service is None:
            _search_service = MessageSearchService(
                downloader=app_context.downloader_core,
                searcher=app_context.searcher,
                indexer=app_context.indexer_service,
                site_cache=app_context.site_cache,
                site_engine=app_context.site_engine,
                subscribe_service=app_context.subscribe_service,
                media_service=app_context.media_service,
                agent_service=app_context.agent_service,
                message=message,
            )
        if _command_handler is None:
            _command_handler = MessageCommandHandler(
                search_handler=_search_service,
                torrent_remover_service=app_context.torrent_remover_service,
                downloader_core=app_context.downloader_core,
                sync_service=app_context.sync_service,
                filetransfer_service=app_context.filetransfer_service,
                event_bus=app_context.event_bus,
                thread_executor=app_context.thread_executor,
                message=message,
                subscription_monitor=app_context.subscription_monitor,
                rss_task_service=app_context.rss_task_service,
                subscribe_service=app_context.subscribe_service,
                site_service=app_context.site_service,
                system_lifecycle=app_context.system_lifecycle,
            )
    return _command_handler


def _reset_handlers() -> None:
    """重置处理器单例（测试用）"""
    global _search_service, _command_handler
    with _handlers_lock:
        _search_service = None
        _command_handler = None


def _handle_webhook(update: dict, channel: SearchType, app_context: AppContext, message: Message):
    """统一处理各平台 webhook"""
    _ensure_message_initialized(message)

    user_id = _get_user_id_from_update(update, channel)
    text = _get_text_from_update(update, channel)
    if not text:
        return {"ok": True}

    log.info(f"[Webhook]{channel.value} 收到消息: user={user_id}, text={text[:60]}...")

    handler = _get_handlers(app_context, message)
    handler.handle_message_job(msg=text, in_from=channel, user_id=user_id)
    return {"ok": True}


@router.post("/telegram", summary="Telegram Bot Webhook")
async def telegram_webhook(
    request: Request,
    service: APIKeyService = Depends(get_apikey_service),
    app_context: AppContext = Depends(get_app_context),
    message: Message = Depends(get_message),
):
    """Telegram Bot Webhook"""
    _ensure_message_initialized(message)
    _verify_webhook_ip(SearchType.TG, request, message)

    entry = message.get_interactive_client(SearchType.TG)
    client = entry.get("client") if entry else None
    secret_token = getattr(client, "secret_token", None) if client else None

    if secret_token:
        header_token = request.headers.get("X-Telegram-Bot-Api-Secret-Token", "")
        if header_token != secret_token:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Telegram secret token mismatch")
    else:
        _verify_apikey(request, service)

    data = await request.json()
    return await asyncio.to_thread(_handle_webhook, data, SearchType.TG, app_context, message)


@router.get("/wechat", summary="微信 URL 验证")
async def wechat_verify(
    request: Request,
    app_context: AppContext = Depends(get_app_context),
    message: Message = Depends(get_message),
):
    """WeChat 企业微信/公众号回调 URL 验证"""
    _ensure_message_initialized(message)

    signature = request.query_params.get("msg_signature", "") or request.query_params.get("signature", "")
    timestamp = request.query_params.get("timestamp", "")
    nonce = request.query_params.get("nonce", "")
    echostr = request.query_params.get("echostr", "")

    entry = message.get_interactive_client(SearchType.WX)
    if not entry or not entry.get("client"):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="WeChat client not configured")

    client = entry["client"]
    if not hasattr(client, "verify_url"):
        raise HTTPException(status_code=status.HTTP_501_NOT_IMPLEMENTED, detail="WeChat verify not supported")

    result = client.verify_url(signature, timestamp, nonce, echostr)
    if result is None:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="WeChat signature verification failed")

    return Response(content=result, media_type="text/plain")


@router.post("/wechat", summary="微信 Webhook")
async def wechat_webhook(
    request: Request,
    app_context: AppContext = Depends(get_app_context),
    message: Message = Depends(get_message),
):
    """WeChat 企业微信/公众号 Webhook"""
    _ensure_message_initialized(message)

    signature = request.query_params.get("msg_signature", "") or request.query_params.get("signature", "")
    timestamp = request.query_params.get("timestamp", "")
    nonce = request.query_params.get("nonce", "")

    entry = message.get_interactive_client(SearchType.WX)
    if not entry or not entry.get("client"):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="WeChat client not configured")

    client = entry["client"]
    if not hasattr(client, "parse_message"):
        raise HTTPException(status_code=status.HTTP_501_NOT_IMPLEMENTED, detail="WeChat message parse not supported")

    xml_text = (await request.body()).decode("utf-8")
    msg = client.parse_message(xml_text, signature=signature, timestamp=timestamp, nonce=nonce)
    if msg is None:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="WeChat message verification failed")

    update = {
        "FromUserName": msg.get("FromUserName", ""),
        "ToUserName": msg.get("ToUserName", ""),
        "Content": msg.get("Content", ""),
        "MsgType": msg.get("MsgType", ""),
        "Event": msg.get("Event", ""),
        "EventKey": msg.get("EventKey", ""),
    }
    # 企业微信 click 菜单事件：EventKey 为命令去掉斜杠后的 key（如 rss、sta、signin），
    # 兼容旧版本下划线前缀的 key（如 _rss）与含下划线的多级 key
    text = update["Content"]
    if update["MsgType"] == "event" and update["Event"] == "click" and update["EventKey"]:
        text = f"/{update['EventKey'].lstrip('_').replace('_', '/')}"
        update["Content"] = text
    if text:
        await asyncio.to_thread(_handle_webhook, update, SearchType.WX, app_context, message)
    return Response(content="success", media_type="text/plain")


@router.post("/synologychat", summary="Synology Chat Webhook")
async def synologychat_webhook(
    request: Request,
    service: APIKeyService = Depends(get_apikey_service),
    app_context: AppContext = Depends(get_app_context),
    message: Message = Depends(get_message),
):
    """Synology Chat Webhook"""
    _verify_apikey(request, service)
    _verify_webhook_ip(SearchType.SYNOLOGY, request, message)
    data = await request.json()
    return await asyncio.to_thread(_handle_webhook, data, SearchType.SYNOLOGY, app_context, message)


@router.post("/slack", summary="Slack Webhook")
async def slack_webhook(
    request: Request,
    service: APIKeyService = Depends(get_apikey_service),
    app_context: AppContext = Depends(get_app_context),
    message: Message = Depends(get_message),
):
    """Slack Event/Webhook"""
    _verify_apikey(request, service)
    _verify_webhook_ip(SearchType.SLACK, request, message)
    data = await request.json()
    if data.get("type") == "url_verification":
        return {"challenge": data.get("challenge")}
    return await asyncio.to_thread(_handle_webhook, data, SearchType.SLACK, app_context, message)
