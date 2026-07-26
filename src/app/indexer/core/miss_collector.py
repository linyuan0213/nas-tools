"""
识别失败语料收集 — 命名模式库的数据来源

将「名称不匹配跳过」「TMDB 未匹配」的种子标题追加到
data/identify_misses.jsonl，供 scripts/naming_tool.py misses 查看，
review 后提炼为 config/naming_patterns.yaml 新规则。
"""

import json
import os
import threading
from collections import Counter
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


def weekly_miss_review() -> None:
    """
    识别失败样本周报（ADR-014 P4）：聚合 identify_misses.jsonl 输出摘要并轮转文件。
    由调度器每周触发。
    """
    path = os.path.join(settings.data_path, "identify_misses.jsonl")
    if not os.path.exists(path):
        log.info("[MissReview]无识别失败样本，跳过周报")
        return
    reasons: Counter = Counter()
    sites: Counter = Counter()
    names: Counter = Counter()
    total = 0
    try:
        with open(path, encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    rec = json.loads(line)
                except json.JSONDecodeError:
                    continue
                total += 1
                reasons[rec.get("reason") or "unknown"] += 1
                sites[rec.get("site") or "unknown"] += 1
                names[(rec.get("title") or "")[:40]] += 1
    except OSError as e:
        log.warn(f"[MissReview]读取失败样本失败: {e}")
        return

    log.info(f"[MissReview]本周识别失败样本 {total} 条")
    for reason, cnt in reasons.most_common(5):
        log.info(f"[MissReview]  原因 {reason}: {cnt}")
    for site, cnt in sites.most_common(5):
        log.info(f"[MissReview]  站点 {site}: {cnt}")
    for name, cnt in names.most_common(10):
        log.info(f"[MissReview]  样本 {name}: {cnt}")

    # 轮转：审阅过的样本归档，开始新周期
    try:
        archive = f"{path}.{datetime.now().strftime('%Y%m%d')}"
        os.replace(path, archive)
        log.info(f"[MissReview]样本已归档: {archive}")
    except OSError as e:
        log.warn(f"[MissReview]样本轮转失败: {e}")
