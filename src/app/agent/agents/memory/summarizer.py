"""滚动摘要器 — 会话超预算时压缩最早消息段"""

import log

_SUMMARY_PROMPT = (
    "请将以下对话历史压缩为简洁的中文摘要，保留关键事实、用户意图与已完成操作。"
    "直接输出摘要文本，不超过 200 字。\n\n"
    "已有摘要（若无则为空）：\n{old_summary}\n\n"
    "待压缩对话：\n{messages}"
)


class Summarizer:
    """滚动摘要 — 复用 AgentService.chat（低温度）"""

    def __init__(self, svc):
        self._svc = svc

    @property
    def ready(self) -> bool:
        return self._svc.ready

    def summarize(self, old_summary: str, messages: list[dict]) -> str:
        """压缩消息段为摘要；LLM 不可用时退化为截断拼接"""
        if not messages:
            return old_summary
        if not self.ready:
            log.warn("[Summarizer]LLM 不可用，退化为截断摘要")
            joined = " / ".join(f"{m.get('role', '?')}: {str(m.get('content', ''))[:50]}" for m in messages[-5:])
            return (old_summary + " | " + joined)[:500]
        lines = [f"{m.get('role', '?')}: {str(m.get('content', ''))[:200]}" for m in messages]
        prompt = _SUMMARY_PROMPT.format(old_summary=old_summary or "（无）", messages="\n".join(lines))
        try:
            result = self._svc.chat(messages=[{"role": "user", "content": prompt}], temperature=0.3)
            return result.strip() or old_summary
        except Exception as e:
            log.warn(f"[Summarizer]摘要生成失败: {e}")
            return old_summary
