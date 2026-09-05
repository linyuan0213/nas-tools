"""日志文件全文搜索与导出服务。

从磁盘日志文件（含轮转文件）中解析并检索日志，
供系统日志页面的搜索与导出使用，弥补内存缓冲仅保留最近 N 条的限制。
默认仅检索最近一天（24h）的日志，避免扫描全部历史文件导致过大/过慢。
"""

import json
import mmap
import os
import re
import time
from datetime import datetime, timedelta
from typing import Any, Iterator

import log
from app.core.settings import settings
from log._source import extract_source

__all__ = ["LogSearchService"]

# 人类可读格式：2026-09-01 13:15:43.327 |INFO    | service.py : service.__init__:  42 | - [MediaService]xxx
_HUMAN_LINE_PATTERN = re.compile(r"^(\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}\.\d{3}) \|([A-Za-z]+)\s*\| .*? \| - (.*)$")


def _looks_like_human_header(line: str) -> bool:
    """廉价判断是否为新日志条目行（YYYY-MM-DD HH:... 开头），用于关键字预筛跳过无关行."""
    return len(line) >= 12 and line[0:4].isdigit() and line[4] == "-" and line[7] == "-"


# 默认搜索时间窗口（小时）：仅检索最近一天，控制读取量与导出体积
DEFAULT_LOG_WINDOW_HOURS = 24

# 单次检索最多解析/返回的命中条数（防止高频来源拖垮接口），超过则 truncated=True
MAX_MATCHES = 20000


class LogSearchService:
    """基于日志文件的全文搜索服务."""

    def __init__(self, log_dir: str | None = None, module: str = "nexus-media"):
        self._log_dir = log_dir
        self._module = module

    def _resolve_log_dir(self) -> str | None:
        """解析日志目录；未配置时回退到默认 data/logs."""
        if self._log_dir:
            return self._log_dir
        log_cfg = settings.get("log") or {}
        logpath = log_cfg.get("path") or ""
        if not logpath:
            logpath = os.path.join(settings.data_path, "logs")
        if not os.path.isdir(logpath):
            return None
        return logpath

    def _list_log_files(self, min_mtime: float | None = None) -> list[str]:
        """按时间升序返回日志文件（最旧在前，当前文件最后）；可跳过修改时间早于 min_mtime 的旧文件."""
        log_dir = self._resolve_log_dir()
        if not log_dir:
            return []
        files: list[str] = []
        for name in os.listdir(log_dir):
            full = os.path.join(log_dir, name)
            if os.path.isfile(full) and name.endswith(".log"):
                if min_mtime is not None and os.path.getmtime(full) < min_mtime:
                    continue
                files.append(full)
        files.sort(key=lambda p: os.path.getmtime(p))
        return files

    @staticmethod
    def _extract_source(text: str) -> tuple[str, str]:
        """从日志文本提取来源，与内存缓冲保持一致（共用归一化逻辑）."""
        return extract_source(text)

    @classmethod
    def _parse_human_line(cls, line: str) -> dict[str, Any] | None:
        """解析 loguru 人类可读格式行."""
        match = _HUMAN_LINE_PATTERN.match(line)
        if not match:
            return None
        timestamp, level, message = match.group(1), match.group(2).upper(), match.group(3)
        source, text = cls._extract_source(message)
        return {"time": timestamp[:19], "level": level, "source": source, "text": text}

    @classmethod
    def _parse_json_line(cls, line: str) -> dict[str, Any] | None:
        """解析 LOG_FORMAT=json 的 JSON 行."""
        try:
            data = json.loads(line)
        except (ValueError, TypeError):
            return None
        message = data.get("message") or ""
        if not isinstance(message, str):
            return None
        source, text = cls._extract_source(message)
        timestamp = data.get("timestamp") or ""
        return {
            "time": timestamp[:19],
            "level": str(data.get("level") or "").upper(),
            "source": source,
            "text": text,
        }

    def _iter_file_entries(self, filepath: str, keyword: str | None = None) -> Iterator[dict[str, Any]]:
        """逐行解析单个日志文件；支持人类可读与 JSON 两种格式，保留多行续行.

        带关键字时先做廉价预筛：新条目行不含关键字则跳过整行解析，
        仅继续追加已命中条目的多行续行，避免全量正则解析拖慢检索（Agent/日志页大时间窗查询）。
        """
        fmt: str | None = None
        last_entry: dict[str, Any] | None = None
        kw = (keyword or "").strip().lower()
        with open(filepath, encoding="utf-8", errors="ignore") as f:
            for raw in f:
                line = raw.rstrip("\n")
                if not line.strip():
                    continue
                if fmt is None:
                    fmt = "json" if line.lstrip().startswith("{") else "human"
                if kw:
                    line_lower = line.lower()
                    if fmt == "json":
                        if kw not in line_lower:
                            last_entry = None
                            continue
                    elif _looks_like_human_header(line):
                        if kw not in line_lower:
                            last_entry = None
                            continue
                    elif last_entry is None:
                        continue
                if fmt == "json":
                    entry = self._parse_json_line(line)
                else:
                    entry = self._parse_human_line(line)
                if entry:
                    yield entry
                    last_entry = entry
                elif last_entry is not None and fmt == "human":
                    # 多行消息的续行（如异常堆栈），追加到上一条
                    last_entry["text"] += "\n" + line

    _MMAP_LIMIT = 512 * 1024 * 1024  # 超过该大小的单文件回退逐行解析，避免内存峰值

    def _build_prefilter_pattern(
        self, keyword: str | None, level: str | None, source: str | None
    ) -> re.Pattern[bytes] | None:
        """把关键词/级别/来源组合成单次字节正则（任一模组命中即候选行）."""
        parts: list[bytes] = []
        kw = (keyword or "").strip()
        if kw:
            parts.append(b"(?:" + re.escape(kw.encode("utf-8")) + b")")
        if level:
            lv = level.strip().upper()
            parts.append(b"\\|" + re.escape(lv.encode()) + b"\\s*\\|")
        if source:
            src = source.strip()
            src_bytes = re.escape(src.encode("utf-8"))
            parts.append(b"\\[" + src_bytes + b"\\]")
            parts.append(src_bytes)
        if not parts:
            return None
        return re.compile(b"|".join(parts), re.IGNORECASE)

    def _fast_entries(
        self,
        filepath: str,
        pattern: re.Pattern[bytes],
        hours: int | None,
        limit_hits: int = 200000,
    ) -> list[dict[str, Any]] | None:
        """mmap + 字节正则快速预筛并解析命中条目（含多行续行）.

        返回 None 表示该文件无法 mmap（超大或异常），由调用方回退逐行解析；
        返回 [] 表示确认无匹配。
        """
        try:
            if os.path.getsize(filepath) > self._MMAP_LIMIT:
                return None
        except OSError:
            return None
        entries: list[dict[str, Any]] = []
        seen_starts: set[int] = set()
        try:
            with open(filepath, "rb") as f:
                with mmap.mmap(f.fileno(), 0, access=mmap.ACCESS_READ) as mm:
                    # 检测文件格式：首个非空行以 { 开头视为 JSON
                    fmt: str = "json" if mm[:1] == b"{" else "human"
                    for match in pattern.finditer(mm):
                        line_start = mm.rfind(b"\n", 0, match.start()) + 1
                        if line_start in seen_starts:
                            continue
                        seen_starts.add(line_start)
                        line_end = mm.find(b"\n", match.start())
                        if line_end == -1:
                            line_end = len(mm)
                        raw_line = bytes(mm[line_start:line_end]).decode("utf-8", errors="ignore")
                        entry = self._parse_json_line(raw_line) if fmt == "json" else self._parse_human_line(raw_line)
                        if not entry:
                            continue
                        if fmt == "human":
                            # 保留命中条目后的多行续行（异常堆栈等），遇到新条目表头即停止
                            pos = line_end
                            for _ in range(500):
                                next_nl = mm.find(b"\n", pos + 1)
                                if next_nl == -1:
                                    break
                                segment = bytes(mm[pos + 1 : next_nl]).decode("utf-8", errors="ignore")
                                pos = next_nl
                                if not segment.strip():
                                    continue
                                if _looks_like_human_header(segment):
                                    break
                                entry["text"] += "\n" + segment
                        if self._within_window(entry, hours):
                            entries.append(entry)
                            if len(entries) >= limit_hits:
                                break
        except (OSError, ValueError, TypeError):
            return None
        return entries

    def _iter_entries(
        self,
        hours: int | None = None,
        keyword: str | None = None,
        level: str | None = None,
        source: str | None = None,
    ) -> Iterator[dict[str, Any]]:
        """遍历可用日志：优先磁盘文件，无文件时回退内存缓冲.

        hours 非空时仅返回最近 N 小时内的条目，并跳过修改时间更早的旧文件。
        关键词/级别/来源任一存在时优先 mmap 字节级快速预筛，命中条目（含续行）才解析；
        mmap 不可用或单文件超大时回退逐行解析。
        """
        min_mtime = None
        if hours and hours > 0:
            min_mtime = time.time() - hours * 3600
        files = self._list_log_files(min_mtime=min_mtime)
        if not files:
            for entry in log.LOG_BUFFER:
                if self._within_window(entry, hours):
                    yield dict(entry)
            return
        pattern = self._build_prefilter_pattern(keyword, level, source)
        for filepath in files:
            if pattern is not None:
                fast_entries = self._fast_entries(filepath, pattern, hours)
                if fast_entries is not None:
                    yield from fast_entries
                    continue
            for entry in self._iter_file_entries(filepath, keyword=(keyword or "").strip() or None):
                if self._within_window(entry, hours):
                    yield entry

    @staticmethod
    def _within_window(entry: dict[str, Any], hours: int | None) -> bool:
        """判断日志条目是否在最近 N 小时内（hours 为空/非正数时不过滤）."""
        if not hours or hours <= 0:
            return True
        raw = entry.get("time") or ""
        if len(raw) < 19:
            return True
        try:
            ts = datetime.strptime(raw[:19], "%Y-%m-%d %H:%M:%S")
        except ValueError:
            return True
        return datetime.now() - ts <= timedelta(hours=hours)

    @staticmethod
    def _match(entry: dict[str, Any], keyword: str | None, level: str | None, source: str | None) -> bool:
        if level and entry.get("level") != level.upper():
            return False
        if source and entry.get("source") != source:
            return False
        if keyword:
            kw = keyword.strip().lower()
            if not kw:
                return True
            haystack = "{} {} {}".format(
                entry.get("text") or "",
                entry.get("source") or "",
                entry.get("time") or "",
            ).lower()
            if kw not in haystack:
                return False
        return True

    def search(
        self,
        keyword: str | None = None,
        level: str | None = None,
        source: str | None = None,
        page: int = 1,
        page_size: int = 1000,
        hours: int | None = DEFAULT_LOG_WINDOW_HOURS,
    ) -> dict[str, Any]:
        """全文搜索日志（默认最近 DEFAULT_LOG_WINDOW_HOURS 小时），返回分页结果."""
        page = max(1, int(page or 1))
        page_size = max(1, min(int(page_size or 1000), 10000))
        start = (page - 1) * page_size
        end = start + page_size
        items: list[dict[str, Any]] = []
        total = 0
        truncated = False
        for entry in self._iter_entries(hours=hours, keyword=keyword, level=level, source=source):
            if not self._match(entry, keyword, level, source):
                continue
            if start <= total < end:
                items.append(entry)
            total += 1
            if total >= MAX_MATCHES:
                truncated = True
                break
        return {
            "items": items,
            "total": total,
            "page": page,
            "page_size": page_size,
            "truncated": truncated,
        }

    def export_text(
        self,
        keyword: str | None = None,
        level: str | None = None,
        source: str | None = None,
        hours: int | None = DEFAULT_LOG_WINDOW_HOURS,
    ) -> str:
        """导出匹配日志为文本（默认仅最近 DEFAULT_LOG_WINDOW_HOURS 小时）."""
        lines: list[str] = []
        for entry in self._iter_entries(hours=hours, keyword=keyword, level=level, source=source):
            if not self._match(entry, keyword, level, source):
                continue
            lines.append(
                "[{}] [{}] [{}] {}".format(
                    entry.get("time") or "",
                    entry.get("level") or "",
                    entry.get("source") or "",
                    entry.get("text") or "",
                )
            )
        return "\n".join(lines) + ("\n" if lines else "")

    def list_sources(self, hours: int | None = DEFAULT_LOG_WINDOW_HOURS) -> list[str]:
        """返回日志中出现过的全部来源（去重排序，默认仅统计最近 DEFAULT_LOG_WINDOW_HOURS 小时）."""
        sources: set[str] = set()
        for entry in self._iter_entries(hours=hours):
            src = entry.get("source")
            if src:
                sources.add(src)
        return sorted(sources, key=lambda s: s.lower())
