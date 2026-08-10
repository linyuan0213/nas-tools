"""RAG 数据模型"""

from dataclasses import dataclass, field


@dataclass(frozen=True)
class Chunk:
    """知识块 — id 由 namespace+source+seq 生成，保证重索引幂等"""

    id: str
    text: str
    namespace: str
    source: str
    metadata: dict = field(default_factory=dict)


@dataclass(frozen=True)
class ScoredChunk:
    """带分数的检索结果"""

    chunk: Chunk
    score: float
