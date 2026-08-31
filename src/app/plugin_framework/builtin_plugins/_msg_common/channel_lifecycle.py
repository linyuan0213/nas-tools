"""消息渠道插件的共享生命周期逻辑.

提供渠道记录的禁用、交互服务停止等公共操作，
供各消息渠道插件（msg_*）的 plugin.py 调用，避免重复实现。
注意：本目录无 manifest.json，不会被插件框架扫描注册为插件。
渠道记录由用户在消息中心手动创建，插件启用时不自动生成。
"""

from typing import Any

import log
from app.db.repositories.config_repo_adapter import MessageClientRepositoryAdapter


def disable_channel_record(message: Any, channel_type: str) -> None:
    """禁用该插件管理的渠道记录（插件禁用时随动停用，配置保留，重新启用时恢复）"""
    try:
        repo = MessageClientRepositoryAdapter()
        for client in repo.get_message_client() or []:
            if client.TYPE == channel_type and client.ENABLED:
                message.update_message_client(cid=client.ID, enabled=0)
    except Exception as e:  # noqa: BLE001
        log.error(f"[Plugin]禁用渠道记录失败 {channel_type}: {e}")


def stop_interactive(message: Any, search_type: str) -> None:
    """停止当前渠道实例的入站交互服务（长连接/Socket 模式）"""
    try:
        entry = message.get_interactive_client(search_type)
        client = entry.get("client") if entry else None
        if client and hasattr(client, "stop_service"):
            client.stop_service()
    except Exception as e:  # noqa: BLE001
        log.error(f"[Plugin]停止交互服务失败 {search_type}: {e}")
