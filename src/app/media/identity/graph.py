"""
版本关系图（ADR-014 P2）

EditionGraph: franchise（虚拟节点）→ Work 的跨作品关系。
数据来源: Bangumi relations（/v0/subjects/{id}/subjects）+ 手工补充表。
识别层用它在同名系列内做版本下钻（franchise + edition_markers → 具体子版本）。
"""

import os
from pathlib import Path

import yaml

import log
from app.media.external.bangumi import Bangumi
from app.media.identity.index import AliasIndex, get_alias_index
from app.media.identity.models import EditionEdge, Franchise, normalize_text

_OVERRIDES_PATH = Path(__file__).resolve().parents[4] / "config" / "edition_overrides.yaml"

# Bangumi relation → 统一关系类型
_RELATION_MAP = {
    "续集": "sequel",
    "前传": "prequel",
    "衍生": "spinoff",
    "番外篇": "special",
    "主线故事": "main_story",
    "总集篇": "compilation",
    "重制": "remake",
    "不同版本": "alt_version",
}

# 建图 BFS 限制
_MAX_DEPTH = 2
_MAX_MEMBERS = 30


class EditionGraph:
    """系列版本关系图：按 franchise key 组织成员与边"""

    def __init__(self, index: AliasIndex | None = None, bangumi: Bangumi | None = None):
        self._index = index or get_alias_index()
        self._bangumi = bangumi or Bangumi()
        self._overrides_loaded = False

    def _ensure_overrides_loaded(self) -> None:
        """加载 config/edition_overrides.yaml 手工补边（Bangumi 缺失的关系）"""
        if self._overrides_loaded:
            return
        self._overrides_loaded = True
        path = Path(os.environ.get("NEXUS_EDITION_OVERRIDES") or _OVERRIDES_PATH)
        try:
            data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        except OSError:
            return
        except yaml.YAMLError as e:
            log.error(f"[EditionGraph]手工补充表解析失败: {path}, {e}")
            return
        for item in data.get("edition_overrides") or []:
            key = item.get("franchise")
            members = item.get("members") or []
            if not key or not members:
                continue
            franchise = Franchise(
                key=key,
                name=item.get("name") or key,
                members=[(m.get("source", "tmdb"), int(m.get("work_id", 0))) for m in members if m.get("work_id")],
            )
            self._index.put_franchise(franchise.to_dict())
            log.info(f"[EditionGraph]手工 franchise 已加载: {franchise.name} 成员 {len(franchise.members)}")

    # ---------- 建图 ----------

    @staticmethod
    def _franchise_key_of(name: str) -> str:
        return normalize_text(name).replace(" ", "").lower()

    def ensure_bgm_franchise(self, bid: int) -> str | None:
        """
        从一个 BGM subject 出发 BFS 拉取关系，建 franchise 图。
        返回 franchise key；无关系边时返回 None。
        """
        members: dict[int, dict] = {}
        edges: dict[int, list[EditionEdge]] = {}
        root = None
        queue: list[tuple[int, int]] = [(bid, 0)]
        seen: set[int] = set()

        while queue and len(members) < _MAX_MEMBERS:
            current, depth = queue.pop(0)
            if current in seen or depth > _MAX_DEPTH:
                continue
            seen.add(current)
            try:
                relations = self._bangumi.relations(current)
            except Exception as e:
                log.debug(f"[EditionGraph]BGM关系拉取失败: {current}, {e}")
                continue
            if current == bid and not relations:
                return None
            for rel in relations:
                if rel.get("type") != 2:  # 只要动画条目
                    continue
                rid = rel.get("id")
                if not rid:
                    continue
                if root is None and current == bid:
                    root = {"id": current}
                members.setdefault(rid, {"id": rid, "name": rel.get("name") or "", "name_cn": rel.get("name_cn") or ""})
                edges.setdefault(current, []).append(
                    EditionEdge(
                        target_source="bgm",
                        target_id=rid,
                        relation=_RELATION_MAP.get(rel.get("relation") or "", "other"),
                        target_title=rel.get("name_cn") or rel.get("name") or "",
                    )
                )
                if depth + 1 <= _MAX_DEPTH and rid not in seen:
                    queue.append((rid, depth + 1))

        if not members:
            return None

        # franchise key 用根条目名（name_cn 优先）
        root_name = ""
        try:
            detail = self._bangumi.detail(bid) or {}
            root_name = detail.get("name_cn") or detail.get("name") or ""
        except Exception as e:
            log.debug(f"[EditionGraph]根条目详情获取失败: {bid}, {e}")
        fkey = self._franchise_key_of(root_name or f"bgm:{bid}")
        franchise = Franchise(
            key=fkey,
            name=root_name or f"bgm:{bid}",
            members=[("bgm", m["id"]) for m in members.values()],
        )
        self._index.put_franchise(franchise.to_dict())
        for src_id, edge_list in edges.items():
            self._index.put_edges("bgm", src_id, [e.to_dict() for e in edge_list])
        log.info(f"[EditionGraph]franchise 已建图: {franchise.name} 成员 {len(members)}")
        return fkey

    # ---------- 查询 ----------

    def get_franchise(self, key: str) -> Franchise | None:
        self._ensure_overrides_loaded()
        data = self._index.get_franchise(key)
        return Franchise.from_dict(data) if data else None

    def get_edges(self, source: str, work_id: int) -> list[EditionEdge]:
        return [EditionEdge.from_dict(e) for e in self._index.get_edges(source, work_id)]

    # ---------- 版本下钻 ----------

    def find_edition(self, franchise_key: str, edition_markers: list[str]) -> tuple[str, int] | None:
        """
        在 franchise 内按 edition_markers 找最匹配的子版本。
        返回 (source, work_id)；无匹配返回 None。
        """
        franchise = self.get_franchise(franchise_key)
        if not franchise or not edition_markers:
            return None
        markers_norm = [normalize_text(m).replace(" ", "") for m in edition_markers if m]
        if not markers_norm:
            return None

        best: tuple[str, int] | None = None
        best_score = 0
        for source, work_id in franchise.members:
            work = self._index.get_work(source, work_id)
            if not work:
                continue
            names_norm = {normalize_text(n).replace(" ", "") for n in work.all_name_strings()}
            score = 0
            for marker in markers_norm:
                if any(marker in n for n in names_norm):
                    score += len(marker)
            if score > best_score:
                best_score = score
                best = (source, work_id)
        if best:
            log.debug(f"[EditionGraph]版本下钻: {franchise.name} + {edition_markers} -> {best}")
        return best


_graph: EditionGraph | None = None


def get_edition_graph() -> EditionGraph:
    global _graph
    if _graph is None:
        _graph = EditionGraph()
    return _graph


def set_edition_graph(graph: EditionGraph | None) -> None:
    """DI 装配入口：注入 builder 显式构建的实例；None 复位（测试隔离）。"""
    global _graph
    _graph = graph
