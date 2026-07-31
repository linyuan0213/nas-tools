"""识别失败语料收集器测试"""

import json
import os

from app.indexer.core.miss_collector import MissCollector


class TestMissCollector:
    def test_record_writes_jsonl(self, tmp_path):
        path = str(tmp_path / "misses.jsonl")
        collector = MissCollector(path=path)
        collector.record("TestSite", "某种子标题", "quick_name_miss")

        with open(path, encoding="utf-8") as f:
            rec = json.loads(f.readline())
        assert rec["site"] == "TestSite"
        assert rec["title"] == "某种子标题"
        assert rec["reason"] == "quick_name_miss"
        assert rec["ts"]

    def test_empty_title_ignored(self, tmp_path):
        path = str(tmp_path / "misses.jsonl")
        collector = MissCollector(path=path)
        collector.record("TestSite", "", "quick_name_miss")
        assert not os.path.exists(path)

    def test_rotation(self, tmp_path):
        path = str(tmp_path / "misses.jsonl")
        collector = MissCollector(path=path, max_bytes=200)
        for i in range(20):
            collector.record("S", f"标题{i}" * 10, "tmdb_no_match")

        assert os.path.exists(path + ".1")
        assert os.path.getsize(path) <= 200 + 500

    def test_concurrent_writes(self, tmp_path):
        import threading

        path = str(tmp_path / "misses.jsonl")
        collector = MissCollector(path=path)
        threads = [threading.Thread(target=lambda: collector.record("S", "标题", "r")) for _ in range(10)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        with open(path, encoding="utf-8") as f:
            lines = [ln for ln in f if ln.strip()]
        assert len(lines) == 10
