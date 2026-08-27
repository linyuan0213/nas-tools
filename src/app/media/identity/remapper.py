"""
集数重映射（ADR-014 P3）

统一入口：发布组编号习惯 → 合并季/绝对集映射 → 规范季集。
- numbering_overrides: 发布组季号 → 规范季号（config/edition_overrides.yaml）
- 合并季/绝对集: 复用 EpisodeMapper（TMDB 季结构推断）
- 包展开: 多季包（S1+S2）按 TMDB 季集数展开为集列表
"""

import os
from pathlib import Path

import yaml

import log
from app.domain.mediatypes import MediaType
from app.media.parser.episode_mapper import EpisodeMapper

_DEFAULT_PATH = Path(__file__).resolve().parents[4] / "config" / "edition_overrides.yaml"


def _load_overrides(path: Path | None = None) -> dict:
    p = Path(os.environ.get("NEXUS_EDITION_OVERRIDES") or (path or _DEFAULT_PATH))
    try:
        data = yaml.safe_load(p.read_text(encoding="utf-8")) or {}
    except OSError:
        return {"numbering_overrides": [], "edition_overrides": []}
    except yaml.YAMLError as e:
        log.error(f"[EpisodeRemapper]编号补充表解析失败: {p}, {e}")
        return {"numbering_overrides": [], "edition_overrides": []}
    return {
        "numbering_overrides": data.get("numbering_overrides") or [],
        "edition_overrides": data.get("edition_overrides") or [],
    }


class EpisodeRemapper:
    """发布组编号 → 规范季集的统一重映射器"""

    def __init__(self, episode_mapper: EpisodeMapper | None = None, overrides_path: Path | None = None):
        self._mapper = episode_mapper
        self._overrides = _load_overrides(overrides_path)
        self._season_map: dict[int, dict[int, int]] = {}
        for item in self._overrides["numbering_overrides"]:
            tmdb_id = item.get("tmdb_id")
            season_map = item.get("season_map") or {}
            if tmdb_id and season_map:
                self._season_map[int(tmdb_id)] = {int(k): int(v) for k, v in season_map.items()}

    # ---------- 单条映射 ----------

    def remap(
        self, tmdb_id: int, season: int | None, episode: int | None, end_episode: int | None = None
    ) -> tuple[int, int] | None | tuple[int, int, int, int]:
        """
        返回 (season, episode) 规范季集；无需映射/失败返回 None。
        优先编号习惯补充表，其次合并季/绝对集推断。
        """
        if not tmdb_id:
            return None
        overridden = self._apply_override(tmdb_id, season, episode)
        if overridden:
            return overridden
        if self._mapper:
            return self._mapper.map_auto(tmdb_id, season, episode, end_episode)
        return None

    def remap_batch(self, items: list[dict]) -> list[tuple[int, int] | tuple[int, int, int, int] | None]:
        """批量映射：先应用补充表（零 API），剩余交 EpisodeMapper.map_batch"""
        if not items:
            return []
        results: list[tuple[int, int] | tuple[int, int, int, int] | None] = [None] * len(items)
        rest: list[tuple[int, dict]] = []
        for i, item in enumerate(items):
            overridden = self._apply_override(int(item.get("tmdb_id") or 0), item.get("season"), item.get("episode"))
            if overridden:
                results[i] = overridden
            else:
                rest.append((i, item))
        if rest and self._mapper:
            mapped = self._mapper.map_batch([item for _, item in rest])
            for (i, _), r in zip(rest, mapped, strict=False):
                results[i] = r
        return results

    def _apply_override(self, tmdb_id: int, season: int | None, episode: int | None) -> tuple[int, int] | None:
        if not tmdb_id or not season or not episode:
            return None
        season_map = self._season_map.get(tmdb_id)
        if not season_map:
            return None
        canonical = season_map.get(season)
        if not canonical:
            return None
        log.info(
            f"[EpisodeRemapper]编号习惯映射: TMDB:{tmdb_id} "
            f"S{season:02d}E{episode:02d} → S{canonical:02d}E{episode:02d}"
        )
        return canonical, episode

    # ---------- 季包展开 ----------

    def expand_pack(self, tmdb_id: int, seasons: list[int]) -> list[tuple[int, int]] | None:
        """
        多季包展开：(tmdb_id, [1, 2]) → [(1,1)...(1,n),(2,1)...(2,m)]
        需要 TMDB 季集数；失败返回 None。
        """
        if not tmdb_id or not seasons or not self._mapper or not self._mapper._tmdb:
            return None
        try:
            tv_info = self._mapper._tmdb.get_tmdb_info(MediaType.TV, tmdb_id)
        except Exception as e:
            log.warn(f"[EpisodeRemapper]季包展开获取详情失败: {tmdb_id}, {e}")
            return None
        if not tv_info:
            return None
        counts = {
            s.get("season_number"): s.get("episode_count", 0)
            for s in tv_info.get("seasons") or []
            if s.get("season_number", 0) > 0
        }
        episodes: list[tuple[int, int]] = []
        for sn in seasons:
            count = counts.get(sn, 0)
            if count <= 0:
                return None
            episodes.extend((sn, ep) for ep in range(1, count + 1))
        return episodes or None


_remapper: EpisodeRemapper | None = None


def get_episode_remapper(episode_mapper: EpisodeMapper | None = None) -> EpisodeRemapper:
    global _remapper
    if _remapper is None:
        _remapper = EpisodeRemapper(episode_mapper=episode_mapper)
    return _remapper


def set_episode_remapper(remapper: EpisodeRemapper | None) -> None:
    """DI 装配入口：注入 builder 显式构建的实例；None 复位（测试隔离）。"""
    global _remapper
    _remapper = remapper
