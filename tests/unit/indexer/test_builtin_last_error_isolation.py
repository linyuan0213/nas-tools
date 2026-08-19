"""内置索引器并发竞态修复测试 — last_error 不再跨搜索共享污染统计结果"""

from concurrent.futures import ThreadPoolExecutor
from unittest.mock import MagicMock, patch

from app.indexer.client.builtin import BuiltinIndexer


def _make_client(stats: list) -> BuiltinIndexer:
    """构造 client：mock 站点引擎/进度，统计写入到 list"""
    engine = MagicMock()
    indexer_helper = MagicMock()
    site_cache = MagicMock()
    site_cache.get_sites.return_value = []
    site_cache.check_ratelimit.return_value = False
    progress = MagicMock()
    repo = MagicMock()
    repo.insert_indexer_statistics.side_effect = lambda *a, **k: stats.append(
        (k.get("indexer"), k.get("itype"), k.get("seconds"), k.get("result"))
    )
    client = BuiltinIndexer(
        indexer_helper=indexer_helper,
        site_cache=site_cache,
        site_engine=engine,
        progress_helper=progress,
        download_repo=repo,
        system_config=MagicMock(),
        site_config_repo=MagicMock(),
        idx_config_repo=MagicMock(),
    )
    return client


def _indexer(name):
    idx = MagicMock()
    idx.name = name
    idx.language = "zh"
    idx.domain = f"https://{name}.example.com"
    return idx


def _media():
    m = MagicMock()
    m.type = MagicMock()
    m.tmdb_info = None
    return m


class TestLastErrorIsolation:
    def test_success_empty_records_y(self):
        """空结果且无 last_error → 记 Y（此前会被并发失败污染成 N）"""
        stats: list = []
        client = _make_client(stats)
        with patch.object(
            client,
            "_BuiltinIndexer__search_via_engine",
            return_value=(False, [], ""),
        ) as mocked:
            client.search(0, _indexer("站点A"), "关键词", {}, _media(), MagicMock())
        mocked.assert_called_once()
        assert stats == [("站点A", "builtin", 0, "Y")]

    def test_failure_records_n(self):
        """真实失败（last_error 非空）→ 记 N"""
        stats: list = []
        client = _make_client(stats)
        with patch.object(
            client,
            "_BuiltinIndexer__search_via_engine",
            return_value=(True, [], "HTTP 500"),
        ):
            client.search(0, _indexer("站点B"), "关键词", {}, _media(), MagicMock())
        assert stats == [("站点B", "builtin", 0, "N")]

    def test_concurrent_mixed_failures_no_pollution(self):
        """并发混合成功/失败：成功搜索必须记 Y，不被失败搜索的 last_error 污染"""
        stats: list = []
        client = _make_client(stats)

        def fake_engine(search_word, indexer, mtype=None, page=0, paginate=False):
            # 站点A 失败（HTTP 500），站点C 成功；通过并发制造交错
            if indexer.name == "站点A":
                return True, [], "HTTP 500"
            return False, [{"title": "t", "enclosure": "e", "size": 1}], ""

        with patch.object(client, "_BuiltinIndexer__search_via_engine", side_effect=fake_engine):
            names = ["站点A", "站点C", "站点A", "站点C", "站点C"]
            with ThreadPoolExecutor(max_workers=5) as pool:
                futures = [
                    pool.submit(client.search, 0, _indexer(n), "关键词", {}, _media(), MagicMock()) for n in names
                ]
                for f in futures:
                    f.result()

        results = {name: res for name, res, _, res in stats}
        assert results["站点A"] == "N"
        assert results["站点C"] == "Y"
