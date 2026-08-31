"""飞书长连接事件接收服务（lark-oapi 官方 SDK）.

使用 lark-oapi 的 ws.Client 建立长连接（官方 v2 帧协议，自带心跳与断线重连），
事件经 EventDispatcherHandler 分发后解析为 (user_id, text) 并通过 callback 回环。
stop 时关闭连接并禁用自动重连。
"""

import asyncio
import threading

import lark_oapi as lark
from lark_oapi.api.im.v1 import P2ImMessageReceiveV1
from lark_oapi.event.callback.model.p2_card_action_trigger import (
    P2CardActionTrigger,
    P2CardActionTriggerResponse,
)
from lark_oapi.ws import client as ws_client

import log
from app.plugin_framework.builtin_plugins.feishu.backend.event_parser import parse_card_action, parse_im_message


class WsServer(threading.Thread):
    """飞书长连接客户端（后台线程运行，事件经 callback 回环）"""

    def __init__(self, app_id: str, app_secret: str, callback):
        super().__init__(name="feishu_ws", daemon=True)
        self._app_id = app_id
        self._app_secret = app_secret
        self._callback = callback
        self._running = True
        self._client = None

    def _dispatch(self, user_id: str, text: str) -> None:
        """分发解析结果给回调（空文本直接忽略）"""
        if not text:
            return
        try:
            self._callback({"user_id": user_id, "text": text})
        except Exception as e:  # noqa: BLE001
            log.error(f"飞书事件回调异常: {e}")

    def _on_im_message(self, data: P2ImMessageReceiveV1) -> None:
        user_id, text = parse_im_message(data)
        self._dispatch(user_id, text)

    def _on_card_action(self, data: P2CardActionTrigger) -> P2CardActionTriggerResponse:
        user_id, text = parse_card_action(data)
        self._dispatch(user_id, text)
        return P2CardActionTriggerResponse()

    def run(self) -> None:
        try:
            handler = (
                lark.EventDispatcherHandler.builder("", "")
                .register_p2_im_message_receive_v1(self._on_im_message)
                .register_p2_card_action_trigger(self._on_card_action)
                .build()
            )
            self._client = lark.ws.Client(
                app_id=self._app_id,
                app_secret=self._app_secret,
                log_level=lark.LogLevel.WARNING,
                event_handler=handler,
            )
            log.info("飞书长连接已启动")
            self._client.start()
        except Exception as e:  # noqa: BLE001
            if self._running:
                log.error(f"飞书长连接运行异常: {e}")
        finally:
            self._running = False
            self._client = None
            log.info("飞书长连接已停止")

    def stop(self) -> None:
        """停止长连接：断开连接、禁用自动重连并终止 SDK 事件循环（线程随之退出）"""
        self._running = False
        client = self._client
        self._client = None
        if client is None:
            return
        try:
            client._auto_reconnect = False
            future = asyncio.run_coroutine_threadsafe(client._disconnect(), ws_client.loop)
            future.result(timeout=3)
            # 终止 ws.Client.start() 内部的 _select() 无限循环，让 start() 返回、线程退出
            ws_client.loop.call_soon_threadsafe(ws_client.loop.stop)
        except Exception as e:  # noqa: BLE001
            log.warn(f"飞书长连接停止失败: {e}")
