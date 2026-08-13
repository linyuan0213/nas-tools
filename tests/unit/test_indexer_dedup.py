"""
索引器多客户端去重测试
"""

from app.indexer.indexer import Indexer


def test_dedup_builtin_priority():
    """builtin 来源的同名结果应优先保留"""
    results = [
        {"title": "Movie 2024", "size": "1000", "_indexer_source": "jackett", "_indexer_order": 1},
        {"title": "Movie 2024", "size": "1000", "_indexer_source": "builtin", "_indexer_order": 2},
    ]
    deduped = Indexer._dedup(results)
    assert len(deduped) == 1
    assert deduped[0]["_indexer_source"] == "builtin"


def test_dedup_order_priority():
    """同来源时 order_seq 大的优先（order_seq=100-pri，pri 小=主站优先）"""
    results = [
        {"title": "Movie 2024", "size": "1000", "_indexer_source": "jackett", "_indexer_order": 5},
        {"title": "Movie 2024", "size": "1000", "_indexer_source": "jackett", "_indexer_order": 3},
    ]
    deduped = Indexer._dedup(results)
    assert len(deduped) == 1
    assert deduped[0]["_indexer_order"] == 5


def test_dedup_different_sizes():
    """不同 size 不应去重"""
    results = [
        {"title": "Movie 2024", "size": "1000", "_indexer_source": "builtin", "_indexer_order": 1},
        {"title": "Movie 2024", "size": "2000", "_indexer_source": "jackett", "_indexer_order": 2},
    ]
    deduped = Indexer._dedup(results)
    assert len(deduped) == 2
