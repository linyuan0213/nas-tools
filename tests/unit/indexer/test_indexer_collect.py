"""站点级超时熔断与进度单调化测试"""

import time
from concurrent.futures import Future
from types import SimpleNamespace

from app.domain.enums import ProgressKey
from app.indexer.indexer import collect_search_results
from app.infrastructure.progress import ProgressTracker


def _site(name):
    return SimpleNamespace(name=name)


def _client():
    return SimpleNamespace(client_id="builtin")


class TestCollectSearchResults:
    def test_completed_results_aggregated(self):
        f1, f2 = Future(), Future()
        f1.set_result([{"title": "a"}])
        f2.set_result([{"title": "b"}, {"title": "c"}])
        advances = []

        results = collect_search_results(
            {f1: (_client(), _site("S1")), f2: (_client(), _site("S2"))},
            timeout_for=lambda _i: 5,
            on_advance=lambda c, t, i, to, e, s: advances.append((c, i.name, to)),
        )

        assert {r["title"] for r in results} == {"a", "b", "c"}
        assert len(advances) == 2
        assert all(not to for _, _, to in advances)

    def test_slow_site_abandoned(self):
        f1, slow = Future(), Future()
        f1.set_result([{"title": "a"}])
        advances = []

        start = time.monotonic()
        results = collect_search_results(
            {f1: (_client(), _site("S1")), slow: (_client(), _site("SlowSite"))},
            timeout_for=lambda _i: 0.2,
            on_advance=lambda c, t, i, to, e, s: advances.append((c, i.name, to)),
        )
        elapsed = time.monotonic() - start

        assert results == [{"title": "a"}]
        assert elapsed < 5
        assert ("SlowSite", True) in [(name, to) for _, name, to in advances]

    def test_exception_site_not_fatal(self):
        f1, bad = Future(), Future()
        f1.set_result([{"title": "a"}])
        bad.set_exception(RuntimeError("boom"))

        results = collect_search_results(
            {f1: (_client(), _site("S1")), bad: (_client(), _site("BadSite"))},
            timeout_for=lambda _i: 5,
        )

        assert results == [{"title": "a"}]


class TestUpdateMax:
    def test_value_never_decreases(self):
        tracker = ProgressTracker()
        key = ProgressKey.Search
        tracker.start(key)
        tracker.update_max(value=50, text="half", ptype=key)
        tracker.update_max(value=20, text="back", ptype=key)
        detail = tracker.get_process(key)
        assert detail is not None
        assert detail["value"] == 50
        assert detail["text"] == "back"
        tracker.update_max(value=80, ptype=key)
        detail2 = tracker.get_process(key)
        assert detail2 is not None
        assert detail2["value"] == 80
        tracker.end(key)

    def test_text_only_update_keeps_value(self):
        tracker = ProgressTracker()
        key = ProgressKey.Search
        tracker.start(key)
        tracker.update_max(value=30, ptype=key)
        tracker.update(text="working...", ptype=key)
        detail = tracker.get_process(key)
        assert detail is not None
        assert detail["value"] == 30
        assert detail["text"] == "working..."
        tracker.end(key)
