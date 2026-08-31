from urllib import parse

from app.infrastructure.http.client import HttpClient
from app.message.client._base import _IMessageClient
from app.message.schema import ConfigField, MessageConfigSchema
from app.utils import ExceptionUtils, StringUtils


class Chanify(_IMessageClient):
    schema = "chanify"
    config_schema = MessageConfigSchema(
        name="Chanify",
        icon_url="/api/plugin-framework/plugins/msg_chanify/assets/chanify.png",
        fields=[
            ConfigField(
                id="server",
                required=True,
                title="Chanify服务器地址",
                tooltip="自己搭建Chanify服务端地址或使用https://api.chanify.net",
                type="text",
                placeholder="https://api.chanify.net",
                default="https://api.chanify.net",
            ),
            ConfigField(
                id="token",
                required=True,
                title="令牌",
                tooltip="在Chanify客户端频道中获取",
                type="text",
            ),
            ConfigField(
                id="params",
                required=False,
                title="附加参数",
                tooltip="添加到Chanify通知中的附加参数，可用于自定义通知特性",
                type="text",
                placeholder="sound=0&interruption-level=active",
            ),
        ],
    )

    def read_config(self):
        cfg = self._config or {}
        self._server = StringUtils.get_base_url(cfg.get("server"))
        self._token = cfg.get("token")
        self._params = cfg.get("params")

    def send_msg(self, title, text="", image="", url="", user_id=""):
        if not title and not text:
            return False, "标题和内容不能同时为空"
        try:
            if not self._server or not self._token:
                return False, "参数未配置"
            sc_url = f"{self._server}/v1/sender/{self._token}"
            params = parse.parse_qs(self._params or "")
            data = {key: value[0] for key, value in params.items()}
            data.update({"title": title, "text": text})
            HttpClient().post(sc_url, data=parse.urlencode(data).encode())
            return True, "发送成功"
        except Exception as msg_e:
            ExceptionUtils.exception_traceback(msg_e)
            return False, str(msg_e)

    def send_list_msg(self, medias: list | None = None, user_id="", title="", **kwargs):
        return False, "不支持发送列表消息"
