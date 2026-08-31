from urllib.parse import quote_plus

from app.infrastructure.http.client import HttpClient
from app.message.client._base import _IMessageClient
from app.message.schema import ConfigField, MessageConfigSchema
from app.utils import ExceptionUtils, StringUtils


class Bark(_IMessageClient):
    schema = "bark"
    config_schema = MessageConfigSchema(
        name="Bark",
        icon_url="/api/plugin-framework/plugins/msg_bark/assets/bark.webp",
        fields=[
            ConfigField(
                id="server",
                required=True,
                title="Bark服务器地址",
                tooltip="自己搭建Bark服务端请实际配置，否则可使用：https://api.day.app",
                type="text",
                placeholder="https://api.day.app",
                default="https://api.day.app",
            ),
            ConfigField(
                id="apikey",
                required=True,
                title="API Key",
                tooltip="在Bark客户端中点击右上角的“...”按钮，选择“生成Bark Key”，然后将生成的KEY填入此处",
                type="text",
            ),
            ConfigField(
                id="params",
                required=False,
                title="附加参数",
                tooltip="添加到Bark通知中的附加参数，可用于自定义通知特性",
                type="text",
                placeholder="group=xxx&sound=xxx&url=xxx",
            ),
        ],
    )

    def read_config(self):
        cfg = self._config or {}
        self._server = StringUtils.get_base_url(cfg.get("server"))
        self._apikey = cfg.get("apikey")
        self._params = cfg.get("params")

    def send_msg(self, title, text="", image="", url="", user_id=""):
        if not title and not text:
            return False, "标题和内容不能同时为空"
        try:
            if not self._server or not self._apikey:
                return False, "参数未配置"
            sc_url = f"{self._server}/{self._apikey}/{quote_plus(title)}/{quote_plus(text)}"
            if self._params:
                sc_url = f"{sc_url}?{self._params}"
            res = HttpClient().post(sc_url)
            ret_json = res.json()
            code = ret_json["code"]
            message = ret_json["message"]
            if code == 200:
                return True, message
            else:
                return False, message
        except Exception as msg_e:
            ExceptionUtils.exception_traceback(msg_e)
            return False, str(msg_e)

    def send_list_msg(self, medias: list | None = None, user_id="", title="", **kwargs):
        return False, "不支持发送列表消息"
