"""飞书消息渠道客户端.

作为 MESSAGE_CLIENT 类型 "feishu" 接入消息中心：
- 出站通知：Webhook 模式（自定义机器人）与应用模式（im/v1/messages）二选一
- 入站交互（应用模式）：长连接接收事件，回环到插件公开回调处理

渠道类在插件加载时经 _IMessageClient.__init_subclass__ 自动注册。
"""

import log
from app.core.settings import settings
from app.infrastructure.http.client import HttpClient
from app.infrastructure.http.config import HttpClientConfig
from app.message.client._base import _IMessageClient
from app.message.schema import ConfigField, MessageConfigSchema
from app.plugin_framework.builtin_plugins.feishu.backend.feishu_api import FeishuApi
from app.plugin_framework.builtin_plugins.feishu.backend.ws_server import WsServer
from app.utils import ExceptionUtils


def build_webhook_payload(title: str, text: str, url: str) -> dict:
    """构造 Webhook 模式文本消息负载"""
    content = title
    if text:
        content = f"{content}\n{text}"
    payload: dict = {"msg_type": "text", "content": {"text": content}}
    return payload


def build_card(title: str, text: str, url: str, img_key: str = "") -> dict:
    """构造应用模式交互卡片（header 显示标题，正文只放 text，避免重复）"""
    elements = []
    if img_key:
        elements.append({"tag": "img", "img_key": img_key, "alt": {"tag": "plain_text", "content": title[:100]}})
    elements.append({"tag": "div", "text": {"tag": "lark_md", "content": text or title}})
    if url:
        elements.append(
            {
                "tag": "action",
                "actions": [
                    {
                        "tag": "button",
                        "text": {"tag": "plain_text", "content": "查看详情"},
                        "type": "default",
                        "url": url,
                    }
                ],
            }
        )
    return {
        "config": {"wide_screen_mode": True},
        "header": {"title": {"tag": "plain_text", "content": title[:100]}, "template": "blue"},
        "elements": elements,
    }


def build_list_card(medias: list, title: str) -> dict:
    """构造搜索结果列表卡片（每项一个"选择"按钮，value 为序号）"""
    elements = []
    for i, media in enumerate(medias):
        idx = i + 1
        star = media.get_star_string() if hasattr(media, "get_star_string") else ""
        overview = media.get_overview_string(50) if hasattr(media, "get_overview_string") else ""
        mtype = media.get_type_string() if hasattr(media, "get_type_string") else ""
        text = f"{idx}. **{media.get_title_string()}**"
        if star:
            text = f"{text}\n{star}"
        if mtype:
            text = f"{text}\n{mtype}"
        if overview:
            text = f"{text}\n{overview}"
        elements.append({"tag": "div", "text": {"tag": "lark_md", "content": text}})
        elements.append(
            {
                "tag": "action",
                "actions": [
                    {"tag": "button", "text": {"tag": "plain_text", "content": "选择"}, "value": {"value": str(idx)}}
                ],
            }
        )
    header_title = title or f"共找到{len(medias)}条相关信息"
    return {
        "config": {"wide_screen_mode": True},
        "header": {"title": {"tag": "plain_text", "content": header_title[:100]}, "template": "blue"},
        "elements": elements,
    }


class Feishu(_IMessageClient):
    """飞书消息渠道（schema=feishu，search_type=FEISHU）"""

    schema = "feishu"
    config_schema = MessageConfigSchema(
        name="飞书",
        search_type="FEISHU",
        icon_url="/api/plugin-framework/plugins/feishu/assets/feishu.svg",
        fields=[
            ConfigField(
                id="webhook_url",
                required=False,
                title="机器人 Webhook 地址",
                tooltip="自定义机器人 Webhook（仅通知）。若同时配置了 App ID/App Secret 将优先使用应用模式",
                type="text",
                placeholder="https://open.feishu.cn/open-apis/bot/v2/hook/xxxx",
            ),
            ConfigField(
                id="secret",
                required=False,
                title="签名密钥",
                tooltip="自定义机器人安全设置中开启签名校验后填写",
                type="password",
                advanced=True,
            ),
            ConfigField(
                id="app_id",
                required=False,
                title="App ID",
                tooltip="企业自建应用的 App ID；填写后使用应用模式（支持交互）",
                type="text",
                placeholder="cli_xxxx",
            ),
            ConfigField(
                id="app_secret",
                required=False,
                title="App Secret",
                tooltip="企业自建应用的 App Secret，请妥善保管",
                type="password",
            ),
            ConfigField(
                id="default_receivers",
                required=False,
                title="通知接收人",
                tooltip="应用模式通知接收人 open_id 或群 chat_id，逗号分隔",
                type="textarea",
            ),
        ],
    )

    def __init__(self, config, apikey_service=None, message=None):
        self._apikey_service = apikey_service
        self._ws = None
        self._callback_url = ""
        super().__init__(config, apikey_service, message=message)

    def read_config(self):
        cfg = self._config or {}
        self._webhook_url = str(cfg.get("webhook_url") or "")
        self._secret = str(cfg.get("secret") or "")
        self._app_id = str(cfg.get("app_id") or "")
        self._app_secret = str(cfg.get("app_secret") or "")
        receivers = str(cfg.get("default_receivers") or "")
        self._default_receivers = [r.strip() for r in receivers.split(",") if r.strip()]
        # 模式判定：填了完整应用凭证优先应用模式（支持交互）；仅有 Webhook 则 Webhook 模式（仅通知）
        if self._app_id and self._app_secret:
            self._mode = "app"
        elif self._webhook_url:
            self._mode = "webhook"
        else:
            self._mode = "app"
        self._feishu_api = FeishuApi(
            app_id=self._app_id,
            app_secret=self._app_secret,
            webhook_url=self._webhook_url,
            secret=self._secret,
        )

    def setup(self):
        """启动入站交互服务（应用模式即启用长连接）"""
        if self._mode != "app" or not self._app_id or not self._app_secret:
            return
        if self._apikey_service is None:
            log.warn("飞书交互服务未启动：缺少 apikey_service")
            return
        try:
            api_key = self._apikey_service.get_or_create_system_key("MessageWebhook")
            app_cfg = settings.get("app") or {}
            if isinstance(app_cfg, dict):
                web_port = app_cfg.get("web_port", 3000)
            else:
                web_port = getattr(app_cfg, "web_port", 3000)
            self._callback_url = (
                f"http://127.0.0.1:{web_port}/api/plugin-framework/webhooks/feishu/callback?apikey={api_key}"
            )
            self._ws = WsServer(
                app_id=self._app_id,
                app_secret=self._app_secret,
                callback=lambda ev: HttpClient(config=HttpClientConfig(timeout=10)).post(self._callback_url, json=ev),
            )
            self._ws.start()
            log.info("飞书消息接收服务已启动")
        except Exception as err:
            ExceptionUtils.exception_traceback(err)
            log.error(f"飞书消息接收服务启动失败: {err}")

    def stop_service(self):
        """停止入站交互服务"""
        if self._ws:
            try:
                self._ws.stop()
            except Exception as err:
                log.warn(f"飞书消息接收服务停止失败: {err}")
            self._ws = None
            log.info("飞书消息接收服务已停止")

    def get_status(self) -> bool:
        """连接测试：先校验应用凭证；有接收人时再实际发送一条测试消息"""
        if self._mode == "webhook":
            state, ret_msg = self.send_msg(title="测试", text="这是一条测试消息")
            if not state:
                log.warn(f"飞书 Webhook 测试失败: {ret_msg}")
            return state
        # 应用模式：先校验凭证有效性
        try:
            if not self._app_id or not self._app_secret:
                log.warn("飞书应用模式测试失败：未配置 App ID/App Secret")
                return False
            self._feishu_api.get_tenant_access_token()
        except Exception as err:
            log.error(f"飞书应用模式测试失败: {err}")
            return False
        # 有接收人时实际发送测试消息，确保通知链路可用
        if self._default_receivers:
            state, ret_msg = self.send_msg(title="测试", text="这是一条测试消息")
            if not state:
                log.warn(f"飞书应用模式测试消息发送失败: {ret_msg}")
            return state
        return True

    def _resolve_image(self, image_url: str) -> str:
        """下载远程图片并上传飞书，返回 image_key（失败返回空串，通知降级为无图）"""
        try:
            resp = HttpClient(config=HttpClientConfig(timeout=20)).get(image_url)
            if not resp.content:
                return ""
            ok, result = self._feishu_api.upload_image(resp.content)
            return result if ok else ""
        except Exception as err:
            log.warn(f"飞书图片上传失败，通知降级为无图: {err}")
            return ""

    # ---------- 出站发送 ----------

    def send_msg(self, title, text="", image="", url="", user_id="") -> tuple[bool, str]:
        if not title and not text:
            return False, "标题和内容不能同时为空"
        if self._mode == "webhook":
            if not self._webhook_url or not self._feishu_api:
                return False, "参数未配置"
            return self._feishu_api.send_webhook(build_webhook_payload(title, text, url), secret=self._secret or None)
        if not self._feishu_api:
            return False, "参数未配置"
        target = user_id or (self._default_receivers[0] if self._default_receivers else "")
        if not target:
            return False, "未配置通知接收人"
        img_key = self._resolve_image(image) if image else ""
        return self._feishu_api.send_card(target, build_card(title, text, url, img_key))

    def send_list_msg(self, medias: list, user_id="", title="", **kwargs) -> tuple[bool, str]:
        if not medias:
            return False, "参数有误"
        if self._mode != "app" or not self._feishu_api:
            return False, "Webhook 模式不支持列表消息"
        target = user_id or (self._default_receivers[0] if self._default_receivers else "")
        if not target:
            return False, "未配置通知接收人"
        return self._feishu_api.send_card(target, build_list_card(medias, title))
