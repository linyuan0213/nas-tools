from pypushdeer import PushDeer

from app.message.client._base import _IMessageClient
from app.message.schema import ConfigField, MessageConfigSchema
from app.utils import ExceptionUtils, StringUtils


class PushDeerClient(_IMessageClient):
    schema = "pushdeer"
    config_schema = MessageConfigSchema(
        name="PushDeer",
        icon_url="/api/plugin-framework/plugins/msg_pushdeer/assets/pushdeer.png",
        fields=[
            ConfigField(
                id="server",
                required=True,
                title="PushDeer服务器地址",
                type="text",
                tooltip="自己搭建pushdeer服务端请实际配置，否则可使用：https://api2.pushdeer.com",
                placeholder="https://api2.pushdeer.com",
                default="https://api2.pushdeer.com",
            ),
            ConfigField(
                id="apikey",
                required=True,
                title="API Key",
                type="text",
                tooltip="pushdeer客户端生成的KEY",
            ),
        ],
    )

    def read_config(self):
        cfg = self._config or {}
        self._server = StringUtils.get_base_url(cfg.get("server"))
        self._apikey = cfg.get("apikey")

    def send_msg(self, title, text="", image="", url="", user_id=""):
        if not title and not text:
            return False, "标题和内容不能同时为空"
        try:
            if not self._server or not self._apikey:
                return False, "参数未配置"
            pushdeer = PushDeer(server=self._server, pushkey=self._apikey)
            res = pushdeer.send_markdown(title, desp=text)
            return (True, "成功") if res else (False, "失败")
        except Exception as msg_e:
            ExceptionUtils.exception_traceback(msg_e)
            return False, str(msg_e)

    def send_list_msg(self, medias: list | None = None, user_id="", title="", **kwargs):
        return False, "不支持发送列表消息"
