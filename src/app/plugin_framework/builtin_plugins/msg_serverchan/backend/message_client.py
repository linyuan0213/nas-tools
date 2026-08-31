from serverchan_sdk import sc_send

from app.message.client._base import _IMessageClient
from app.message.schema import ConfigField, MessageConfigSchema
from app.utils import ExceptionUtils


class ServerChan(_IMessageClient):
    schema = "serverchan"
    config_schema = MessageConfigSchema(
        name="Server酱",
        icon_url="/api/plugin-framework/plugins/msg_serverchan/assets/serverchan.png",
        fields=[
            ConfigField(
                id="sckey",
                required=True,
                title="SCKEY",
                type="text",
                tooltip="填写ServerChan的API Key，SCT类型，在https://sct.ftqq.com/中申请",
                placeholder="SCT...",
            ),
        ],
    )

    def read_config(self):
        cfg = self._config or {}
        self._sckey = cfg.get("sckey")

    def send_msg(self, title, text="", image="", url="", user_id=""):
        if not title and not text:
            return False, "标题和内容不能同时为空"
        if not self._sckey:
            return False, "参数未配置"
        try:
            formatted_text = self._format_message_content(text, image, url)
            ret_json = sc_send(self._sckey, title, formatted_text, {"tags": "NEXUS_MEDIA"})
            errno = ret_json.get("code")
            error = ret_json.get("message")
            return (True, error) if errno == 0 else (False, error)
        except Exception as msg_e:
            ExceptionUtils.exception_traceback(msg_e)
            return False, str(msg_e)

    def _format_message_content(self, text, image="", url=""):
        formatted_content = []
        if text:
            formatted_text = text.replace("\n\n", "\n\n").replace("\n", "\n\n")
            formatted_content.append(formatted_text)
        if image:
            formatted_content.append("")
            formatted_content.append(f"![封面图片]({image})")
        if url:
            formatted_content.append("")
            formatted_content.append(f"[查看详情]({url})")
        return "\n\n".join(formatted_content)

    def send_list_msg(self, medias: list, user_id="", title="", **kwargs):
        if not self._sckey:
            return False, "参数未配置"
        if not isinstance(medias, list) or not medias:
            return False, "数据错误或为空"
        try:
            content_parts = []
            first_media = medias[0]
            if hasattr(first_media, "get_message_image"):
                image_url = first_media.get_message_image()
                if image_url:
                    content_parts.append(f"![封面图片]({image_url})")
                    content_parts.append("")
            for index, media in enumerate(medias, 1):
                media_info = []
                if hasattr(media, "get_title_string"):
                    media_info.append(f"**{index}. {media.get_title_string()}**")
                type_info = []
                if hasattr(media, "get_type_string"):
                    type_info.append(media.get_type_string())
                if hasattr(media, "get_vote_string") and media.get_vote_string():
                    type_info.append(media.get_vote_string())
                if type_info:
                    media_info.append(f"*{', '.join(type_info)}*")
                if hasattr(media, "get_detail_url") and media.get_detail_url():
                    media_info.append(f"[查看详情]({media.get_detail_url()})")
                content_parts.append("\n\n".join(media_info))
            formatted_content = "\n\n---\n\n".join(content_parts)
            ret_json = sc_send(self._sckey, title or "媒体推荐", formatted_content, {"tags": "NEXUS_MEDIA"})
            errno = ret_json.get("code")
            error = ret_json.get("message")
            return (True, error) if errno == 0 else (False, error)
        except Exception as msg_e:
            ExceptionUtils.exception_traceback(msg_e)
            return False, str(msg_e)
