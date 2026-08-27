"""
别名索引（ADR-014 P1）

AliasIndex: 归一化别名 → 候选作品集合（tiered: 进程内 LRU + Redis）。
索引返回候选集，不定身份；集合 >1 时由识别层做年份/edition 消歧。
"""

import log
from app.infrastructure.cache_system import get_cache_manager
from app.media.identity.models import (
    FAN_PROMOTE_HITS,
    AliasEntry,
    Work,
    alias_key,
    edition_key,
    franchise_key,
    work_key,
)

_ALIAS_TTL = 7 * 24 * 3600
_WORK_TTL = 7 * 24 * 3600


class AliasIndex:
    """别名索引：查询 O(1)，热路径零网络"""

    def __init__(
        self,
        alias_adapter=None,
        work_adapter=None,
        graph_adapter=None,
    ):
        cm = get_cache_manager()
        self._alias_cache = alias_adapter or cm.get_or_create(
            "identity_alias", "tiered", memory_maxsize=2000, ttl=_ALIAS_TTL
        )
        self._work_cache = work_adapter or cm.get_or_create(
            "identity_work", "tiered", memory_maxsize=1000, ttl=_WORK_TTL
        )
        self._graph_cache = graph_adapter or cm.get_or_create(
            "identity_graph", "tiered", memory_maxsize=500, ttl=_WORK_TTL
        )

    # ---------- 别名查询 ----------

    def lookup(self, name: str) -> list[AliasEntry]:
        """查别名 → 候选作品集合（可能为空/多作品）"""
        if not name or not name.strip():
            return []
        data = self._alias_cache.get(alias_key(name))
        if not data:
            return []
        return [AliasEntry.from_dict(e) for e in data]

    def add_alias(self, name: str, entry: AliasEntry) -> None:
        """追加别名映射（去重）；fan 重复写入视为一次命中，达阈值升格 translation"""
        if not name or not name.strip() or not entry.work_id:
            return
        key = alias_key(name)
        data = self._alias_cache.get(key) or []
        ref = (entry.source, entry.work_id)
        for e in data:
            if (e.get("source"), e.get("work_id")) == ref:
                if e.get("kind") == "fan":
                    if entry.kind == "fan":
                        # fan 一致命中：累计次数，达阈值升格
                        e["hits"] = int(e.get("hits") or 1) + 1
                        if e["hits"] >= FAN_PROMOTE_HITS:
                            e["kind"] = "translation"
                            log.info(f"[IdentityIndex]fan 别名升格: {name} -> {ref} (hits={e['hits']})")
                    else:
                        e["kind"] = entry.kind
                        e["lang"] = entry.lang
                self._alias_cache.set(key, data, ttl=_ALIAS_TTL)
                return
        data.append({**entry.to_dict(), "hits": 1})
        self._alias_cache.set(key, data, ttl=_ALIAS_TTL)

    def record_hit(self, name: str, source: str, work_id: int) -> None:
        """记录一次 fan 别名成功命中（用于升格计数）"""
        if not name or not name.strip():
            return
        key = alias_key(name)
        data = self._alias_cache.get(key)
        if not data:
            return
        changed = False
        for e in data:
            if (e.get("source"), e.get("work_id")) == (source, work_id) and e.get("kind") == "fan":
                e["hits"] = int(e.get("hits") or 1) + 1
                if e["hits"] >= FAN_PROMOTE_HITS:
                    e["kind"] = "translation"
                    log.info(f"[IdentityIndex]fan 别名升格: {name} -> {(source, work_id)} (hits={e['hits']})")
                changed = True
        if changed:
            self._alias_cache.set(key, data, ttl=_ALIAS_TTL)

    def invalidate(self, name: str) -> None:
        """整条逐出（错配纠错路径）"""
        if not name or not name.strip():
            return
        self._alias_cache.delete(alias_key(name))

    def invalidate_mapping(self, name: str, source: str, work_id: int) -> bool:
        """按映射逐出：仅移除别名下的某个作品映射，保留其余"""
        if not name or not name.strip():
            return False
        key = alias_key(name)
        data = self._alias_cache.get(key)
        if not data:
            return False
        kept = [e for e in data if (e.get("source"), e.get("work_id")) != (source, work_id)]
        if len(kept) == len(data):
            return False
        if kept:
            self._alias_cache.set(key, kept, ttl=_ALIAS_TTL)
        else:
            self._alias_cache.delete(key)
        log.info(f"[IdentityIndex]映射逐出: {name} - {(source, work_id)}")
        return True

    # ---------- Work 存取 ----------

    def get_work(self, source: str, work_id: int) -> Work | None:
        data = self._work_cache.get(work_key(source, work_id))
        return Work.from_dict(data) if data else None

    def put_work(self, work: Work) -> None:
        """写入 Work 并把其全部名称灌入别名索引"""
        if not work.work_id:
            return
        self._work_cache.set(work_key(work.source, work.work_id), work.to_dict(), ttl=_WORK_TTL)
        for n in work.official_titles:
            self.add_alias(n, AliasEntry(work.source, work.work_id, kind="official"))
        for a in work.aliases:
            self.add_alias(a.text, AliasEntry(work.source, work.work_id, kind=a.kind, lang=a.lang))

    def get_work_names(self, source: str, work_id: int) -> list[str] | None:
        """兼容 get_all_names 语义：命中返回名称列表，未命中返回 None"""
        work = self.get_work(source, work_id)
        return work.all_name_strings() if work else None

    # ---------- EditionGraph / Franchise 存取 ----------

    def get_edges(self, source: str, work_id: int) -> list[dict]:
        return self._graph_cache.get(edition_key(source, work_id)) or []

    def put_edges(self, source: str, work_id: int, edges: list[dict]) -> None:
        self._graph_cache.set(edition_key(source, work_id), edges, ttl=_WORK_TTL)

    def get_franchise(self, key: str) -> dict | None:
        return self._graph_cache.get(franchise_key(key))

    def put_franchise(self, franchise: dict) -> None:
        self._graph_cache.set(franchise_key(franchise.get("key", "")), franchise, ttl=_WORK_TTL)


_index: AliasIndex | None = None


def get_alias_index() -> AliasIndex:
    global _index
    if _index is None:
        _index = AliasIndex()
        log.debug("[IdentityIndex]别名索引初始化完成")
    return _index


def set_alias_index(index: AliasIndex | None) -> None:
    """DI 装配入口：注入 builder 显式构建的实例；None 复位（测试隔离）。"""
    global _index
    _index = index
