"""MarkdownChunker 单元测试"""

import pytest

from app.agent.rag.chunker import MarkdownChunker


class TestMarkdownChunker:
    def test_empty_text_returns_empty(self):
        chunker = MarkdownChunker()
        assert chunker.split("", "s", "faq") == []
        assert chunker.split("   \n  ", "s", "faq") == []

    def test_overlap_must_be_smaller_than_chunk_size(self):
        with pytest.raises(ValueError):
            MarkdownChunker(chunk_size=100, overlap=100)

    def test_short_text_single_chunk(self):
        chunker = MarkdownChunker(chunk_size=800, overlap=100)
        chunks = chunker.split("这是一段普通文本。", "docs/a.md", "faq")
        assert len(chunks) == 1
        assert chunks[0].namespace == "faq"
        assert chunks[0].source == "docs/a.md"

    def test_heading_split_with_path_metadata(self):
        text = "# 安装\n安装步骤内容\n\n## 依赖\n依赖列表内容\n\n# 配置\n配置说明内容\n"
        chunker = MarkdownChunker(chunk_size=800, overlap=100)
        chunks = chunker.split(text, "docs/install.md", "faq")
        assert len(chunks) == 3
        assert chunks[0].metadata["heading"] == "安装"
        assert chunks[1].metadata["heading"] == "安装 > 依赖"
        assert chunks[2].metadata["heading"] == "配置"

    def test_long_text_window_split(self):
        text = "字" * 2000
        chunker = MarkdownChunker(chunk_size=800, overlap=100)
        chunks = chunker.split(text, "s", "faq")
        assert len(chunks) >= 3
        assert all(len(c.text) <= 800 for c in chunks)

    def test_chunk_id_stable_for_same_source(self):
        chunker = MarkdownChunker()
        text = "# 标题\n内容"
        ids1 = [c.id for c in chunker.split(text, "s", "faq")]
        ids2 = [c.id for c in chunker.split(text, "s", "faq")]
        assert ids1 == ids2
