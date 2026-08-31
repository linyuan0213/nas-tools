from app.infrastructure.http.client import HttpClient
from app.infrastructure.http.config import HttpClientConfig
from app.message.client._base import _IMessageClient
from app.message.schema import ConfigField, MessageConfigSchema
from app.utils import ExceptionUtils, StringUtils


class Gotify(_IMessageClient):
    schema = "gotify"
    config_schema = MessageConfigSchema(
        name="Gotify",
        icon_url="/api/plugin-framework/plugins/msg_gotify/assets/gotify.png",
        fields=[
            ConfigField(
                id="server",
                required=True,
                title="Gotify服务器地址",
                tooltip="自己搭建gotify服务端地址",
                type="text",
                placeholder="http://localhost:8800",
            ),
            ConfigField(
                id="token",
                required=True,
                title="令牌Token",
                tooltip="Gotify服务端APPS下创建的token",
                type="text",
            ),
            ConfigField(
                id="priority",
                required=False,
                title="消息Priority",
                tooltip="消息通知优先级, 请填写数字(1-8), 默认: 8",
                type="text",
                placeholder="8",
            ),
        ],
    )

    def read_config(self):
        cfg = self._config or {}
        self._server = StringUtils.get_base_url(cfg.get("server"))
        self._token = cfg.get("token")
        try:
            self._priority = int(cfg.get("priority") or 0)
        except Exception:
            self._priority = 8

    def send_msg(self, title, text="", image="", url="", user_id=""):
        if not title and not text:
            return False, "标题和内容不能同时为空"
        try:
            if not self._server or not self._token:
                return False, "参数未配置"
            sc_url = f"{self._server}/message?token={self._token}"
            sc_data = {
                "title": title,
                "message": text,
                "priority": self._priority,
                "extras": {
                    "client::notification": {"click": {"url": url}},
                },
            }
            HttpClient(config=HttpClientConfig(default_headers={"Content-Type": "application/json"})).post(
                sc_url, json=sc_data
            )
            return True, "发送成功"
        except Exception as msg_e:
            ExceptionUtils.exception_traceback(msg_e)
            return False, str(msg_e)

    def send_list_msg(self, medias: list | None = None, user_id="", title="", **kwargs):
        return False, "不支持发送列表消息"
