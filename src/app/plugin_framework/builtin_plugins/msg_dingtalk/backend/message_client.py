"""钉钉消息渠道客户端.

- 通知：自定义机器人 Webhook（markdown，可选加签）
- 交互：Stream 模式长连接（dingtalk-stream SDK）接收机器人消息，回环到插件公开回调
"""

import asyncio
import threading
import time

from dingtalk_stream import AckMessage, ChatbotHandler, ChatbotMessage, Credential, DingTalkStreamClient

import log
from app.core.settings import settings
from app.infrastructure.http.client import HttpClient
from app.infrastructure.http.config import HttpClientConfig
from app.message.client._base import _IMessageClient
from app.message.schema import ConfigField, MessageConfigSchema
from app.plugin_framework.builtin_plugins.msg_dingtalk.backend.event_parser import parse_chatbot_message
from app.plugin_framework.builtin_plugins.msg_dingtalk.backend.signer import gen_sign
from app.utils import ExceptionUtils
from app.utils.json_utils import JsonUtils


class _DingTalkChatbotHandler(ChatbotHandler):
    """钉钉机器人消息回调处理器.

    解析用户消息并保存会话回复通道（sessionWebhook），随后回环本机插件公开回调。
    交互回复通过会话 Webhook 精准发回对话，无需群机器人。
    """

    def __init__(self, client):
        super().__init__()
        self._client = client

    async def process(self, message):  # type: ignore[override] - 钉钉 SDK 回调覆写
        try:
            log.info(f"[DingTalk]收到消息 data: {JsonUtils.dumps(message.data, ensure_ascii=False)[:400]}")
            user_id, text = parse_chatbot_message(message.data)
            session_webhook = message.data.get("sessionWebhook") or ""
            if user_id and session_webhook:
                self._client.save_session_webhook(user_id, session_webhook)
            if text:
                self._client.loopback({"user_id": user_id, "text": text})
        except Exception as e:  # noqa: BLE001
            log.error(f"[DingTalk]消息解析失败: {e}")
        return AckMessage.STATUS_OK, "OK"


class DingTalk(_IMessageClient):
    """钉钉消息渠道（schema=dingtalk，search_type=DINGTALK）"""

    schema = "dingtalk"
    config_schema = MessageConfigSchema(
        name="钉钉",
        search_type="DINGTALK",
        icon_url="/api/plugin-framework/plugins/msg_dingtalk/assets/dingtalk.svg",
        fields=[
            ConfigField(
                id="webhook_url",
                required=False,
                title="机器人 Webhook 地址",
                tooltip="钉钉群自定义机器人 Webhook（通知推送）。若配置了 App Key/App Secret 则同时启用交互",
                type="text",
                placeholder="https://oapi.dingtalk.com/robot/send?access_token=xxx",
            ),
            ConfigField(
                id="secret",
                required=False,
                title="加签密钥",
                tooltip="自定义机器人安全设置中开启加签后填写",
                type="password",
                advanced=True,
            ),
            ConfigField(
                id="app_key",
                required=False,
                title="App Key",
                tooltip="钉钉开放平台应用 App Key（Stream 模式交互）",
                type="text",
            ),
            ConfigField(
                id="app_secret",
                required=False,
                title="App Secret",
                tooltip="钉钉开放平台应用 App Secret，请妥善保管",
                type="password",
            ),
            ConfigField(
                id="agent_id",
                required=False,
                title="Agent ID（应用 ID）",
                tooltip="开放平台应用详情中的 AgentId；填写后主动通知通过 OpenAPI 工作通知发送到个人",
                type="text",
            ),
            ConfigField(
                id="default_user_ids",
                required=False,
                title="通知接收人 userId",
                tooltip="主动通知接收人钉钉 userId（交互过的用户自动记录），逗号分隔；留空则发给交互过的用户",
                type="textarea",
            ),
            ConfigField(
                id="at_mobiles",
                required=False,
                title="@手机号",
                tooltip="通知时 @ 的手机号，逗号分隔（仅群 Webhook 模式）",
                type="textarea",
            ),
        ],
    )

    def __init__(self, config, apikey_service=None, message=None):
        self._apikey_service = apikey_service
        self._stream_client = None
        self._stream_loop: asyncio.AbstractEventLoop | None = None
        self._stream_thread: threading.Thread | None = None
        # 交互会话回复通道：user_id -> sessionWebhook（钉钉会话级 webhook）
        self._session_webhooks: dict[str, str] = {}
        self._callback_url = ""
        super().__init__(config, apikey_service, message=message)

    def read_config(self):
        cfg = self._config or {}
        self._webhook_url = str(cfg.get("webhook_url") or "")
        self._secret = str(cfg.get("secret") or "")
        self._app_key = str(cfg.get("app_key") or "")
        self._app_secret = str(cfg.get("app_secret") or "")
        self._agent_id = str(cfg.get("agent_id") or "")
        at_mobiles = str(cfg.get("at_mobiles") or "")
        self._at_mobiles = [m.strip() for m in at_mobiles.split(",") if m.strip()]
        user_ids = str(cfg.get("default_user_ids") or "")
        self._default_user_ids = [u.strip() for u in user_ids.split(",") if u.strip()]
        self._token = ""
        self._token_expires = 0.0

    # ---------- 交互：Stream 长连接 ----------

    def save_session_webhook(self, user_id: str, session_webhook: str) -> None:
        """保存会话回复通道（交互回复精准发回对话）"""
        self._session_webhooks[user_id] = session_webhook

    def loopback(self, ev: dict) -> None:
        """回环事件到插件公开回调（统一走命令处理）"""
        try:
            HttpClient(config=HttpClientConfig(timeout=10)).post(self._callback_url, json=ev)
        except Exception as e:  # noqa: BLE001
            log.error(f"[DingTalk]事件回环失败: {e}")

    def setup(self):
        if not self._app_key or not self._app_secret:
            return
        if self._stream_thread is not None and self._stream_thread.is_alive():
            return  # 已运行，防重复连接
        if self._apikey_service is None:
            log.warn("钉钉交互服务未启动：缺少 apikey_service")
            return
        try:
            api_key = self._apikey_service.get_or_create_system_key("MessageWebhook")
            app_cfg = settings.get("app") or {}
            if isinstance(app_cfg, dict):
                web_port = app_cfg.get("web_port", 3000)
            else:
                web_port = getattr(app_cfg, "web_port", 3000)
            self._callback_url = (
                f"http://127.0.0.1:{web_port}/api/plugin-framework/webhooks/msg_dingtalk/callback?apikey={api_key}"
            )
            handler = _DingTalkChatbotHandler(self)
            self._stream_loop = asyncio.new_event_loop()
            self._stream_thread = threading.Thread(
                target=self._run_stream,
                args=(handler,),
                name="dingtalk_stream",
                daemon=True,
            )
            self._stream_thread.start()
            log.info("钉钉 Stream 交互服务已启动")
        except Exception as err:
            ExceptionUtils.exception_traceback(err)
            log.error(f"钉钉 Stream 交互服务启动失败: {err}")

    def _run_stream(self, handler) -> None:
        loop = self._stream_loop
        if loop is None:
            return
        asyncio.set_event_loop(loop)
        loop.run_until_complete(self._stream_client_run(handler))

    async def _stream_client_run(self, handler) -> None:
        self._stream_client = DingTalkStreamClient(Credential(self._app_key, self._app_secret))
        self._stream_client.register_callback_handler(ChatbotMessage.TOPIC, handler)
        await self._stream_client.start()

    def stop_service(self):
        client = self._stream_client
        loop = self._stream_loop
        thread = self._stream_thread
        if client is not None and loop is not None:
            try:
                stop = getattr(client, "stop", None)
                if callable(stop):
                    asyncio.run_coroutine_threadsafe(stop(), loop)  # type: ignore[arg-type]
                if thread is not None:
                    thread.join(timeout=3)
            except Exception as err:  # noqa: BLE001
                log.warn(f"钉钉 Stream 交互服务停止失败: {err}")
        self._stream_client = None
        self._stream_loop = None
        self._stream_thread = None

    # ---------- 通知：Webhook 发送 ----------

    def _build_payload(self, title: str, text: str, image: str = "") -> dict:
        content = f"### {title}" if text else title
        if image:
            content = f"{content}\n\n![海报]({image})"
        if text:
            content = f"{content}\n\n{text}"
        payload: dict = {"msgtype": "markdown", "markdown": {"title": title[:100], "text": content}}
        if self._at_mobiles:
            payload["at"] = {"atMobiles": self._at_mobiles, "isAtAll": False}
        return payload

    def _send_webhook(self, payload: dict) -> tuple[bool, str]:
        try:
            headers = {"Content-Type": "application/json"}
            if self._secret:
                timestamp = str(int(time.time() * 1000))
                headers.update(
                    {
                        "timestamp": timestamp,
                        "sign": gen_sign(self._secret, timestamp),
                    }
                )
            resp = HttpClient(config=HttpClientConfig(timeout=15)).post(
                self._webhook_url, json=payload, headers=headers
            )
            data = resp.json()
            if data and data.get("errcode") == 0:
                return True, ""
            return False, str((data or {}).get("errmsg") or resp.text[:200])
        except Exception as e:
            err_msg = getattr(getattr(e, "__cause__", None), "response", None) or e
            ExceptionUtils.exception_traceback(e)
            return False, str(err_msg)

    # ---------- OpenAPI 工作通知（主动发送到个人，无需群机器人） ----------

    def _get_access_token(self) -> str:
        """获取钉钉新版 OAuth accessToken（缓存，约 2 小时）"""
        if self._token and time.time() < self._token_expires:
            return self._token
        resp = HttpClient(config=HttpClientConfig(timeout=10)).post(
            "https://api.dingtalk.com/v1.0/oauth2/accessToken",
            json={"appKey": self._app_key, "appSecret": self._app_secret},
        )
        data = resp.json()
        token = str((data or {}).get("accessToken") or "")
        if not token:
            raise RuntimeError(str((data or {}).get("message") or "获取 accessToken 失败"))
        self._token = token
        self._token_expires = time.time() + int((data or {}).get("expireIn", 7200)) - 300
        return self._token

    def _send_corp_conversation(self, user_ids: list[str], title: str, text: str, image: str = "") -> tuple[bool, str]:
        """通过机器人单聊（新版 REST API）发送 markdown 消息到指定用户"""
        try:
            token = self._get_access_token()
            content = f"### {title}" if text else title
            if image:
                content = f"{content}\n\n![海报]({image})"
            if text:
                content = f"{content}\n\n{text}"
            resp = HttpClient(config=HttpClientConfig(timeout=15)).post(
                "https://api.dingtalk.com/v1.0/robot/oToMessages/batchSend",
                headers={"x-acs-dingtalk-access-token": token},
                json={
                    "userIds": user_ids,
                    "msgKey": "sampleMarkdown",
                    "msgParam": JsonUtils.dumps(
                        {"title": title[:100], "text": content},
                        ensure_ascii=False,
                    ),
                    "robotCode": self._app_key,
                },
            )
            data = resp.json()
            if data and not data.get("code"):
                return True, ""
            return False, str((data or {}).get("message") or resp.text[:200])
        except Exception as e:
            ExceptionUtils.exception_traceback(e)
            return False, str(e)

    def _active_user_ids(self) -> list[str]:
        """主动通知接收人：默认配置 + 交互过的用户"""
        users = list(self._default_user_ids)
        for uid in self._session_webhooks:
            if uid not in users:
                users.append(uid)
        return users

    def send_msg(self, title, text="", image="", url="", user_id="") -> tuple[bool, str]:
        if not title and not text:
            return False, "标题和内容不能同时为空"
        # 1. 交互回复：优先会话 Webhook（精准发回对话）
        if user_id and user_id in self._session_webhooks:
            return self._send_webhook_to(
                self._session_webhooks[user_id], self._build_payload(title, text, image)
            )
        # 2. 主动通知：机器人单聊（发个人，无需群机器人）
        if self._app_key and self._app_secret:
            users = self._active_user_ids()
            if user_id and user_id not in users:
                users.insert(0, user_id)
            if users:
                state, err = self._send_corp_conversation(users, title, text, image)
                if state:
                    return True, ""
                log.warn(f"[DingTalk]机器人单聊发送失败，回退 Webhook: {err}")
        # 3. 兜底：群机器人 Webhook
        if not self._webhook_url:
            return False, "未配置 Webhook 地址"
        return self._send_webhook(self._build_payload(title, text, image))

    def send_list_msg(self, medias: list, user_id="", title="", **kwargs) -> tuple[bool, str]:
        if not medias:
            return False, "参数有误"
        lines = [f"{i + 1}. **{media.get_title_string()}**" for i, media in enumerate(medias)]
        image = kwargs.get("image") or ""
        payload = self._build_payload(title or "搜索结果", "\n".join(lines), image)
        if user_id and user_id in self._session_webhooks:
            return self._send_webhook_to(self._session_webhooks[user_id], payload)
        if self._app_key and self._app_secret:
            users = self._active_user_ids()
            if user_id and user_id not in users:
                users.insert(0, user_id)
            if users:
                state, err = self._send_corp_conversation(users, title or "搜索结果", "\n".join(lines), image)
                if state:
                    return True, ""
                log.warn(f"[DingTalk]机器人单聊发送失败，回退 Webhook: {err}")
        if not self._webhook_url:
            return False, "未配置 Webhook 地址"
        return self._send_webhook(payload)

    def _send_webhook_to(self, webhook_url: str, payload: dict) -> tuple[bool, str]:
        try:
            headers = {"Content-Type": "application/json"}
            if self._secret:
                timestamp = str(int(time.time() * 1000))
                headers.update(
                    {
                        "timestamp": timestamp,
                        "sign": gen_sign(self._secret, timestamp),
                    }
                )
            resp = HttpClient(config=HttpClientConfig(timeout=15)).post(
                webhook_url, json=payload, headers=headers
            )
            data = resp.json()
            if data and data.get("errcode") == 0:
                return True, ""
            return False, str((data or {}).get("errmsg") or resp.text[:200])
        except Exception as e:
            ExceptionUtils.exception_traceback(e)
            return False, str(e)
