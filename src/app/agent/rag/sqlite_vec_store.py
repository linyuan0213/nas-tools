"""SQLite-vec + FTS5(trigram) 混合检索向量库 — 默认实现，单文件零运维"""

import json
import re
import sqlite3
import struct
from pathlib import Path

import sqlite_vec

import log
from app.agent.rag.models import Chunk, ScoredChunk
from app.agent.rag.vector_store import _RRF_K, VectorStore


class SQLiteVecStore(VectorStore):
    """SQLite-vec + FTS5(trigram) 混合检索，单文件零运维"""

    def __init__(self, path: str, dimension: int = 0):
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        self._db = sqlite3.connect(path, check_same_thread=False)
        self._db.enable_load_extension(True)
        sqlite_vec.load(self._db)
        self._db.enable_load_extension(False)
        # 并发写安全：WAL + busy_timeout（SSE 线程/重建索引可能并行）
        self._db.execute("PRAGMA journal_mode=WAL")
        self._db.execute("PRAGMA busy_timeout=5000")
        self._dimension = dimension
        self._db.execute(
            "CREATE TABLE IF NOT EXISTS kb_chunks("
            "id TEXT PRIMARY KEY, namespace TEXT NOT NULL, source TEXT NOT NULL,"
            " text TEXT NOT NULL, metadata TEXT NOT NULL DEFAULT '{}')"
        )
        self._db.execute(
            "CREATE VIRTUAL TABLE IF NOT EXISTS kb_fts USING fts5(chunk_id UNINDEXED, text, tokenize='trigram')"
        )
        self._db.commit()

    def _ensure_vec_table(self, dimension: int) -> None:
        if self._dimension:
            return
        if self._table_exists("kb_vec"):
            # 重开已有库：从存量向量恢复维度；维度变化需重建索引
            row = self._db.execute("SELECT length(vector) FROM kb_vec LIMIT 1").fetchone()
            if row:
                existing = row[0] // 4
                self._dimension = existing
                if existing != dimension:
                    raise ValueError(
                        f"向量维度不匹配：库内为 {existing}，当前 embedding 模型为 {dimension}。"
                        "请先 POST /api/agent/kb/reindex 重建索引"
                    )
            return
        self._dimension = dimension
        self._db.execute(
            "CREATE VIRTUAL TABLE IF NOT EXISTS kb_vec USING vec0("
            f"chunk_id TEXT PRIMARY KEY, vector float[{dimension}])"
        )
        self._db.commit()

    def _table_exists(self, name: str) -> bool:
        row = self._db.execute("SELECT 1 FROM sqlite_master WHERE name = ?", (name,)).fetchone()
        return row is not None

    @staticmethod
    def _pack(vector: list[float]) -> bytes:
        return struct.pack(f"{len(vector)}f", *vector)

    def upsert(self, namespace: str, chunks: list[Chunk], vectors: list[list[float] | None]) -> int:
        if not chunks:
            return 0
        if len(chunks) != len(vectors):
            raise ValueError(f"chunks({len(chunks)}) 与 vectors({len(vectors)}) 数量不一致")
        # 首次遇到真实向量时才建 vec 表（支持纯文本降级索引）
        first_vector = next((v for v in vectors if v is not None), None)
        if first_vector is not None:
            self._ensure_vec_table(len(first_vector))
        with self._db:
            for chunk, vector in zip(chunks, vectors, strict=True):
                self._db.execute(
                    "INSERT OR REPLACE INTO kb_chunks(id, namespace, source, text, metadata) VALUES(?,?,?,?,?)",
                    (chunk.id, namespace, chunk.source, chunk.text, json.dumps(chunk.metadata, ensure_ascii=False)),
                )
                self._db.execute("DELETE FROM kb_fts WHERE chunk_id = ?", (chunk.id,))
                self._db.execute("INSERT INTO kb_fts(chunk_id, text) VALUES(?,?)", (chunk.id, chunk.text))
                if self._table_exists("kb_vec"):
                    self._db.execute("DELETE FROM kb_vec WHERE chunk_id = ?", (chunk.id,))
                    if vector is not None:
                        self._db.execute(
                            "INSERT INTO kb_vec(chunk_id, vector) VALUES(?,?)", (chunk.id, self._pack(vector))
                        )
        return len(chunks)

    def delete_by_source(self, namespace: str, source: str) -> int:
        rows = self._db.execute(
            "SELECT id FROM kb_chunks WHERE namespace = ? AND source = ?", (namespace, source)
        ).fetchall()
        if not rows:
            return 0
        with self._db:
            vec_exists = self._table_exists("kb_vec")
            for (chunk_id,) in rows:
                self._db.execute("DELETE FROM kb_fts WHERE chunk_id = ?", (chunk_id,))
                if vec_exists:
                    self._db.execute("DELETE FROM kb_vec WHERE chunk_id = ?", (chunk_id,))
                self._db.execute("DELETE FROM kb_chunks WHERE id = ?", (chunk_id,))
        return len(rows)

    def hybrid_search(
        self, query: str, vector: list[float] | None, namespace: str | None, top_k: int
    ) -> list[ScoredChunk]:
        candidate_k = max(top_k * 4, 20)
        fts_hits = self._fts_search(query, namespace, candidate_k)
        vec_hits = self._vec_search(vector, namespace, candidate_k)
        return self._rrf_fuse(fts_hits, vec_hits, top_k)

    @staticmethod
    def _build_fts_query(query: str) -> str:
        """构建 FTS5 查询：拉丁词整词保留，CJK 连续段按 3 字滑窗拆分，OR 连接保证召回"""
        terms: list[str] = []
        for token in re.findall(r"[a-zA-Z0-9]+|[一-鿿぀-ヿ]+", query):
            if re.fullmatch(r"[a-zA-Z0-9]+", token):
                if len(token) >= 3:
                    terms.append(token)
            elif len(token) <= 3:
                terms.append(token)
            else:
                terms.extend(token[i : i + 3] for i in range(len(token) - 2))
        if not terms:
            return ""
        return " OR ".join(f'"{t.replace(chr(34), chr(34) * 2)}"' for t in terms)

    def _fts_search(self, query: str, namespace: str | None, limit: int) -> list[str]:
        """FTS5 BM25 检索，返回按相关度排序的 chunk_id 列表"""
        match = self._build_fts_query(query)
        if not match:
            return []
        sql = "SELECT f.chunk_id FROM kb_fts f JOIN kb_chunks c ON c.id = f.chunk_id WHERE kb_fts MATCH ?"
        params: list = [match]
        if namespace:
            sql += " AND c.namespace = ?"
            params.append(namespace)
        sql += " ORDER BY bm25(kb_fts) LIMIT ?"
        params.append(limit)
        try:
            return [r[0] for r in self._db.execute(sql, tuple(params)).fetchall()]
        except sqlite3.OperationalError as e:
            log.warn(f"[SQLiteVecStore]FTS 检索失败: {e}, query={query[:50]}")
            return []

    def _vec_search(self, vector: list[float] | None, namespace: str | None, limit: int) -> list[str]:
        """向量 KNN 检索，返回按距离排序的 chunk_id 列表"""
        if not vector:
            return []
        if not self._dimension:
            # 重开已有库时从存量向量恢复维度
            if not self._table_exists("kb_vec"):
                return []
            row = self._db.execute("SELECT length(vector) FROM kb_vec LIMIT 1").fetchone()
            if not row:
                return []
            self._dimension = row[0] // 4
        fetch_k = limit * 3 if namespace else limit
        try:
            rows = self._db.execute(
                "SELECT chunk_id, distance FROM kb_vec WHERE vector MATCH ? AND k = ?",
                (self._pack(vector), fetch_k),
            ).fetchall()
        except sqlite3.OperationalError as e:
            log.warn(f"[SQLiteVecStore]向量检索失败: {e}")
            return []
        ids = [r[0] for r in rows]
        if not namespace:
            return ids[:limit]
        if not ids:
            return []
        placeholders = ",".join("?" * len(ids))
        allowed = {
            r[0]
            for r in self._db.execute(
                f"SELECT id FROM kb_chunks WHERE namespace = ? AND id IN ({placeholders})",  # nosec B608 - 值全部参数化
                (namespace, *ids),
            ).fetchall()
        }
        return [i for i in ids if i in allowed][:limit]

    def _rrf_fuse(self, fts_ids: list[str], vec_ids: list[str], top_k: int) -> list[ScoredChunk]:
        """RRF 融合两路排序"""
        scores: dict[str, float] = {}
        for rank, cid in enumerate(fts_ids):
            scores[cid] = scores.get(cid, 0.0) + 1.0 / (_RRF_K + rank + 1)
        for rank, cid in enumerate(vec_ids):
            scores[cid] = scores.get(cid, 0.0) + 1.0 / (_RRF_K + rank + 1)
        if not scores:
            return []
        top_ids = sorted(scores, key=lambda cid: scores[cid], reverse=True)[:top_k]
        placeholders = ",".join("?" * len(top_ids))
        rows = self._db.execute(
            f"SELECT id, namespace, source, text, metadata FROM kb_chunks WHERE id IN ({placeholders})",  # nosec B608 - 值全部参数化
            tuple(top_ids),
        ).fetchall()
        chunk_map = {
            r[0]: Chunk(id=r[0], namespace=r[1], source=r[2], text=r[3], metadata=json.loads(r[4] or "{}"))
            for r in rows
        }
        return [ScoredChunk(chunk=chunk_map[cid], score=scores[cid]) for cid in top_ids if cid in chunk_map]

    def list_by_source_prefix(self, namespace: str, prefix: str, limit: int = 50) -> list[dict]:
        rows = self._db.execute(
            "SELECT id, source, text FROM kb_chunks WHERE namespace = ? AND source LIKE ? LIMIT ?",
            (namespace, f"{prefix}%", limit),
        ).fetchall()
        return [{"id": r[0], "source": r[1], "text": r[2]} for r in rows]

    def count(self, namespace: str | None = None) -> int:
        if namespace:
            row = self._db.execute("SELECT COUNT(*) FROM kb_chunks WHERE namespace = ?", (namespace,)).fetchone()
        else:
            row = self._db.execute("SELECT COUNT(*) FROM kb_chunks").fetchone()
        return int(row[0]) if row else 0

    def close(self) -> None:
        self._db.close()
