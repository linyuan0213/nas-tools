"""ContextBuilder — 上下文组装器

按分层组装 LLM 上下文：system 提示词（工具规则）→ 会话历史（含滚动摘要）。
"""

from dataclasses import dataclass, field


@dataclass
class BuiltContext:
    messages: list[dict] = field(default_factory=list)

    def append(self, role: str, content: str) -> None:
        if content:
            self.messages.append({"role": role, "content": content})


class ContextBuilder:
    """分层组装对话上下文"""

    def build(
        self,
        *,
        system_prompt: str = "",
        history: list[dict] | None = None,
        user_input: str = "",
    ) -> BuiltContext:
        """组装顺序：system → 记忆/历史 → 用户输入"""
        ctx = BuiltContext()
        if system_prompt:
            ctx.append("system", system_prompt)
        for msg in history or []:
            role = msg.get("role", "user")
            content = msg.get("content", "")
            if content:
                ctx.append(role, content)
        if user_input:
            ctx.append("user", user_input)
        return ctx
