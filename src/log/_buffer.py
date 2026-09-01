"""线程安全的内存日志缓冲区."""

import threading
import time
from collections import deque
from typing import Any

from ._source import extract_source


class LogBuffer:
    """
    线程安全的内存日志缓冲区，用于实时日志推送。
    通过单调递增计数器解决 maxlen 场景下无法识别新增日志的问题。
    """

    def __init__(self, maxlen: int = 200):
        self._queue: deque[dict[str, Any]] = deque(maxlen=maxlen)
        self._lock = threading.Lock()
        self._counter = 0

    def append(self, level: str, text: str) -> int:
        """添加一条日志记录，返回当前计数器值。"""
        source, text = extract_source(text)

        log_entry = {
            "time": time.strftime("%H:%M:%S", time.localtime(time.time())),
            "level": level,
            "source": source,
            "text": text,
        }
        with self._lock:
            self._queue.append(log_entry)
            self._counter += 1
            return self._counter

    def get_logs(self, source: str | None = None, last_counter: int = 0) -> tuple[list[dict[str, Any]], int]:
        """获取自 last_counter 以来新增的所有日志。返回 (logs, current_counter)。"""
        with self._lock:
            total = self._counter
            if last_counter >= total:
                return [], total
            count = min(total - last_counter, len(self._queue))
            logs = list(self._queue)[-count:] if count > 0 else []
        if source:
            logs = [lg for lg in logs if lg.get("source") == source]
        return logs, total

    def __len__(self) -> int:
        with self._lock:
            return len(self._queue)

    def __iter__(self):
        with self._lock:
            return iter(list(self._queue))

    def __getitem__(self, index):
        with self._lock:
            return list(self._queue)[index]

    @property
    def counter(self) -> int:
        with self._lock:
            return self._counter
