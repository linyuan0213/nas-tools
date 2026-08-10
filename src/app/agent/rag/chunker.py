"""Markdown 感知分块器 — 按标题切段，超长滑动窗口再切"""

import hashlib
import re

from app.agent.rag.models import Chunk

_HEADING_RE = re.compile(r"^(#{1,6})\s+(.*)$")


class MarkdownChunker:
    """Markdown 分块：标题分段优先，超长段按滑动窗口切分，标题路径进 metadata"""

    def __init__(self, chunk_size: int = 800, overlap: int = 100):
        if overlap >= chunk_size:
            raise ValueError("overlap 必须小于 chunk_size")
        self._chunk_size = chunk_size
        self._overlap = overlap

    def split(self, text: str, source: str, namespace: str) -> list[Chunk]:
        if not text or not text.strip():
            return []
        sections = self._split_by_heading(text)
        chunks: list[Chunk] = []
        for heading_path, body in sections:
            for piece in self._window_split(body):
                seq = len(chunks)
                chunk_id = hashlib.sha1(f"{namespace}:{source}:{seq}".encode(), usedforsecurity=False).hexdigest()
                chunks.append(
                    Chunk(
                        id=chunk_id,
                        text=piece,
                        namespace=namespace,
                        source=source,
                        metadata={"heading": heading_path} if heading_path else {},
                    )
                )
        return chunks

    def _split_by_heading(self, text: str) -> list[tuple[str, str]]:
        """按标题层级切段，返回 (标题路径, 段落文本) 列表"""
        sections: list[tuple[str, str]] = []
        heading_stack: list[str] = []
        current_lines: list[str] = []
        current_path = ""

        def flush() -> None:
            body = "\n".join(current_lines).strip()
            if body:
                sections.append((current_path, body))

        for line in text.splitlines():
            m = _HEADING_RE.match(line)
            if m:
                flush()
                current_lines = []
                level = len(m.group(1))
                title = m.group(2).strip()
                heading_stack = heading_stack[: level - 1]
                heading_stack.append(title)
                current_path = " > ".join(heading_stack)
            else:
                current_lines.append(line)
        flush()
        return sections

    def _window_split(self, text: str) -> list[str]:
        """超长文本按滑动窗口切分"""
        if len(text) <= self._chunk_size:
            return [text]
        pieces = []
        step = self._chunk_size - self._overlap
        for start in range(0, len(text), step):
            piece = text[start : start + self._chunk_size].strip()
            if piece:
                pieces.append(piece)
            if start + self._chunk_size >= len(text):
                break
        return pieces
