import threading
from typing import Any
from urllib.parse import quote

import log
from app.core.settings import settings
from app.infrastructure.http.client import HttpClient
from app.infrastructure.http.config import HttpClientConfig
from app.infrastructure.thread import ThreadExecutor
from app.message.client._base import _IMessageClient
from app.message.schema import ConfigField, MessageConfigSchema
from app.utils import ExceptionUtils, StringUtils
from app.utils.json_utils import JsonUtils

lock = threading.Lock()


class SynologyChat(_IMessageClient):
    schema = "synologychat"
    config_schema = MessageConfigSchema(
        name="Synology Chat",
        icon_url="/api/plugin-framework/plugins/msg_synologychat/assets/synologychat.png",
        search_type="SYNOLOGY",
        fields=[
            ConfigField(
                id="webhook_url",
                required=True,
                title="机器人传入URL",
                tooltip="在Synology Chat中创建机器人，获取机器人传入URL",
                type="text",
                placeholder="https://xxx/webapi/entry.cgi?api=xxx",
            ),
            ConfigField(
                id="token",
                required=True,
                title="令牌",
                tooltip="在Synology Chat中创建机器人，获取机器人令牌",
                type="text",
                placeholder="",
            ),
            ConfigField(
                id="webhook_ipv4",
                required=False,
                title="Webhook IPv4 白名单",
                tooltip="允许的 IPv4 地址段（CIDR），逗号分隔，默认 0.0.0.0/0 放行所有",
                type="text",
                placeholder="0.0.0.0/0",
                advanced=True,
            ),
            ConfigField(
                id="webhook_ipv6",
                required=False,
                title="Webhook IPv6 白名单",
                tooltip="允许的 IPv6 地址段（CIDR），逗号分隔，默认 ::/0 放行所有",
                type="text",
                placeholder="::/0",
                advanced=True,
            ),
        ],
    )
    _setup_done = set()

    def __init__(self, config, apikey_service, message=None):
        self._config = settings
        self._domain = None
        self._webhook_url = None
        self._token = None
        self._req = HttpClient(
            config=HttpClientConfig(default_headers={"Content-Type": "application/x-www-form-urlencoded"})
        )
        self._apikey_service = apikey_service
        self._polling_stop = threading.Event()
        self._polling_future = None
        super().__init__(config, apikey_service, message=message)

    def read_config(self):
        cfg: Any = self._config or {}
        self._webhook_url = cfg.get("webhook_url")
        if self._webhook_url:
            self._domain = StringUtils.get_base_url(self._webhook_url)
        self._token = cfg.get("token")

    def setup(self):
        if self._webhook_url:
            if self._polling_future and not self._polling_future.done():
                return
            app_cfg = settings.get("app") or {}
            if isinstance(app_cfg, dict):
                web_port = app_cfg.get("web_port", 3000)
            else:
                web_port = getattr(app_cfg, "web_port", 3000)
            _api_key = self._apikey_service.get_or_create_system_key("MessageWebhook")
            ds_url = f"http://127.0.0.1:{web_port}/api/plugin-framework/webhooks/msg_synologychat/callback?apikey={_api_key}"
            self._polling_stop.clear()
            self._polling_future = ThreadExecutor(name="synology_poll").submit(self._start_polling, ds_url)

    def _start_polling(self, ds_url):
        log.info("SynologyChat消息接收服务启动")
        while not self._polling_stop.wait(2):
            try:
                if not self._webhook_url:
                    break
                res = self._req.get(url=self._webhook_url)
                data = res.json()
                if data and "post_id" in data:
                    log.debug(f"[SynologyChat]接收到消息: {data}")
                    ThreadExecutor(name="synology_msg").submit(self._process_message, data, ds_url)
            except Exception as e:
                ExceptionUtils.exception_traceback(e)
                log.error(f"[SynologyChat]消息接收错误: {e}")
                if self._polling_stop.wait(5):
                    break

    def stop_service(self):
        """停止消息轮询服务"""
        self._polling_stop.set()
        if self._polling_future:
            try:
                self._polling_future.result(timeout=3)
            except Exception as e:  # noqa: BLE001
                log.warn(f"SynologyChat 轮询停止失败: {e}")
            self._polling_future = None
            log.info("SynologyChat消息接收服务已停止")

    def _process_message(self, data, ds_url):
        try:
            self._req.post(url=ds_url, json=data, timeout=10)
        except Exception as e:
            ExceptionUtils.exception_traceback(e)

    def check_token(self, token):
        return token == self._token

    def send_msg(self, title, text="", image="", url="", user_id=""):
        if not title and not text:
            return False, "标题和内容不能同时为空"
        if not self._webhook_url or not self._token:
            return False, "参数未配置"
        try:
            titles = str(title).split("\n")
            if len(titles) > 1:
                title = titles[0]
                if not text:
                    text = "\n".join(titles[1:])
                else:
                    text = "{}\n{}".format("\n".join(titles[1:]), text)
            if text:
                caption = "*{}*\n{}".format(title, text.replace("\n\n", "\n"))
            else:
                caption = title
            if url and image:
                caption = f"{caption}\n\n<{url}|查看详情>"
            payload_data = {"text": quote(caption)}
            if image:
                payload_data["file_url"] = quote(image)
            if user_id:
                user_ids = [int(user_id)]
            else:
                user_ids = self.__get_bot_users()
                if not user_ids:
                    return False, "机器人没有对任何用户可见"
            error_flag = True
            error_msg = ""
            for uid in user_ids:
                payload_data["user_ids"] = str(uid)
                error_flag, error_msg = self.__send_request(payload_data)
                if not error_flag:
                    return error_flag, error_msg
            return error_flag, error_msg
        except Exception as msg_e:
            ExceptionUtils.exception_traceback(msg_e)
            return False, str(msg_e)

    def send_list_msg(self, medias: list, user_id="", title="", **kwargs):
        if not medias:
            return False, "参数有误"
        if not self._webhook_url or not self._token:
            return False, "参数未配置"
        try:
            if not title or not isinstance(medias, list):
                return False, "数据错误"
            index, image, caption = 1, "", f"*{title}*"
            for media in medias:
                if not image:
                    image = media.get_message_image()
                if media.get_vote_string():
                    caption = (
                        f"{caption}\n{index}. <{media.get_detail_url()}|{media.get_title_string()}>\n"
                        f"{media.get_type_string()}，{media.get_vote_string()}"
                    )
                else:
                    caption = (
                        f"{caption}\n{index}. <{media.get_detail_url()}|{media.get_title_string()}>\n"
                        f"{media.get_type_string()}"
                    )
                index += 1
            if user_id:
                user_ids = [int(user_id)]
            else:
                user_ids = self.__get_bot_users()
            error_flag = True
            error_msg = ""
            for uid in user_ids:
                payload_data = {"text": quote(caption), "user_ids": [uid]}
                error_flag, error_msg = self.__send_request(payload_data)
                if not error_flag:
                    return error_flag, error_msg
            return error_flag, error_msg
        except Exception as msg_e:
            ExceptionUtils.exception_traceback(msg_e)
            return False, str(msg_e)

    def __get_bot_users(self):
        if not self._domain or not self._token:
            return []
        req_url = (
            f"{self._domain}/webapi/entry.cgi?api=SYNO.Chat.External&method=user_list&version=2&token={self._token}"
        )
        try:
            ret = self._req.get(url=req_url)
            users = ret.json().get("data", {}).get("users", []) or []
            return [user.get("user_id") for user in users]
        except Exception:
            return []

    def __send_request(self, payload_data):
        payload = f"payload={JsonUtils.dumps(payload_data)}"
        if not self._webhook_url:
            return False, "未配置webhook"
        try:
            ret = self._req.post(url=self._webhook_url, data=payload)
            result = ret.json()
            if result:
                errno = result.get("error", {}).get("code")
                errmsg = result.get("error", {}).get("errors")
                if not errno:
                    return True, ""
                return False, f"{errno}-{errmsg}"
            return False, f"{ret.text}"
        except Exception:
            return False, "未获取到返回信息"
