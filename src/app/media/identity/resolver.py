"""
身份解析器（ADR-014 P2）

统一识别决策流：直通快路径 → 别名索引 → 版本因子评分 → 外部解析回写。
与 BatchIdentifier 的集成契约：返回可直接写缓存的 ResolveResult（status + media_info）。
"""

import re
from dataclasses import dataclass, field

import log
from app.domain.enums import IdentifyStatus
from app.domain.mediatypes import MediaType
from app.media.identity.builder import get_identity_builder
from app.media.identity.graph import get_edition_graph
from app.media.identity.index import get_alias_index
from app.media.identity.models import (
    ALIAS_FAN,
    ALIAS_OFFICIAL,
    ALIAS_ROMANIZATION,
    ALIAS_TRANSLATION,
    EDITION_MARKERS,
    Alias,
    AliasEntry,
    Work,
    normalize_text,
)
from app.media.models import MediaInfo

# 版本/子系列标记词（EDITION_MARKERS 单一来源）+ 拉丁词组 + 第X季模式
_EDITION_WORDS_RE = re.compile(
    r"(?i)("
    + r"|".join(re.escape(m) for m in sorted(EDITION_MARKERS, key=len, reverse=True))
    + r"|2nd\s*gig|stand\s+alone\s+complex|solid\s+state\s+society|第[一二三四五六七八九十\d]+季)"
)

_KIND_WEIGHT = {
    ALIAS_OFFICIAL: 1.0,
    ALIAS_TRANSLATION: 0.9,
    ALIAS_ROMANIZATION: 0.85,
    ALIAS_FAN: 0.5,
}
_HIT_SCORE = 0.5
_HIT_MARGIN = 1.3
# 索引命中置信度低于该值告警（canary：观察学成别名/边缘评分的可靠性）
_LOW_CONFIDENCE_WARN = 0.65


@dataclass
class ResolveResult:
    status: IdentifyStatus
    media_info: MediaInfo | None = None
    confidence: float = 0.0
    evidence: list[str] = field(default_factory=list)
    reason: str = ""


def extract_edition_markers(*texts: str) -> list[str]:
    """从标题/名称中抽取版本标记（SAC_2045/ARISE/剧场版/第X季...）"""
    markers: list[str] = []
    for text in texts:
        if not text:
            continue
        for m in _EDITION_WORDS_RE.finditer(text):
            token = re.sub(r"\s+", " ", m.group(1)).strip()
            if token and token not in markers:
                markers.append(token)
    return markers


class IdentityResolver:
    """统一身份解析：替代分散在 BatchIdentifier/identify_groups 中的启发式"""

    def __init__(self, media_service, index=None, graph=None, builder=None):
        self.media = media_service
        self.index = index or get_alias_index()
        self.graph = graph or get_edition_graph()
        self.builder = builder or get_identity_builder()
        self._target_names_cache: dict[int, list[str]] = {}

    # ---------- 主入口 ----------

    def resolve(self, group: dict, match_media: MediaInfo | None = None) -> ResolveResult:
        """完整解析：本地决策 + 外部解析（单组场景）"""
        result = self.resolve_local(group, match_media)
        if result is not None:
            return result
        return self._external_resolve(group, match_media)

    def resolve_local(self, group: dict, match_media: MediaInfo | None = None) -> ResolveResult | None:
        """
        本地决策（零外部调用）：直通快路径 → 别名索引 → 评分。
        本地可决返回 ResolveResult；需要外部解析返回 None。
        """
        names = group.get("names") or []
        markers = extract_edition_markers(group.get("title") or "", *names)

        # 守卫：年份/类型与目标冲突 → 本地排除（与旧 _guards_pass 语义一致）
        if match_media and not self._guards_pass(group, match_media):
            return ResolveResult(
                IdentifyStatus.NOT_FOUND,
                self._build_media_info(group),
                evidence=["reject:年份/类型与目标冲突"],
                reason="guard_conflict",
            )

        target_names = self._target_names(match_media)

        # 0. 直通快路径（目标已知）
        if match_media and target_names and names:
            matched = [self._strict(n, target_names) for n in names]
            if all(matched):
                tmdb_id = int(match_media.tmdb_id) if match_media.tmdb_id else 0
                info = self._build_media_info(group, tmdb_id=tmdb_id, from_media=match_media)
                return ResolveResult(
                    IdentifyStatus.HIT,
                    info,
                    confidence=1.0,
                    evidence=["direct:全名命中目标别名集"],
                    reason="direct_pass",
                )
            if not any(matched):
                return ResolveResult(
                    IdentifyStatus.NOT_FOUND,
                    self._build_media_info(group),
                    evidence=["reject:名称与目标零重叠"],
                    reason="zero_overlap",
                )

        # 1-2. 别名索引查询
        name_hits = [(n, self.index.lookup(n)) for n in names]
        name_hits = [(n, entries) for n, entries in name_hits if entries]

        # 3-4. 评分
        if name_hits:
            scored = self._score(name_hits, group, markers)
            if scored and self._passes(scored):
                score, work, ev_names = scored[0]
                tmdb_id = work.work_id if work.source == "tmdb" else 0
                info = self._build_media_info(group, work=work, tmdb_id=tmdb_id)
                # fan 证据名记命中（达阈值升格 translation）
                for n in ev_names:
                    self.index.record_hit(n, work.source, work.work_id)
                if score < _LOW_CONFIDENCE_WARN:
                    log.warn(
                        f"[IdentityResolver]低置信索引命中: {group.get('title', '')[:50]} "
                        f"-> {work.source}/{work.work_id} score={score:.2f} aliases={ev_names} markers={markers}"
                    )
                return ResolveResult(
                    IdentifyStatus.HIT,
                    info,
                    confidence=min(score, 1.0),
                    evidence=[f"alias:{n}" for n in ev_names] + [f"edition:{m}" for m in markers],
                    reason=f"index_hit:{work.source}/{work.work_id}",
                )
            if scored:
                log.debug(f"[IdentityResolver]评分未过阈: {[(round(s, 2), w.work_id) for s, w, _ in scored[:3]]}")
        return None

    # ---------- 外部解析 ----------

    def resolve_external_batch(self, groups: list[dict], match_media: MediaInfo | None = None) -> dict:
        """
        批量外部解析（并发，一次 identify_groups 调用）。
        返回 {cache_key: ResolveResult}，含共识后验证与 fan 学成回写。
        """
        results: dict = {}
        if not groups:
            return results
        # 每组名称上限 3 个（cn 优先排序），避免垃圾名逐个烧降级链
        capped = []
        for g in groups:
            names = g.get("names") or []
            if len(names) > 3:
                g = {**g, "names": names[:3]}
            capped.append(g)
        try:
            status_map = self.media.identify_groups(capped)
        except Exception as e:
            log.error(f"[IdentityResolver]批量外部解析出错: {e}")
            for g in groups:
                results[g["_cache_key"]] = ResolveResult(IdentifyStatus.ERROR, self._build_media_info(g), reason=str(e))
            return results

        check_names = self._target_names(match_media) if match_media else []
        for g in groups:
            key = g["_cache_key"]
            status, info = status_map.get(key, (IdentifyStatus.ERROR, None))
            if info is None:
                results[key] = ResolveResult(IdentifyStatus.ERROR, None, reason="external_error")
                continue
            if status == IdentifyStatus.HIT and info.tmdb_id:
                # 共识后验证：命中目标但组内有未解析名称（区分信息）→ 排除
                if match_media and getattr(match_media, "tmdb_id", None) == info.tmdb_id:
                    unresolved = [n for n in g.get("names") or [] if not self._strict(n, check_names)]
                    if unresolved:
                        results[key] = ResolveResult(
                            IdentifyStatus.NOT_FOUND,
                            self._build_media_info(g),
                            evidence=[f"reject:命中目标但存在区分信息 {unresolved}"],
                            reason="distinguishing_names",
                        )
                        continue
                # 学成回写：fan 别名（仅作证据，不单独定身份）+ 最小 Work 元数据
                self._learn_work(info)
                for n in g.get("names") or []:
                    self.index.add_alias(n, AliasEntry("tmdb", info.tmdb_id, kind=ALIAS_FAN))
                results[key] = ResolveResult(
                    status, info, confidence=0.7, evidence=["external:identify_groups"], reason="external_hit"
                )
            else:
                results[key] = ResolveResult(
                    status, info, evidence=["external:未命中"], reason=f"external_{status.value}"
                )
        return results

    def _external_resolve(self, group: dict, match_media: MediaInfo | None) -> ResolveResult:
        try:
            status_map = self.media.identify_groups([group])
        except Exception as e:
            log.error(f"[IdentityResolver]外部解析出错: {e}")
            return ResolveResult(IdentifyStatus.ERROR, self._build_media_info(group), reason=str(e))
        status, info = status_map.get(group["_cache_key"], (IdentifyStatus.ERROR, None))
        if info is None:
            return ResolveResult(IdentifyStatus.ERROR, None, reason="external_error")
        if status == IdentifyStatus.HIT and info.tmdb_id:
            # 共识后验证：命中目标但组内有未解析名称（区分信息）→ 排除
            if match_media and getattr(match_media, "tmdb_id", None) == info.tmdb_id:
                check_names = self._target_names(match_media)
                unresolved = [n for n in group.get("names") or [] if not self._strict(n, check_names)]
                if unresolved:
                    return ResolveResult(
                        IdentifyStatus.NOT_FOUND,
                        self._build_media_info(group),
                        evidence=[f"reject:命中目标但存在区分信息 {unresolved}"],
                        reason="distinguishing_names",
                    )
            # 学成回写：fan 别名（仅作证据，不单独定身份）+ 最小 Work 元数据
            self._learn_work(info)
            for n in group.get("names") or []:
                self.index.add_alias(n, AliasEntry("tmdb", info.tmdb_id, kind=ALIAS_FAN))
            return ResolveResult(
                status, info, confidence=0.7, evidence=["external:identify_groups"], reason="external_hit"
            )
        return ResolveResult(status, info, evidence=["external:未命中"], reason=f"external_{status.value}")

    # ---------- 评分 ----------

    def _score(self, name_hits, group, markers) -> list[tuple[float, Work, list[str]]]:
        by_work: dict[tuple[str, int], list[tuple[str, AliasEntry]]] = {}
        for name, entries in name_hits:
            for e in entries:
                by_work.setdefault((e.source, e.work_id), []).append((name, e))

        scored: list[tuple[float, Work, list[str]]] = []
        for (source, work_id), hits in by_work.items():
            work = self._ensure_work(source, work_id, group)
            if not work:
                continue
            base = sum(self._name_conf(n, group) * _KIND_WEIGHT.get(e.kind, 0.6) for n, e in hits)
            score = base * self._year_factor(group.get("year"), work.year) * self._edition_factor(markers, work)
            scored.append((score, work, [n for n, _ in hits]))
        scored.sort(key=lambda x: -x[0])
        return scored

    @staticmethod
    def _passes(scored) -> bool:
        best = scored[0][0]
        if best < _HIT_SCORE:
            return False
        return len(scored) == 1 or best >= scored[1][0] * _HIT_MARGIN

    @staticmethod
    def _name_conf(name: str, group: dict) -> float:
        if name and name == group.get("cn_name"):
            return 0.9
        return 0.75

    @staticmethod
    def _year_factor(group_year, work_year) -> float:
        gy = str(group_year or "")[:4]
        wy = str(work_year or "")[:4]
        if gy and wy:
            return 1.0 if gy == wy else 0.3
        return 0.7

    @staticmethod
    def _edition_factor(markers: list[str], work: Work) -> float:
        """版本因子：无标记 1.0；按标记命中率 0.4-1.2 线性（全中加成）"""
        if not markers:
            return 1.0
        names_norm = [normalize_text(n).replace(" ", "") for n in work.all_name_strings()]
        hits = sum(1 for m in markers if any(normalize_text(m).replace(" ", "") in n for n in names_norm))
        return 0.4 + 0.8 * (hits / len(markers))

    # ---------- 工具 ----------

    def _ensure_work(self, source: str, work_id: int, group: dict) -> Work | None:
        """读取已缓存的 Work 元数据（不触发 TMDB API；未缓存跳过，交外部解析兜底）"""
        if source == "tmdb":
            return self.index.get_work("tmdb", work_id)
        if source == "bgm":
            return self.index.get_work("bgm", work_id)
        return None

    def _learn_work(self, info) -> None:
        """外部解析命中后回写最小 Work 元数据（完成冷→热闭环，避免同作品重复外部解析）"""
        if not info or not getattr(info, "tmdb_id", None):
            return
        tmdb_id = int(info.tmdb_id)
        if self.index.get_work("tmdb", tmdb_id):
            return
        mtype = getattr(info, "type", None)
        year_str = str(getattr(info, "year", "") or "")[:4]
        work = Work(
            source="tmdb",
            work_id=tmdb_id,
            media_type="anime" if mtype == MediaType.ANIME else (mtype.value if mtype else "tv"),
            year=int(year_str) if year_str.isdigit() else None,
            official_titles=[n for n in (getattr(info, "title", None), getattr(info, "original_title", None)) if n],
            aliases=[
                Alias(text=n, kind=ALIAS_FAN, source="learned")
                for n in (getattr(info, "cn_name", None), getattr(info, "en_name", None))
                if n
            ],
        )
        self.index.put_work(work)
        log.info(f"[IdentityResolver]外部解析学成 Work: tmdb/{tmdb_id} {work.official_titles}")

    @staticmethod
    def _strict(name: str, target_names: list[str]) -> bool:
        n = normalize_text(name)
        if not n:
            return False
        return any(n == normalize_text(t) for t in target_names if t)

    @staticmethod
    def _guards_pass(group: dict, match_media: MediaInfo) -> bool:
        """类型一致 + 年份一致（或种子无年份）。TV 和 ANIME 互认兼容。"""
        m_type = getattr(match_media, "type", None)
        g_type = group.get("type")
        if g_type and m_type and g_type != m_type:
            if not ({g_type, m_type} <= {MediaType.TV, MediaType.ANIME}):
                return False
        g_year = str(group.get("year") or "")
        m_year = str(getattr(match_media, "year", "") or "")
        return not (g_year and m_year and g_year != m_year)

    def _target_names(self, match_media: MediaInfo | None) -> list[str]:
        if not match_media or not getattr(match_media, "tmdb_id", None):
            return []
        tmdb_id = int(match_media.tmdb_id)
        cache = getattr(self, "_target_names_cache", None)
        if cache is None:
            cache = self._target_names_cache = {}
        if tmdb_id in cache:
            return cache[tmdb_id]
        names = [
            n
            for n in (
                getattr(match_media, "cn_name", None),
                getattr(match_media, "en_name", None),
                getattr(match_media, "title", None),
                getattr(match_media, "original_title", None),
            )
            if n
        ]
        try:
            extra = self.media.get_all_names(match_media.tmdb_id, match_media.type or MediaType.TV) or []
            for n in extra:
                if n and n not in names:
                    names.append(n)
        except Exception as e:
            log.warn(f"[IdentityResolver]获取目标别名失败: {e}")
        self._target_names_cache[tmdb_id] = names
        return names

    def _build_media_info(
        self,
        group: dict,
        work: Work | None = None,
        tmdb_id: int = 0,
        from_media: MediaInfo | None = None,
    ) -> MediaInfo:
        seasons = group.get("seasons") or []
        episodes = group.get("episodes") or []
        info = MediaInfo(
            cn_name=group.get("cn_name"),
            en_name=group.get("en_name"),
            year=group.get("year"),
            begin_season=seasons[0] if seasons else None,
            end_season=seasons[-1] if len(seasons) > 1 else None,
            begin_episode=episodes[0] if episodes else None,
            end_episode=episodes[-1] if len(episodes) > 1 else None,
            type=group.get("type"),
        )
        info.site = group.get("site")
        info.enclosure = group.get("enclosure")
        info.size = group.get("size", 0)
        info.seeders = group.get("seeders", 0)
        info.org_string = group.get("title", "")

        if from_media is not None:
            info.tmdb_id = from_media.tmdb_id
            info.year = info.year or getattr(from_media, "year", None)
            info.type = info.type or getattr(from_media, "type", None)
            info.title = getattr(from_media, "title", None)
            info.original_title = getattr(from_media, "original_title", None)
            info.tmdb_info = getattr(from_media, "tmdb_info", None) or {}
            info.poster_path = getattr(from_media, "poster_path", None)
            info.backdrop_path = getattr(from_media, "backdrop_path", None)
        elif work is not None:
            info.tmdb_id = tmdb_id
            if work.official_titles:
                info.title = work.official_titles[0]
                if len(work.official_titles) > 1:
                    info.original_title = work.official_titles[1]
            info.year = info.year or (str(work.year) if work.year else None)
            if tmdb_id:
                info.tmdb_info = {"id": tmdb_id, "title": info.title, "year": info.year}
        return info


_resolver: IdentityResolver | None = None


def get_identity_resolver(media_service=None) -> IdentityResolver:
    global _resolver
    if _resolver is None:
        if media_service is None:
            raise ValueError("首次获取 IdentityResolver 必须提供 media_service")
        _resolver = IdentityResolver(media_service)
    return _resolver


def set_identity_resolver(resolver: IdentityResolver | None) -> None:
    """DI 装配入口：注入 builder 显式构建的实例；None 复位（测试隔离）。"""
    global _resolver
    _resolver = resolver
