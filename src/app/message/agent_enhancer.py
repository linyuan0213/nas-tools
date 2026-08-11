"""Agent 通知增强器 — 单流替换模板通知，避免与组件自带通知重复

设计要点：
- 不订阅事件总线（组件已就同一事件发送模板通知，重复订阅 = 重复推送）
- 在 dispatcher.sendmsg 出口按 msg_type 拦截：Agent 生成内容替换模板，失败回退模板
- 增强成功时跳过客户端自定义模板渲染（避免模板覆盖 Agent 内容）
"""

import log
from app.agent.config import get_notify_config

_ENHANCE_PROMPT = """你是 NAS 媒体管理系统的通知助手。将以下消息改写成简洁的中文用户通知。

要求：
- 保留关键信息（标题、进度、数量、结果），压缩为 1-3 句
- 口语化，不要客套，不要表格，不要 Markdown 语法符号
- 直接输出通知内容

原标题：{title}
原内容：
{text}"""


class AgentMessageEnhancer:
    """按 msg_type 决定是否增强；LLM 生成失败返回 None（调用方回退原模板）"""

    def __init__(self, agent_service):
        self._agent = agent_service
        self._config = get_notify_config()
        self._msg_types = set(self._config.get("msg_types") or [])

    @property
    def enabled(self) -> bool:
        return bool(self._config.get("enabled")) and self._agent is not None

    def should_enhance(self, msg_type: str | None) -> bool:
        return self.enabled and bool(msg_type) and msg_type in self._msg_types

    def enhance(self, msg_type: str, title: str, text: str) -> str | None:
        """LLM 改写通知；失败返回 None（回退模板）"""
        if not self._agent.ready:
            return None
        prompt = _ENHANCE_PROMPT.format(title=title or "", text=text or "")
        try:
            result = self._agent.chat(
                messages=[{"role": "user", "content": prompt}],
                temperature=self._config.get("temperature", 0.3),
            )
            return (result or "").strip() or None
        except Exception as e:
            log.warn(f"[AgentEnhancer]通知增强失败，回退模板: {e}")
            return None
