"""LanceDB 向量库 — 可选加速实现（原生混合检索 + RRF 重排）

注意：lancedb 预编译原生库要求 AVX2 CPU，不支持的机器 import 即 SIGILL。
本模块只允许被 vector_store.create_vector_store 在通过 CPU 探测后惰性加载，
严禁被其他模块直接 import。
"""

import json
from pathlib import Path

import lancedb
import pyarrow as pa
from lancedb.rerankers import RRFReranker

import log
from app.agent.rag.models import Chunk, ScoredChunk
from app.agent.rag.vector_store import VectorStore


class LanceDBStore(VectorStore):
    """LanceDB 可选加速（原生混合检索 + RRF 重排，需 AVX2 CPU）"""

    def __init__(self, path: str, dimension: int = 0):
        Path(path).mkdir(parents=True, exist_ok=True)
        self._db = lancedb.connect(path)
        self._dimension = dimension

    def _table(self, namespace: str, dimension: int):
        name = f"kb_{namespace}"
        if name in self._db.table_names():
            return self._db.open_table(name)
        schema = pa.schema(
            [
                ("id", pa.string()),
                ("text", pa.string()),
                ("source", pa.string()),
                ("metadata", pa.string()),
                ("vector", pa.list_(pa.float32(), dimension)),
            ]
        )
        return self._db.create_table(name, schema=schema)

    def upsert(self, namespace: str, chunks: list[Chunk], vectors: list[list[float] | None]) -> int:
        if not chunks:
            return 0
        if len(chunks) != len(vectors):
            raise ValueError(f"chunks({len(chunks)}) 与 vectors({len(vectors)}) 数量不一致")
        pairs: list[tuple[Chunk, list[float]]] = [(c, v) for c, v in zip(chunks, vectors, strict=True) if v is not None]
        if not pairs:
            log.warn(f"[LanceDBStore]全部 embedding 失败，跳过（lancedb 不支持纯文本入库）: {namespace}")
            return 0
        table = self._table(namespace, len(pairs[0][1]))
        rows = [
            {
                "id": c.id,
                "text": c.text,
                "source": c.source,
                "metadata": json.dumps(c.metadata, ensure_ascii=False),
                "vector": v,
            }
            for c, v in pairs
        ]
        table.merge_insert("id").when_matched_update_all().when_not_matched_insert_all().execute(rows)
        try:
            table.create_fts_index("text", replace=True)
        except Exception as e:
            log.warn(f"[LanceDBStore]FTS 索引创建失败: {e}")
        return len(pairs)

    def delete_by_source(self, namespace: str, source: str) -> int:
        name = f"kb_{namespace}"
        if name not in self._db.table_names():
            return 0
        table = self._db.open_table(name)
        before = table.count_rows()
        table.delete(f"source = '{source}'")
        return before - table.count_rows()

    def hybrid_search(
        self, query: str, vector: list[float] | None, namespace: str | None, top_k: int
    ) -> list[ScoredChunk]:
        namespaces = [namespace] if namespace else [n[3:] for n in self._db.table_names() if n.startswith("kb_")]
        results: list[ScoredChunk] = []
        for ns in namespaces:
            name = f"kb_{ns}"
            if name not in self._db.table_names():
                continue
            table = self._db.open_table(name)
            try:
                if vector is None:
                    rows = table.search(query, query_type="fts").limit(top_k).to_list()
                else:
                    rows = (
                        table.search(query_type="hybrid")
                        .vector(vector)
                        .text(query)
                        .rerank(RRFReranker())
                        .limit(top_k)
                        .to_list()
                    )
            except Exception as e:
                if vector is None:
                    log.warn(f"[LanceDBStore]全文检索失败: {e}")
                    continue
                log.warn(f"[LanceDBStore]混合检索失败，退回纯向量: {e}")
                rows = table.search(vector).limit(top_k).to_list()
            for r in rows:
                chunk = Chunk(
                    id=r["id"],
                    text=r["text"],
                    namespace=ns,
                    source=r["source"],
                    metadata=json.loads(r.get("metadata") or "{}"),
                )
                results.append(ScoredChunk(chunk=chunk, score=float(r.get("_relevance_score", 0.0))))
        results.sort(key=lambda x: x.score, reverse=True)
        return results[:top_k]

    def count(self, namespace: str | None = None) -> int:
        names = [f"kb_{namespace}"] if namespace else [n for n in self._db.table_names() if n.startswith("kb_")]
        return sum(self._db.open_table(n).count_rows() for n in names if n in self._db.table_names())
