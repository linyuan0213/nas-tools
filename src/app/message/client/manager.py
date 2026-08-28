"""消息客户端 — 内置客户端注册."""

import log
from app.db.repositories.config_repo_adapter import MessageClientRepositoryAdapter
from app.message.client.bark import Bark
from app.message.client.chanify import Chanify
from app.message.client.gotify import Gotify
from app.message.client.iyuu import IyuuMsg
from app.message.client.ntfy import Ntfy
from app.message.client.pushdeer import PushDeerClient
from app.message.client.pushplus import PushPlus
from app.message.client.serverchan import ServerChan
from app.message.client.slack import Slack
from app.message.client.synologychat import SynologyChat
from app.message.client.telegram import Telegram
from app.message.client.web import WebMessage
from app.message.client.webhook import Webhook
from app.message.client.wechat import WeChat
from app.message.registry import register
from app.message.switches import MESSAGE_SWITCHES


def init_clients() -> None:
    """注册内置消息客户端类（幂等，可重复调用）"""
    register(Bark)
    register(Chanify)
    register(Gotify)
    register(IyuuMsg)
    register(Ntfy)
    register(PushDeerClient)
    register(PushPlus)
    register(ServerChan)
    register(Slack)
    register(SynologyChat)
    register(Telegram)
    register(WeChat)
    register(WebMessage)
    register(Webhook)


def ensure_web_client() -> None:
    """内置消息页客户端 DB 种子：缺失则插入（幂等，通知设置页统一配置开关）"""
    repo = MessageClientRepositoryAdapter()
    clients = repo.get_message_client() or []
    if any(getattr(c, "TYPE", None) == "web" for c in clients):
        return
    cid = repo.insert_message_client(
        name="内置消息页",
        ctype="web",
        config="{}",
        switches=list(MESSAGE_SWITCHES.keys()),
        interactive=1,
        enabled=1,
        note="内置消息交互页通知渠道（不可删除）",
        templates="{}",
    )
    if cid:
        log.info("[Message]内置消息页客户端已创建")
