from app.infrastructure.http.client import HttpClient
from app.infrastructure.http.config import HttpClientConfig
from app.message.client._base import _IMessageClient
from app.message.schema import ConfigField, MessageConfigSchema
from app.utils import ExceptionUtils, StringUtils


class Ntfy(_IMessageClient):
    schema = "ntfy"
    config_schema = MessageConfigSchema(
        name="ntfy",
        icon_url="/api/plugin-framework/plugins/msg_ntfy/assets/ntfy.webp",
        fields=[
            ConfigField(
                id="server",
                required=True,
                title="ntfy服务器地址",
                type="text",
                tooltip="自己搭建ntfy服务端地址",
                placeholder="http://localhost:8800",
            ),
            ConfigField(
                id="token",
                required=True,
                title="令牌Token",
                type="text",
                tooltip="ntfy服务端创建的token",
            ),
            ConfigField(
                id="topic",
                required=True,
                title="topic",
                type="text",
                tooltip="ntfy创建的topic",
            ),
            ConfigField(
                id="priority",
                required=False,
                title="消息Priority",
                type="text",
                tooltip="消息通知优先级, 请填写数字(1-5), 默认: 4",
                placeholder="4",
            ),
            ConfigField(
                id="tags",
                required=False,
                title="消息tags",
                type="text",
                tooltip="消息tags,以逗号分隔, 请参阅ntfy官网, 默认: rotating_light",
                placeholder="rotating_light",
            ),
        ],
    )

    def read_config(self):
        cfg = self._config or {}
        self._server = StringUtils.get_base_url(cfg.get("server"))
        self._token = cfg.get("token")
        self._topic = cfg.get("topic")
        self._tags = "rotating_light" if cfg.get("tags") == "" else (cfg.get("tags") or "rotating_light")
        self._tags = self._tags.split(",") if "," in self._tags else [self._tags]
        try:
            self._priority = int(cfg.get("priority") or 0)
        except Exception:
            self._priority = 4

    def send_msg(self, title, text="", image="", url="", user_id=""):
        if not title and not text:
            return False, "标题和内容不能同时为空"
        try:
            if not self._server or not self._token:
                return False, "参数未配置"
            sc_data = {
                "topic": self._topic,
                "title": title,
                "message": text,
                "priority": self._priority,
                "tags": self._tags,
            }
            HttpClient(config=HttpClientConfig(default_headers={"Authorization": "Bearer " + self._token})).post(
                self._server, json=sc_data
            )
            return True, "发送成功"
        except Exception as msg_e:
            ExceptionUtils.exception_traceback(msg_e)
            return False, str(msg_e)

    def send_list_msg(self, medias: list | None = None, user_id="", title="", **kwargs):
        return False, "不支持发送列表消息"
