"""消息客户端 — 内置客户端注册.

Telegram / WeChat 为核心保留渠道；WebMessage（内置消息页）为系统站内通知兜底，
其余第三方渠道均已插件化（msg_* 插件启用时经 on_enable 显式注册）。
"""

import log
from app.db.repositories.config_repo_adapter import MessageClientRepositoryAdapter
from app.message.client.telegram import Telegram
from app.message.client.web import WebMessage
from app.message.client.wechat import WeChat
from app.message.registry import register
from app.message.switches import MESSAGE_SWITCHES


def init_clients() -> None:
    """注册内置消息客户端类（幂等，可重复调用）"""
    register(Telegram)
    register(WeChat)
    # 内置消息页渠道类（站内通知核心依赖）
    register(WebMessage)


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
