"""LogSearchService 单元测试 — 磁盘日志关键字检索与多行续行保留."""

# ruff: noqa: E501

from app.services.log_search_service import LogSearchService

HUMAN_LINES = """\
2026-09-03 10:00:00.123 |INFO    | a.py : a.run:  1 | - [autosignin] [Rousi]签到成功
2026-09-03 10:00:01.123 |WARNING | b.py : b.run:  2 | - [autosignin] [Rousi]签到请求异常: HttpClientError("Client error '409 Conflict'")
    File "/app/x.py", line 10, in run
    raise err
2026-09-03 10:00:02.123 |INFO    | c.py : c.run:  3 | - [其他]普通日志，无关键字
    未命中条目的续行（应被跳过，不得串到其它条目）
2026-09-03 10:00:03.123 |ERROR   | d.py : d.run:  4 | - [autosignin] [Rousi]签到再次失败
    命中条目的续行（应保留）
"""

JSON_LINES = """\
{"timestamp": "2026-09-03 10:00:00.123", "level": "INFO", "message": "[autosignin] [Rousi]签到成功"}
{"timestamp": "2026-09-03 10:00:01.123", "level": "INFO", "message": "[其他]无关键字日志"}
{"timestamp": "2026-09-03 10:00:02.123", "level": "ERROR", "message": "[autosignin] [Rousi]签到失败 boom"}
"""


class TestLogSearchServiceKeywordSearch:
    def test_human_keyword_match_keeps_multiline(self, tmp_path):
        (tmp_path / "nexus-media.log").write_text(HUMAN_LINES, encoding="utf-8")
        svc = LogSearchService(log_dir=str(tmp_path))
        res = svc.search(keyword="rousi", hours=None)
        assert res["total"] == 3, res
        texts = "\n".join(item.get("text", "") for item in res["items"])
        # 命中条目的多行续行（异常堆栈 / 结尾续行）应保留在消息内
        assert 'File "/app/x.py"' in texts
        assert "命中条目的续行（应保留）" in texts
        # 未命中条目下的续行不得被错误拼接到其它命中条目
        assert "未命中条目的续行" not in texts

    def test_human_keyword_no_match_fast(self, tmp_path):
        (tmp_path / "nexus-media.log").write_text(HUMAN_LINES, encoding="utf-8")
        svc = LogSearchService(log_dir=str(tmp_path))
        res = svc.search(keyword="不存在的关键字xyz", hours=None)
        assert res["total"] == 0
        assert res["items"] == []

    def test_json_keyword_search(self, tmp_path):
        (tmp_path / "nexus-media.log").write_text(JSON_LINES, encoding="utf-8")
        svc = LogSearchService(log_dir=str(tmp_path))
        res = svc.search(keyword="rousi", hours=None)
        assert res["total"] == 2, res
        assert all("rousi" in (it.get("text") or "").lower() for it in res["items"])

    def test_source_and_level_still_filter(self, tmp_path):
        (tmp_path / "nexus-media.log").write_text(HUMAN_LINES, encoding="utf-8")
        svc = LogSearchService(log_dir=str(tmp_path))
        res = svc.search(keyword="rousi", level="ERROR", hours=None)
        assert res["total"] == 1
        assert "再次失败" in res["items"][0]["text"]
