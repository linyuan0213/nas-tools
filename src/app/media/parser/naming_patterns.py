"""
站点/字幕组命名模式库 — 规则引擎

规则存放于 config/naming_patterns.yaml（可用 NEXUS_NAMING_PATTERNS 覆盖路径），
支持 mtime 热重载；单条规则编译失败仅跳过并告警，不影响整体。
"""

import os
import re
import time
from dataclasses import dataclass, field
from pathlib import Path

import yaml

import log

_PATTERN_FIELDS = ("cn_name", "en_name", "season", "episode", "episode_end", "year")
_DEFAULT_PATH = Path(__file__).resolve().parents[4] / "config" / "naming_patterns.yaml"
_RELOAD_INTERVAL = 5.0


@dataclass
class NamingRule:
    name: str
    pattern: re.Pattern
    description: str = ""
    match: re.Pattern | None = field(default=None)


class NamingPatternLibrary:
    """有序规则匹配，先匹配先赢"""

    def __init__(self, path: str | Path | None = None):
        self._path = Path(path or os.environ.get("NEXUS_NAMING_PATTERNS") or _DEFAULT_PATH)
        self._rules: list[NamingRule] = []
        self._mtime = 0.0
        self._last_check = 0.0
        self.reload()

    @property
    def rules(self) -> list[NamingRule]:
        return list(self._rules)

    def reload(self) -> None:
        try:
            mtime = self._path.stat().st_mtime
        except OSError:
            if self._rules:
                log.warn(f"[NamingPattern]规则文件不可读: {self._path}")
            self._rules = []
            return
        self._mtime = mtime
        try:
            data = yaml.safe_load(self._path.read_text(encoding="utf-8")) or {}
        except Exception as e:
            log.error(f"[NamingPattern]规则文件解析失败: {self._path}, {e}")
            return
        rules = []
        for idx, entry in enumerate(data.get("rules") or []):
            rule = self._compile_rule(entry, idx)
            if rule:
                rules.append(rule)
        self._rules = rules
        log.debug(f"[NamingPattern]已加载 {len(rules)} 条命名规则: {self._path}")

    @staticmethod
    def _compile_rule(entry, idx: int) -> NamingRule | None:
        if not isinstance(entry, dict) or not entry.get("name") or not entry.get("pattern"):
            log.warn(f"[NamingPattern]第 {idx + 1} 条规则缺少 name/pattern，跳过")
            return None
        try:
            pattern = re.compile(entry["pattern"])
            match = re.compile(entry["match"]) if entry.get("match") else None
        except re.error as e:
            log.error(f"[NamingPattern]规则 '{entry['name']}' 正则编译失败: {e}，跳过")
            return None
        return NamingRule(
            name=str(entry["name"]),
            pattern=pattern,
            description=str(entry.get("description") or ""),
            match=match,
        )

    def _reload_if_stale(self) -> None:
        now = time.monotonic()
        if now - self._last_check < _RELOAD_INTERVAL:
            return
        self._last_check = now
        try:
            mtime = self._path.stat().st_mtime
        except OSError:
            return
        if mtime != self._mtime:
            self.reload()

    def apply(self, title: str) -> dict | None:
        """匹配标题，命中返回 {'rule': 规则名, ...提取字段}，未命中返回 None"""
        if not title:
            return None
        self._reload_if_stale()
        for rule in self._rules:
            if rule.match and not rule.match.search(title):
                continue
            m = rule.pattern.search(title)
            if not m:
                continue
            fields = {k: v.strip() for k, v in m.groupdict().items() if k in _PATTERN_FIELDS and v and v.strip()}
            if not fields:
                continue
            log.info(
                f"[NamingPattern]命中规则 '{rule.name}': {title[:60]} -> "
                f"cn={fields.get('cn_name')}, en={fields.get('en_name')}"
            )
            return {"rule": rule.name, **fields}
        return None


_library: NamingPatternLibrary | None = None


def get_naming_patterns() -> NamingPatternLibrary:
    global _library
    if _library is None:
        _library = NamingPatternLibrary()
    return _library


def apply_hit_to_info(info, hit: dict) -> None:
    """将模式命中的数字字段覆盖到 MediaInfo（季/集/年），仅覆盖规则提供的字段"""

    def _to_int(v):
        try:
            return int(v)
        except (TypeError, ValueError):
            return None

    if (s := _to_int(hit.get("season"))) is not None:
        info.begin_season = s
    if (e := _to_int(hit.get("episode"))) is not None:
        info.begin_episode = e
    if (ee := _to_int(hit.get("episode_end"))) is not None:
        info.end_episode = ee
    if hit.get("year") and not info.year:
        info.year = str(hit["year"])
