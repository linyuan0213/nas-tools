"""向量库抽象（ABC 与公共常量）

本模块不导入任何具体实现，实现模块（sqlite_vec_store / lancedb_store）依赖本模块，
工厂在 factory.py 中组装，避免循环导入。
"""

from abc import ABC, abstractmethod

from app.agent.rag.models import Chunk, ScoredChunk

_RRF_K = 60


class VectorStore(ABC):
    """向量库抽象"""

    @abstractmethod
    def upsert(self, namespace: str, chunks: list[Chunk], vectors: list[list[float] | None]) -> int:
        """写入/覆盖知识块；vector 为 None 的块按纯文本入库（仅全文检索，降级模式）"""

    @abstractmethod
    def delete_by_source(self, namespace: str, source: str) -> int:
        """按来源删除（增量刷新用）"""

    @abstractmethod
    def hybrid_search(
        self, query: str, vector: list[float] | None, namespace: str | None, top_k: int
    ) -> list[ScoredChunk]:
        """全文 + 向量混合检索；vector 为 None 时退化为纯全文检索"""

    @abstractmethod
    def count(self, namespace: str | None = None) -> int:
        """知识块数量"""

    def close(self) -> None:
        """释放资源（可选实现）"""
