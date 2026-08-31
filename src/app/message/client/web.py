"""内置 Web 消息客户端 — 交互页作为一等消息渠道

事件通知经 dispatcher.sendmsg 按开关分发到本客户端，写入 WebMessageStore，
由内置消息交互页消费。开关与模板配置与第三方渠道一致（通知设置页统一管理）。
"""

from app.message.client._base import _IMessageClient
from app.message.schema import MessageConfigSchema
from app.message.web_store import WebMessageStore


class WebMessage(_IMessageClient):
    schema = "web"
    config_schema = MessageConfigSchema(
        name="内置消息页",
        icon_url="/static/img/message/web.svg",
        fields=[],
    )

    def read_config(self):
        self._enabled = self._config.get("enabled", True)

    def send_msg(self, title, text="", image="", url="", user_id="") -> tuple[bool, str]:
        if not title and not text:
            return False, "消息内容为空"
        WebMessageStore.instance().add(
            title=str(title), content=str(text), kind="notify", image=image or "", url=url or "", user_id=user_id or ""
        )
        return True, ""

    def send_list_msg(self, medias: list, user_id="", title="", **kwargs) -> tuple[bool, str]:
        WebMessageStore.instance().add(
            title=str(title),
            content="",
            kind="list",
            items=WebMessageStore.build_list_items(medias),
            user_id=user_id or "",
        )
        return True, ""
