"""AgentEnhancingDispatcher — 通知发送出口的单流 Agent 增强包装器

包装真实 MessageDispatcher：在 sendmsg 出口按 msg_type 拦截，
Agent 生成内容替换模板（失败回退模板），跳过客户端模板渲染，避免重复通知。
"""

from typing import Any

import log
from app.message.agent_enhancer import AgentMessageEnhancer
from app.message.formatter import dialect_for_channel, format_agent_message


class AgentEnhancingDispatcher:
    """通知出口增强代理 — 只处理配置的 msg_type，其余原样透传"""

    def __init__(self, inner: Any, enhancer: AgentMessageEnhancer):
        self._inner = inner
        self._enhancer = enhancer

    def sendmsg(
        self,
        client,
        title,
        text: str | None = None,
        image: str | None = None,
        url: str | None = None,
        user_id: str = "",
        msg_type: str | None = None,
        variables: dict | None = None,
        template_engine=None,
    ):
        if self._enhancer.should_enhance(msg_type):
            assert msg_type is not None
            enhanced = self._enhancer.enhance(msg_type, title or "", text or "")
            if enhanced:
                ctype = client.get("ctype") if isinstance(client, dict) else None
                dialect = dialect_for_channel(ctype)
                # 替换内容并跳过客户端模板渲染（msg_type/variables 置空），避免模板覆盖 Agent 内容
                return self._inner.sendmsg(
                    client,
                    title="智能通知",
                    text=format_agent_message(enhanced, dialect),
                    image=image,
                    url=url,
                    user_id=user_id,
                    msg_type=None,
                    variables=None,
                    template_engine=None,
                )
            log.info(f"[AgentEnhancingDispatcher]增强失败，回退模板通知: {msg_type}")
        return self._inner.sendmsg(client, title, text, image, url, user_id, msg_type, variables, template_engine)

    def _do_sendmsg(self, client, title, text, image, url, user_id):
        return self._inner._do_sendmsg(client, title, text, image, url, user_id)

    def __getattr__(self, name: str) -> Any:
        return getattr(self._inner, name)
