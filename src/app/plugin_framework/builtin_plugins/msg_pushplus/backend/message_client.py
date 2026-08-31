import time
from urllib.parse import urlencode

from app.infrastructure.http.client import HttpClient
from app.message.client._base import _IMessageClient
from app.message.schema import ConfigField, MessageConfigSchema
from app.utils import ExceptionUtils


class PushPlus(_IMessageClient):
    schema = "pushplus"
    config_schema = MessageConfigSchema(
        name="PushPlus",
        icon_url="/api/plugin-framework/plugins/msg_pushplus/assets/pushplus.jpg",
        fields=[
            ConfigField(
                id="token",
                required=True,
                title="Token",
                type="text",
                tooltip="在PushPlus官网中申请，申请地址：http://pushplus.plus/",
            ),
            ConfigField(
                id="channel",
                required=True,
                title="推送渠道",
                type="select",
                tooltip="使用PushPlus中配置的发送渠道，具体参考pushplus.plus官网文档说明，支持第三方webhook、钉钉、飞书、邮箱等",
                options={"wechat": "微信", "mail": "邮箱", "webhook": "第三方Webhook"},
                default="wechat",
            ),
            ConfigField(
                id="topic",
                required=False,
                title="群组编码",
                type="text",
                tooltip="PushPlus中创建的群组，如未设置可为空",
            ),
            ConfigField(
                id="webhook",
                required=False,
                title="Webhook编码",
                type="text",
                tooltip="PushPlus中创建的webhook编码，发送渠道为第三方webhook时需要填入",
            ),
        ],
    )

    def read_config(self):
        cfg = self._config or {}
        self._token = cfg.get("token")
        self._topic = cfg.get("topic")
        self._channel = cfg.get("channel")
        self._webhook = cfg.get("webhook")

    def send_msg(self, title, text="", image="", url="", user_id=""):
        if not title and not text:
            return False, "标题和内容不能同时为空"
        if not text:
            text = "无"
        if not self._token or not self._channel:
            return False, "参数未配置"
        try:
            values = {
                "token": self._token,
                "channel": self._channel,
                "topic": self._topic,
                "webhook": self._webhook,
                "title": title,
                "content": text,
                "timestamp": time.time_ns() + 60,
            }
            sc_url = f"http://www.pushplus.plus/send?{urlencode(values)}"
            res = HttpClient().get(sc_url)
            ret_json = res.json()
            code = ret_json.get("code")
            msg = ret_json.get("msg")
            if code == 200:
                return True, msg
            else:
                return False, msg
        except Exception as msg_e:
            ExceptionUtils.exception_traceback(msg_e)
            return False, str(msg_e)

    def send_list_msg(self, medias: list | None = None, user_id="", title="", **kwargs):
        return False, "不支持发送列表消息"
