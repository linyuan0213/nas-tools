"""长程语义记忆 — 用户偏好/事实（向量库 user_memory 命名空间）

- 存储：复用 VectorStore 抽象，namespace=user_memory，chunk_id 由 user+text 哈希（幂等 upsert）
- 检索：语义检索 top-k，注入对话上下文
- 删除：按用户/文本删除（memory_forget 工具）
- 抽取：会话结束后由 LLM 提炼偏好事实（异步，经 Summarizer 复用）
"""

import hashlib
import re

import log
from app.agent.rag.embedding import EmbeddingService
from app.agent.rag.models import Chunk
from app.agent.rag.vector_store import VectorStore

_MEMORY_NAMESPACE = "user_memory"
_EXTRACT_PROMPT = """你是用户偏好提取器。从以下对话中提取 1-5 条可长期记忆的用户偏好或事实。

规则：
- 每行一条，格式：内容（不含序号）
- 只提取稳定的偏好/事实（如"偏好 4K REMUX"、"只下载 FREE 种子"、"喜欢科幻电影"），不提取一次性操作
- 没有可记忆的内容则输出空行
- 不要客套，不要 Markdown

对话：
{messages}"""


def _memory_id(user_id: str, text: str) -> str:
    raw = f"{user_id}:{text}"
    return hashlib.sha1(raw.encode(), usedforsecurity=False).hexdigest()


def _memory_source(user_id: str, text: str) -> str:
    """每条记忆 source 唯一（供 delete_by_source 精确删除）"""
    return f"user:{user_id}:memory:{_memory_id(user_id, text)[:16]}"


class SemanticMemory:
    """长程语义记忆存储"""

    def __init__(self, store: VectorStore, embedding: EmbeddingService, top_k: int = 5):
        self._store = store
        self._embedding = embedding
        self._top_k = top_k

    def add_memory(self, user_id: str, text: str) -> bool:
        """写入一条用户记忆（幂等：同 user+text 覆盖）"""
        text = text.strip()
        if not text:
            return False
        chunk = Chunk(
            id=_memory_id(user_id, text),
            text=text,
            namespace=_MEMORY_NAMESPACE,
            source=_memory_source(user_id, text),
            metadata={"user_id": user_id},
        )
        vector = self._embedding.embed_query(text)
        if vector is None:
            log.warn("[SemanticMemory]embedding 失败，记忆未写入")
            return False
        self._store.upsert(_MEMORY_NAMESPACE, [chunk], [vector])
        log.info(f"[SemanticMemory]记忆写入: user={user_id} {text[:40]}")
        return True

    def search(self, user_id: str, query: str, top_k: int | None = None) -> list[str]:
        """检索用户记忆（限定该用户的来源）"""
        if not query:
            return []
        vector = self._embedding.embed_query(query)
        hits = self._store.hybrid_search(query, vector, _MEMORY_NAMESPACE, top_k or self._top_k)
        return [h.chunk.text for h in hits if h.chunk.metadata.get("user_id") == user_id and h.chunk.text.strip()]

    def forget(self, user_id: str, text: str) -> int:
        """按文本删除记忆（仅删除与查询最匹配的一条，避免连带删除语义相近的其他偏好）"""
        if not text.strip():
            return 0
        vector = self._embedding.embed_query(text)
        hits = self._store.hybrid_search(text, vector, _MEMORY_NAMESPACE, 10)
        user_hits = [h for h in hits if h.chunk.metadata.get("user_id") == user_id]
        if not user_hits:
            return 0
        # RRF 融合下分数可能同分（向量/全文并列），优先删除与查询文本有词元重叠的记忆，
        # 避免删到同分的无关条目
        query_tokens = set(re.findall(r"[a-zA-Z0-9]+|[\u4e00-\u9fff]+", text))

        def _overlap(hit) -> int:
            mem_tokens = set(re.findall(r"[a-zA-Z0-9]+|[\u4e00-\u9fff]+", hit.chunk.text))
            return len(query_tokens & mem_tokens)

        best = max(user_hits, key=_overlap)
        if self._store.delete_by_source(_MEMORY_NAMESPACE, best.chunk.source):
            return 1
        return 0

    def list(self, user_id: str, limit: int = 50) -> list[dict]:
        """列出该用户全部长程记忆（供管理 UI）"""
        prefix = f"user:{user_id}:memory:"
        try:
            rows = self._store.list_by_source_prefix(_MEMORY_NAMESPACE, prefix, limit)
        except NotImplementedError:
            return []
        return [{"source": r["source"], "text": r["text"]} for r in rows if r.get("text")]


def extract_facts(agent_service, messages: list[dict]) -> list[str]:
    """会话结束后从对话提炼偏好事实；LLM 失败返回空"""
    if not agent_service or not agent_service.ready:
        return []
    try:
        lines = "\n".join(f"{m.get('role')}: {str(m.get('content', ''))[:300]}" for m in messages[-20:])
        result = agent_service.chat(
            messages=[{"role": "user", "content": _EXTRACT_PROMPT.format(messages=lines)}],
            temperature=0.2,
            use_cache=False,
        )
        facts = [line.strip("- ").strip() for line in (result or "").splitlines() if line.strip("- ").strip()]
        return [f for f in facts if len(f) <= 120][:5]
    except Exception as e:
        log.warn(f"[SemanticMemory]事实抽取失败: {e}")
        return []


__all__ = ["SemanticMemory", "extract_facts", "_MEMORY_NAMESPACE"]
