"""
识别失败语料收集 — 命名模式库的数据来源

将「名称不匹配跳过」「TMDB 未匹配」的种子标题追加到
data/identify_misses.jsonl，供 scripts/naming_tool.py misses 查看，
review 后提炼为 config/naming_patterns.yaml 新规则。
"""

import json
import os
import threading
from datetime import datetime

import log
from app.core.settings import settings

_MAX_BYTES = 5 * 1024 * 1024


class MissCollector:
    def __init__(self, path: str | None = None, max_bytes: int = _MAX_BYTES):
        self._path = path or os.path.join(settings.data_path, "identify_misses.jsonl")
        self._max_bytes = max_bytes
        self._lock = threading.Lock()

    def record(self, site: str, title: str, reason: str) -> None:
        if not title:
            return
        try:
            line = json.dumps(
                {
                    "ts": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                    "site": site or "",
                    "reason": reason,
                    "title": title,
                },
                ensure_ascii=False,
            )
            with self._lock:
                self._rotate_if_needed(len(line) + 1)
                with open(self._path, "a", encoding="utf-8") as f:
                    f.write(line + "\n")
        except OSError as e:
            log.debug(f"[MissCollector]写入失败: {e}")

    def _rotate_if_needed(self, incoming: int) -> None:
        if os.path.exists(self._path) and os.path.getsize(self._path) + incoming > self._max_bytes:
            os.replace(self._path, self._path + ".1")


_collector: MissCollector | None = None


def get_miss_collector() -> MissCollector:
    global _collector
    if _collector is None:
        _collector = MissCollector()
    return _collector
