import re
from threading import Lock

from slack_bolt import App
from slack_bolt.adapter.socket_mode import SocketModeHandler
from slack_sdk.errors import SlackApiError

import log
from app.core.settings import settings
from app.infrastructure.http.client import HttpClient
from app.infrastructure.http.config import HttpClientConfig
from app.message.client._base import _IMessageClient
from app.message.schema import ConfigField, MessageConfigSchema
from app.utils import ExceptionUtils

lock = Lock()


class Slack(_IMessageClient):
    schema = "slack"
    config_schema = MessageConfigSchema(
        name="Slack",
        icon_url="/api/plugin-framework/plugins/msg_slack/assets/slack.png",
        search_type="SLACK",
        fields=[
            ConfigField(
                id="bot_token",
                required=True,
                title="Bot User OAuth Token",
                tooltip="在Slack中创建应用，获取Bot User OAuth Token",
                type="text",
                placeholder="xoxb-xxxxxxxxxxxx-xxxxxxxxxxxxxxxxxxxxxxxx",
            ),
            ConfigField(
                id="app_token",
                required=True,
                title="App-Level Token",
                tooltip="在Slack中创建应用，获取App-Level Token",
                type="text",
                placeholder="xapp-xxxxxxxxxxxx-xxxxxxxxxxxxxxxxxxxxxxxx",
            ),
            ConfigField(
                id="channel",
                required=False,
                title="频道名称",
                tooltip="Slack中的频道名称，默认为全体；需要将机器人添加到该频道，以接收非交互类的通知消息",
                type="text",
                placeholder="全体",
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

    def __init__(self, config, apikey_service, message=None):
        self._config = settings
        self._ds_url = None
        self._service = None
        self._channel = None
        self._client = None
        self._bot_token = None
        self._app_token = None
        self._apikey_service = apikey_service
        super().__init__(config, apikey_service, message=message)

    def read_config(self):
        raw: dict = self._config  # type: ignore[assignment]
        self._channel = raw.get("channel") or "全体"
        self._bot_token = raw.get("bot_token")
        self._app_token = raw.get("app_token")

    def setup(self):
        app_cfg = settings.get("app") or {}
        web_port = app_cfg.get("web_port", 3000) if isinstance(app_cfg, dict) else getattr(app_cfg, "web_port", 3000)
        _api_key = self._apikey_service.get_or_create_system_key("MessageWebhook")
        self._ds_url = f"http://127.0.0.1:{web_port}/api/plugin-framework/webhooks/msg_slack/callback?apikey={_api_key}"
        if not self._bot_token:
            return
        try:
            slack_app = App(token=self._bot_token if isinstance(self._bot_token, str) else None)
        except Exception as err:
            ExceptionUtils.exception_traceback(err)
            return
        self._client = slack_app.client

        @slack_app.event("message")
        def slack_message(message):
            local_res = HttpClient(config=HttpClientConfig(timeout=10)).post(self._ds_url or "", json=message)
            log.debug(f"[Slack]message processed: {local_res.text}")

        @slack_app.action(re.compile(r"actionId-\d+"))
        def slack_action(ack, body):
            ack()
            local_res = HttpClient(config=HttpClientConfig(timeout=60)).post(self._ds_url or "", json=body)
            log.debug(f"[Slack]action processed: {local_res.text}")

        @slack_app.event("app_mention")
        def slack_mention(say, body):
            say(f"收到，请稍等... <@{body.get('event', {}).get('user')}>")
            local_res = HttpClient(config=HttpClientConfig(timeout=10)).post(self._ds_url or "", json=body)
            log.debug(f"[Slack]mention processed: {local_res.text}")

        @slack_app.shortcut(re.compile(r"/*"))
        def slack_shortcut(ack, body):
            ack()
            local_res = HttpClient(config=HttpClientConfig(timeout=10)).post(self._ds_url or "", json=body)
            log.debug(f"[Slack]shortcut processed: {local_res.text}")

        if self._app_token:
            try:
                self._service = SocketModeHandler(
                    slack_app, self._app_token if isinstance(self._app_token, str) else None
                )
                self._service.connect()
                log.info("Slack消息接收服务启动")
            except Exception as err:
                ExceptionUtils.exception_traceback(err)
                log.error(f"Slack消息接收服务启动失败: {err}")

    def stop_service(self):
        if self._service:
            try:
                self._service.close()
            except Exception as err:
                log.warn(f"Slack消息接收服务停止失败: {err}")
            log.info("Slack消息接收服务已停止")

    def send_msg(self, title, text="", image="", url="", user_id="") -> tuple[bool, str]:
        if not title and not text:
            return False, "标题和内容不能同时为空"
        if not self._client:
            return False, "消息客户端未就绪"
        try:
            channel = user_id or self.__find_public_channel()
            titles = str(title).split("\n")
            if len(titles) > 1:
                title = titles[0]
                text = "\n".join(titles[1:]) if not text else f"{chr(10).join(titles[1:])}\n{text}"
            block = {"type": "section", "text": {"type": "mrkdwn", "text": f"*{title}*\n{text}"}}
            if image:
                block["accessory"] = {"type": "image", "image_url": image, "alt_text": title}
            blocks = [block]
            if image and url:
                blocks.append(
                    {
                        "type": "actions",
                        "elements": [
                            {
                                "type": "button",
                                "text": {"type": "plain_text", "text": "查看详情", "emoji": True},
                                "value": "click_me_url",
                                "url": url,
                                "action_id": "actionId-url",
                            }
                        ],
                    }
                )
            result = self._client.chat_postMessage(channel=channel, blocks=blocks)
            return True, str(result)
        except Exception as msg_e:
            ExceptionUtils.exception_traceback(msg_e)
            return False, str(msg_e)

    def send_list_msg(self, medias: list, user_id="", title="", **kwargs) -> tuple[bool, str]:
        if not medias:
            return False, "参数有误"
        if not self._client:
            return False, "消息客户端未就绪"
        try:
            channel = user_id or self.__find_public_channel()
            title = title or f"共找到{len(medias)}条相关信息，请选择"
            blocks = [{"type": "section", "text": {"type": "mrkdwn", "text": f"*{title}*"}}]
            for i, media in enumerate(medias):
                blocks.append({"type": "divider"})
                idx = i + 1
                if media.get_star_string():
                    text = (
                        f"{idx}. *<{media.get_detail_url()}|{media.get_title_string()}>*\n"
                        f"{media.get_type_string()}\n"
                        f"{media.get_star_string()}\n"
                        f"{media.get_overview_string(50)}"
                    )
                else:
                    text = (
                        f"{idx}. *<{media.get_detail_url()}|{media.get_title_string()}>*\n"
                        f"{media.get_type_string()}\n"
                        f"{media.get_overview_string(50)}"
                    )
                if media.get_poster_image():
                    blocks.append(
                        {
                            "type": "section",
                            "text": {"type": "mrkdwn", "text": text},
                            "accessory": {
                                "type": "image",
                                "image_url": media.get_poster_image(),
                                "alt_text": media.get_title_string(),
                            },
                        }
                    )
                else:
                    blocks.append({"type": "section", "text": {"type": "mrkdwn", "text": text}})
                blocks.append(
                    {
                        "type": "actions",
                        "elements": [
                            {
                                "type": "button",
                                "text": {"type": "plain_text", "text": "选择", "emoji": True},
                                "value": str(idx),
                                "action_id": f"actionId-{idx}",
                            }
                        ],
                    }
                )
            result = self._client.chat_postMessage(channel=channel, blocks=blocks)
            return True, str(result)
        except Exception as msg_e:
            ExceptionUtils.exception_traceback(msg_e)
            return False, str(msg_e)

    def __find_public_channel(self):
        if not self._client:
            return ""
        try:
            conversations = self._client.conversations_list()
            if not conversations:
                return ""
            for result in conversations:
                for channel in result.get("channels") or []:
                    if channel.get("name") == self._channel:
                        return channel.get("id")
        except SlackApiError as e:
            log.error(f"Slack Error: {e}")
        return ""
