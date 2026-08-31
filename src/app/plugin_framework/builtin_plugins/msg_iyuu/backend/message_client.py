from urllib.parse import urlencode

from app.infrastructure.http.client import HttpClient
from app.message.client._base import _IMessageClient
from app.message.schema import ConfigField, MessageConfigSchema
from app.utils import ExceptionUtils


class IyuuMsg(_IMessageClient):
    schema = "iyuu"
    config_schema = MessageConfigSchema(
        name="爱语飞飞",
        icon_url="/api/plugin-framework/plugins/msg_iyuu/assets/iyuu.png",
        fields=[
            ConfigField(
                id="token",
                required=True,
                title="令牌Token",
                tooltip="在爱语飞飞官网中申请，申请地址：https://iyuu.cn/",
                type="text",
                placeholder="登录https://iyuu.cn获取",
            ),
        ],
    )

    def read_config(self):
        cfg = self._config or {}
        self._token = cfg.get("token")

    def send_msg(self, title, text="", image="", url="", user_id=""):
        if not title and not text:
            return False, "标题和内容不能同时为空"
        if not self._token:
            return False, "参数未配置"
        try:
            sc_url = "http://iyuu.cn/{}.send?{}".format(self._token, urlencode({"text": title, "desp": text}))
            res = HttpClient().get(sc_url)
            ret_json = res.json()
            errno = ret_json.get("errcode")
            error = ret_json.get("errmsg")
            if errno == 0:
                return True, error
            else:
                return False, error
        except Exception as msg_e:
            ExceptionUtils.exception_traceback(msg_e)
            return False, str(msg_e)

    def send_list_msg(self, medias: list | None = None, user_id="", title="", **kwargs):
        return False, "不支持发送列表消息"
