import re

import log
from app.core.settings import settings
from app.domain.enums import IdentifyStatus, ProgressKey
from app.domain.mediatypes import MediaType
from app.domain.validators.media_title import is_valid_media_title
from app.infrastructure.cache_system import get_cache_manager
from app.infrastructure.progress import ProgressTracker
from app.media.identity.resolver import get_identity_resolver
from app.media.models import MediaInfo
from app.utils import StringUtils

# 未识别结果缓存 TTL（秒），供 match_filter 区分「未匹配」与「识别出错」
_NOT_FOUND_TTL = 600

# 名称尾巴上的质量/平台词（"Solid State Society（2006）Web Dl" 这类解析残留）
_QUALITY_TAIL_RE = re.compile(
    r"(?i)\s*\b(?:web[- ]?(?:dl|rip)|bd(?:rip)?|blu[-]?ray|hdtv|uhdtv|\d{3,4}p|hevc|avc|x\.?26[45]|h\.?26[45]"
    r"|aac\d*|ac3|eac3|flac|ddp?\d*(?:\.\d)?|opus|dts|mp4|mkv|10bit|8bit|hdr\d*|dv|sdr"
    r"|baha|cr|abema|nf|hulu|dsnp|friday|linetv|catchplay|kktv)\b.*$"
)
# 名称首尾重复的词组（如 "Sac 2045 X Sac 2045" 是解析残留，去重一端）
_DUP_ENDS_RE = re.compile(r"^(?P<dup>[A-Z][A-Za-z0-9\-]*(?:\s+\d+)?)\s+(?P<mid>.+?)\s+(?P=dup)$", re.IGNORECASE)


def _clean_name(name: str) -> str:
    """剥掉名称尾巴的质量/平台残留词，去重首尾重复词组"""
    m = _DUP_ENDS_RE.match(name.strip())
    if m:
        name = f"{m.group('dup')} {m.group('mid')}"
    cleaned = _QUALITY_TAIL_RE.sub("", name).strip(" -.:/：")
    return cleaned or name


def _strict_match(name: str, target_names: list) -> bool:
    """全名共识用的严格匹配：归一化后精确相等。

    不用 compare_tmdb_names 的子串宽松规则（"GHOST IN THE SHELL" 是
    "SAC 2045 GHOST IN THE SHELL" 子串即判匹配），否则会放行同名不同作。
    """
    n = StringUtils.handler_special_chars(str(name)).upper().strip()
    if not n:
        return False
    for t in target_names or []:
        if t and n == StringUtils.handler_special_chars(str(t)).upper().strip():
            return True
    return False


def _is_latin_name(name: str) -> bool:
    """名称是否含拉丁字母（英文名）。

    拉丁名精确匹配到目标即可信（短中文名/前缀只是不完整，不是冲突；
    而同名不同作的拉丁名通常带 SAC_2045 等后缀，不会与基础名严格相等）。
    """
    return bool(re.search(r"[A-Za-z]", str(name or "")))


class BatchIdentifier:
    """
    批量媒体识别器

    职责：按缓存键分组聚合名称候选（中文优先），先走 match_media 先验直通，
    其余交 MediaService.identify_groups 批量识别，按状态写缓存。
    """

    def __init__(
        self,
        media_service,
        progress: ProgressTracker | None = None,
    ):
        self.media = media_service
        self.progress = progress or ProgressTracker()
        self._media_ident_cache = get_cache_manager().get_or_create("media_ident", "memory", maxsize=2000, ttl=3600)

    @staticmethod
    def build_cache_key(meta_info, fallback_title=None):
        """构建与 identify 阶段一致的缓存 key (v2)"""
        name = meta_info.get_name() or fallback_title
        if not name:
            return None
        # 名称归一化：剥离标点差异（"Jaadugar: A Witch" 与 "Jaadugar A Witch" 同键）
        name = StringUtils.handler_special_chars(name).strip()
        season_ep = ""
        if meta_info.get_season_list():
            season_ep += f"_S{'-'.join(str(s) for s in meta_info.get_season_list())}"
        if meta_info.get_episode_list():
            season_ep += f"_E{'-'.join(str(e) for e in meta_info.get_episode_list())}"
        key = f"v2_{name}{season_ep}"
        # 英文名哈希区分同名不同作（如 攻壳机动队 SAC_2045 vs 攻壳机动队 2026）
        # 不用截断前缀——"Ghost in the Shell AKA...Stand Alone Complex" 截断后与
        # "Ghost in the Shell" 相同，导致跨作品共享缓存键
        en = getattr(meta_info, "en_name", None)
        if en:
            normalized = StringUtils.handler_special_chars(en).upper().replace(" ", "")
            key += f"_{StringUtils.md5_hash(normalized)[:8]}"
        return key

    def identify(self, candidates, progress_key=ProgressKey.Search, match_media: MediaInfo | None = None):
        """
        对 candidates 中 skip_tmdb=False 的条目分组识别。

        :param match_media: 搜索/订阅目标媒体，提供时启用先验直通
        """
        if not candidates:
            return

        groups: dict[str, dict] = {}
        order: list[str] = []
        for cand in candidates:
            if cand.skip_tmdb:
                continue
            cache_key = self.build_cache_key(cand.meta_info, cand.item.get("title"))
            if not cache_key:
                continue
            if self._media_ident_cache.get(cache_key) is not None:
                continue
            mi = cand.meta_info
            g = groups.get(cache_key)
            if g is None:
                g = {
                    "_cache_key": cache_key,
                    "names": [],
                    "cn_name": getattr(mi, "cn_name", None),
                    "en_name": getattr(mi, "en_name", None),
                    "year": getattr(mi, "year", None),
                    "type": getattr(mi, "type", None),
                    "seasons": mi.get_season_list() or [],
                    "episodes": mi.get_episode_list() or [],
                    "title": cand.item.get("title") or cache_key,
                    "site": cand.item.get("site"),
                    "enclosure": cand.item.get("enclosure"),
                    "size": cand.item.get("size"),
                    "seeders": cand.item.get("seeders"),
                }
                groups[cache_key] = g
                order.append(cache_key)
            # 名称候选聚合：清洗 + 质量过滤 + 去重；回填组代表的中/英文名
            cn = getattr(mi, "cn_name", None)
            en = getattr(mi, "en_name", None)
            if cn and not g["cn_name"]:
                g["cn_name"] = cn
            if en and not g["en_name"]:
                g["en_name"] = en
            for name in (cn, en):
                if not name:
                    continue
                name = _clean_name(name)
                if name and is_valid_media_title(name) and name not in g["names"]:
                    g["names"].append(name)

        if not groups:
            return

        # 中文名优先尝试（稳定排序，保持同类内插入序）
        for g in groups.values():
            g["names"].sort(key=lambda n: 0 if StringUtils.is_chinese(n) else 1)

        log.info(f"[BatchIdentifier]批量识别 {len(groups)} 组不重复结果 ...")

        # 身份解析器（ADR-014 P2）灰度开关：开启后统一由 IdentityResolver 决策
        if settings.get("laboratory").get("identity_resolver"):
            self._identify_via_resolver(order, groups, match_media, progress_key)
            return

        # 基础名：零网络成本，始终可用
        base_target_names = (
            [
                n
                for n in (
                    getattr(match_media, "cn_name", None),
                    getattr(match_media, "en_name", None),
                    getattr(match_media, "title", None),
                    getattr(match_media, "original_title", None),
                )
                if n
            ]
            if match_media
            else []
        )
        target_names = list(base_target_names)
        enrichment_ok = False
        # 别名扩充：一次 TMDB API，有缓存；失败不影响搜索可用性
        if match_media and target_names:
            try:
                extra = self.media.get_all_names(match_media.tmdb_id, match_media.type or MediaType.TV) or []
            except Exception as e:
                log.warn(f"[BatchIdentifier]获取目标别名失败，直通降级为保守模式: {e}")
                extra = []
            for n in extra:
                if n and n not in target_names:
                    target_names.append(n)
                    enrichment_ok = True
            if enrichment_ok:
                log.debug(f"[BatchIdentifier]目标别名扩充 {len(target_names) - len(base_target_names)} 条")
            else:
                log.warn("[BatchIdentifier]目标别名扩充失败或为空，直通降级为保守模式")

        pending: list[dict] = []
        for key in order:
            g = groups[key]
            if not base_target_names or match_media is None:
                pending.append(g)
                continue
            if not self._guards_pass(g, match_media):
                self._media_ident_cache.set(key, self._build_group_media_info(g), ttl=_NOT_FOUND_TTL)
                log.info(f"[BatchIdentifier]{g['title'][:50]} 年份/类型冲突，本地排除")
                continue
            if not g["names"]:
                pending.append(g)
                continue
            base_matched = [_strict_match(n, base_target_names) for n in g["names"]]
            enriched_matched = [_strict_match(n, target_names) for n in g["names"]] if enrichment_ok else base_matched
            if enrichment_ok:
                # 拉丁名严格匹配到目标即可直通（短中文名/前缀只是不完整，不是冲突）
                latin_matched = [m for n, m in zip(g["names"], enriched_matched) if _is_latin_name(n)]
                if all(enriched_matched) or any(latin_matched):
                    info = self._build_direct_media_info(g, match_media)
                    self._media_ident_cache.set(key, info)
                    log.info(f"[BatchIdentifier]{g['title'][:50]} 先验直通")
                elif not any(enriched_matched):
                    self._media_ident_cache.set(key, self._build_group_media_info(g), ttl=_NOT_FOUND_TTL)
                    log.info(f"[BatchIdentifier]{g['title'][:50]} 名称与目标零重叠，本地排除")
                else:
                    pending.append(g)
            else:
                if any(base_matched):
                    info = self._build_direct_media_info(g, match_media)
                    self._media_ident_cache.set(key, info)
                    log.info(f"[BatchIdentifier]{g['title'][:50]} (保守) 直通")
                elif not any(base_matched):
                    self._media_ident_cache.set(key, self._build_group_media_info(g), ttl=_NOT_FOUND_TTL)
                    log.info(f"[BatchIdentifier]{g['title'][:50]} 名称与目标零重叠，本地排除")
                else:
                    pending.append(g)

        if not pending:
            return

        log.info(f"[BatchIdentifier]{len(pending)} 组需查 TMDB")
        try:
            status_map = self.media.identify_groups(pending)
        except Exception as e:
            log.error(f"[BatchIdentifier]批量识别出错: {e}")
            return

        for idx, g in enumerate(pending):
            status, info = status_map.get(g["_cache_key"], (IdentifyStatus.ERROR, None))
            if info is None:
                continue
            if status == IdentifyStatus.HIT:
                # 共识后验证：识别为目标剧，但组内有不匹配目标的名称（区分信息）→ 排除
                if match_media and info.tmdb_id == getattr(match_media, "tmdb_id", None):
                    check_names = target_names or base_target_names
                    unresolved = [n for n in g["names"] if not _strict_match(n, check_names)]
                    if unresolved:
                        log.info(
                            f"[BatchIdentifier]{g['title'][:50]} 共识命中目标但存在区分信息 {unresolved}，强制排除"
                        )
                        self._media_ident_cache.set(
                            g["_cache_key"], self._build_group_media_info(g), ttl=_NOT_FOUND_TTL
                        )
                        continue
                self._media_ident_cache.set(g["_cache_key"], info)
            elif status == IdentifyStatus.NOT_FOUND:
                # 未匹配结果短 TTL 缓存；ERROR 不缓存，下次搜索立即重试
                self._media_ident_cache.set(g["_cache_key"], info, ttl=_NOT_FOUND_TTL)
            if idx % 10 == 0 or idx == len(pending) - 1:
                self.progress.update(
                    ptype=progress_key,
                    text=f"识别 {g['title'][:20]}... ({idx + 1}/{len(pending)})",
                )

    def _identify_via_resolver(self, order: list, groups: dict, match_media, progress_key) -> None:
        """ADR-014 P2：统一由 IdentityResolver 决策识别路径（两阶段：本地先行 + 外部攒批并发）"""
        resolver = get_identity_resolver(self.media)
        total = len(order)
        pending: list[dict] = []
        stats = {"local_hit": 0, "local_reject": 0, "external_pending": 0, "external_hit": 0, "external_fail": 0}

        # 阶段1：本地决策（直通/索引/评分，零外部调用）
        for idx, key in enumerate(order):
            g = groups[key]
            result = resolver.resolve_local(g, match_media)
            if result is None:
                pending.append(g)
                stats["external_pending"] += 1
                continue
            self._apply_result(key, result)
            if result.status == IdentifyStatus.HIT:
                stats["local_hit"] += 1
            elif result.status == IdentifyStatus.NOT_FOUND:
                stats["local_reject"] += 1
            log.info(f"[BatchIdentifier]{g['title'][:50]} [{result.reason}] confidence={result.confidence:.2f}")
            if idx % 10 == 0 or idx == total - 1:
                self.progress.update(ptype=progress_key, text=f"本地识别 {idx + 1}/{total} ...")

        if not pending:
            log.info(f"[BatchIdentifier]识别完成(全本地): {stats}")
            return

        # 阶段2：外部解析（攒批并发，一次 identify_groups 调用）
        log.info(f"[BatchIdentifier]{len(pending)} 组需外部识别 ...")
        ext_results = resolver.resolve_external_batch(pending, match_media)
        for g in pending:
            result = ext_results.get(g["_cache_key"])
            if result:
                self._apply_result(g["_cache_key"], result)
                if result.status == IdentifyStatus.HIT:
                    stats["external_hit"] += 1
                else:
                    stats["external_fail"] += 1
                log.info(f"[BatchIdentifier]{g['title'][:50]} [{result.reason}] confidence={result.confidence:.2f}")
        log.info(f"[BatchIdentifier]识别完成: {stats}")

    def _apply_result(self, key: str, result) -> None:
        if result.status == IdentifyStatus.HIT and result.media_info:
            # 置信度透传：ResolveResult.confidence → 缓存 MediaInfo
            result.media_info.confidence = result.confidence
            self._media_ident_cache.set(key, result.media_info)
        elif result.status == IdentifyStatus.NOT_FOUND and result.media_info:
            self._media_ident_cache.set(key, result.media_info, ttl=_NOT_FOUND_TTL)
        # ERROR 不缓存，下次搜索立即重试

    @staticmethod
    def _guards_pass(group: dict, match_media) -> bool:
        """类型一致 + 年份一致（或种子无年份）。TV 和 ANIME 互认兼容。

        年份守卫：电影严格一致（同名不同年的电影是不同作品）；
        剧集/动漫放宽——多季剧集跨年份（S2 播映年晚于 S1 首播年），
        且种子标题年份常为发行/压片年而非首播年，名称精确匹配 + tmdb_id 才是真正的判别依据。
        """
        m_type = getattr(match_media, "type", None)
        g_type = group.get("type")
        if g_type and m_type and g_type != m_type:
            if not ({g_type, m_type} <= {MediaType.TV, MediaType.ANIME}):
                return False
        g_year = str(group.get("year") or "")
        m_year = str(getattr(match_media, "year", "") or "")
        if not (g_year and m_year):
            return True
        if g_year == m_year:
            return True
        # 剧集/动漫：年份不一致不作为硬冲突（多季/重制/发行年差异）
        if m_type in (MediaType.TV, MediaType.ANIME) or g_type in (MediaType.TV, MediaType.ANIME):
            return True
        return False

    @staticmethod
    def _build_group_media_info(group: dict) -> MediaInfo:
        """由组元信息构造无 TMDB 的 MediaInfo（本地排除/未命中用）"""
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
        return info

    @classmethod
    def _build_direct_media_info(cls, group: dict, match_media) -> MediaInfo:
        """直通命中：组元信息 + 目标媒体信息"""
        info = cls._build_group_media_info(group)
        info.tmdb_id = match_media.tmdb_id
        info.year = info.year or getattr(match_media, "year", None)
        info.type = info.type or getattr(match_media, "type", None)
        info.title = getattr(match_media, "title", None)
        info.original_title = getattr(match_media, "original_title", None)
        info.tmdb_info = getattr(match_media, "tmdb_info", None) or {}
        info.poster_path = getattr(match_media, "poster_path", None)
        info.backdrop_path = getattr(match_media, "backdrop_path", None)
        # 全名严格命中目标别名集 → 最高置信
        info.confidence = 1.0
        return info
