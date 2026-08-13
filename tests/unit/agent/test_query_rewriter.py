"""查询改写单元测试"""

from app.agent.rag.query_rewriter import rewrite_query


class TestRewriteQuery:
    def test_synonym_expansion(self):
        out = rewrite_query("怎么配置下载器")
        assert "下载器" in out
        assert "qbittorrent" in out.lower()
        assert "transmission" in out.lower()

    def test_alias_replacement(self):
        out = rewrite_query("qb 连接参数")
        assert "qBittorrent" in out
        assert "qb" not in out.split()[0] or "qBittorrent" in out

    def test_no_duplicate_synonyms(self):
        out = rewrite_query("下载器 qBittorrent 配置")
        # qBittorrent/transmission 已含则不再追加重复项
        assert out.count("qbittorrent") <= 1

    def test_empty_query(self):
        assert rewrite_query("") == ""

    def test_original_kept(self):
        out = rewrite_query("刷流任务怎么配置")
        assert out.startswith("刷流任务怎么配置")
        assert "保种" in out
