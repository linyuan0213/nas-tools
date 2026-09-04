"""短程记忆 — ConversationStore（DB 持久化 + 缓存热路径 + token 预算 + 滚动摘要 + 工具执行轨迹）"""

import time

import log
from app.agent.agents.memory.key import MemoryKey
from app.agent.agents.memory.summarizer import Summarizer
from app.db.repositories.agent_conversation_repository import AgentConversationRepository
from app.infrastructure.cache_system import OpenAISessionCache


def estimate_tokens(text: str) -> int:
    """粗略 token 估算（CJK 约 1 字 1 token，英文约 4 字符 1 token，取保守值）"""
    return max(1, len(text) // 2)


class ConversationStore:
    """会话存储：DB 为准、缓存加速；超预算触发滚动摘要"""

    def __init__(
        self,
        repo: AgentConversationRepository,
        summarizer: Summarizer,
        max_tokens: int = 4000,
        keep_recent: int = 10,
        cache=None,
    ):
        self._repo = repo
        self._summarizer = summarizer
        self._max_tokens = max_tokens
        self._keep_recent = keep_recent
        self._cache = cache if cache is not None else OpenAISessionCache

    def load_history(self, key: MemoryKey) -> list[dict]:
        """加载会话消息（缓存优先，miss 回源 DB 并回写）"""
        cached = self._cache.get(key.cache_key())
        if cached is not None:
            return cached
        conv = self._repo.get(key.user_id, key.channel, key.session_id)
        if not conv:
            return []
        rows = self._repo.get_messages_latest(conv.ID)
        messages = [
            {
                "role": r.ROLE,
                "content": r.CONTENT,
                "tool_calls": r.TOOL_CALLS,
                "created_at": r.CREATED_AT.timestamp() if r.CREATED_AT else 0,
            }
            for r in rows
        ]
        self._cache.set(key.cache_key(), messages)
        return messages

    def append(self, key: MemoryKey, role: str, content: str, tool_calls: dict | None = None) -> None:
        """追加消息（DB + 缓存双写），随后按预算滚动摘要"""
        # 先读后写：load_history 在 DB 写入前取旧历史，避免重复追加
        messages = self.load_history(key)
        conv = self._repo.get_or_create(key.user_id, key.channel, key.session_id)
        self._repo.append_message(conv.ID, role, content, tokens=estimate_tokens(content), tool_calls=tool_calls)
        messages.append({"role": role, "content": content, "tool_calls": tool_calls, "created_at": time.time()})
        self._cache.set(key.cache_key(), messages)
        self._maybe_summarize(key, conv.ID, conv.SUMMARY or "", messages)

    def history_for_llm(self, key: MemoryKey) -> list[dict]:
        """组装 LLM 上下文：滚动摘要（若有）+ 最近消息"""
        messages = self.load_history(key)
        conv = self._repo.get(key.user_id, key.channel, key.session_id)
        summary = conv.SUMMARY if conv else ""
        result: list[dict] = []
        if summary:
            result.append({"role": "system", "content": f"此前对话摘要：{summary}"})
        result.extend(messages[-self._keep_recent :])
        return result

    def clear_session(self, session_id: str, user_id: str = "", channel: str = "web") -> None:
        """清空会话（DB + 缓存）"""
        key = MemoryKey(user_id=user_id, channel=channel, session_id=session_id)
        self._repo.delete_conversation(key.user_id, key.channel, key.session_id)
        self._cache.delete(key.cache_key())

    def cleanup_expired(self, ttl_days: int) -> int:
        """删除超过 ttl_days 未更新的会话（记忆过期清理），返回清理的会话数"""
        return self._repo.cleanup_expired(ttl_days)

    def append_tool_trace(self, key: MemoryKey, tool: str, args: dict, success: bool, result_note: str = "") -> None:
        """持久化工具执行轨迹（中断恢复/幂等参考）"""
        self.append(
            key,
            "system",
            f"[已执行] {tool}",
            tool_calls={"tool": tool, "args": args, "success": success, "result": result_note},
        )

    def chat_history(self, key: MemoryKey) -> list[dict]:
        """展示用对话历史：仅 user/assistant 消息（排除滚动摘要与工具轨迹备注），供前端刷新恢复"""
        return [
            {"role": m["role"], "content": m["content"], "ts": m.get("created_at") or 0}
            for m in self.load_history(key)
            if m["role"] in ("user", "assistant") and m.get("content")
        ]

    def _maybe_summarize(self, key: MemoryKey, conversation_id: int, old_summary: str, messages: list[dict]) -> None:
        """超预算：最早一半消息并入滚动摘要"""
        total = sum(estimate_tokens(m.get("content", "")) for m in messages)
        if total <= self._max_tokens or len(messages) <= self._keep_recent:
            return
        split = max(1, (len(messages) - self._keep_recent) // 2)
        archived = messages[:split]
        new_summary = self._summarizer.summarize(old_summary, archived)
        rows = self._repo.get_messages(conversation_id)
        if rows and len(rows) >= split:
            self._repo.delete_messages_before(conversation_id, rows[split - 1].ID)
        self._repo.update_summary(conversation_id, new_summary, total)
        remaining = messages[split:]
        self._cache.set(key.cache_key(), remaining)
        log.info(f"[ConversationStore]会话摘要滚动: 归档 {split} 条, 剩余 {len(remaining)} 条")
