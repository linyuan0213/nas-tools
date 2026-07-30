"""
集数映射器 — 全自动将解析出的季集映射到 TMDB 标准季集

触发条件（同时满足）：
  1. TMDB 上该剧正常季数 < Parser 解析出的季号
  2. 获取到的总集数 > 典型单季集数（>26）

映射逻辑：
  1. 获取 TMDB 全部 episodes（排除 Specials）
  2. 按 episode_number 排序，根据 air_date 间隔推断季分界
  3. 间隔 > 90 天视为新季开始
  4. 每个 block 对应 Parser 的一个季
  5. 返回映射后的 TMDB season/episode

普通电视剧（如 Breaking Bad S03E05）：
  TMDB 有 S01-S05，Parser 季号 3 <= 5 → 不触发映射

动漫合并季（如 Re:Zero S04E01）：
  TMDB 只有 S01，Parser 季号 4 > 1 → 触发映射
  推断出4个季块后 → 映射到 S01 对应集
"""

from concurrent.futures import ThreadPoolExecutor
from datetime import datetime

import log
from app.core.constants import (
    EPISODE_MAPPER_MIN_BLOCK_LENGTH,
    EPISODE_MAPPER_MIN_TOTAL_EPISODES,
    EPISODE_MAPPER_SEASON_GAP_DAYS,
    EPISODE_MAPPER_SEASON_GAP_FORCE_DAYS,
)
from app.domain.mediatypes import MediaType
from app.media.lookup.tmdb_lookup import TmdbLookup


class EpisodeMapper:
    """全自动集数映射器"""

    def __init__(self, tmdb_lookup: TmdbLookup | None = None):
        self._tmdb = tmdb_lookup
        # 缓存: tmdb_id -> [(block_season, start_ep, end_ep), ...]
        self._blocks: dict[int | str, list[tuple[int, int, int]]] = {}

    def _fetch_blocks(self, tmdb_id: int) -> list[tuple[int, int, int]] | None:
        """从 TMDB 获取 episodes，按 air_date 推断季分界"""
        if tmdb_id in self._blocks:
            return self._blocks[tmdb_id]
        if not self._tmdb:
            return None

        try:
            tv_info = self._tmdb.get_tmdb_info(MediaType.TV, tmdb_id)
            if not tv_info:
                return None

            seasons = tv_info.get("seasons") or []
            normal_seasons = [s for s in seasons if s.get("season_number", 0) > 0]
            if not normal_seasons:
                return None

            max_tmdb_season = max(s.get("season_number", 0) for s in normal_seasons)
            total_episodes = sum(s.get("episode_count", 0) for s in normal_seasons)

            # 总集数不够多，不是合并季
            if total_episodes < EPISODE_MAPPER_MIN_TOTAL_EPISODES:
                return None

            # 收集所有 episodes
            all_eps = []
            for season in normal_seasons:
                sn = season.get("season_number")
                eps = self._tmdb.season.get_episodes(tmdb_id, sn)
                for ep in eps:
                    ep["_tmdb_season"] = sn
                all_eps.extend(eps)

            if len(all_eps) < 2:
                return None

            all_eps = sorted(all_eps, key=lambda e: (e.get("_tmdb_season", 0), e.get("episode_number", 0)))

            # 推断季分界
            # 策略：
            #   1. 间隔 > EPISODE_MAPPER_SEASON_GAP_FORCE_DAYS (180天) → 强制分季
            #   2. 间隔 > EPISODE_MAPPER_SEASON_GAP_DAYS (90天) 且当前 block 已 >=
            #      EPISODE_MAPPER_MIN_BLOCK_LENGTH → 分季
            #   3. 否则 → 不分季（视为季内分割放送）
            blocks = []
            cur_season = 1
            start_ep = all_eps[0].get("episode_number", 1)
            block_start_idx = 0

            for i in range(1, len(all_eps)):
                prev = all_eps[i - 1]
                curr = all_eps[i]
                prev_date = _parse_date(prev.get("air_date"))
                curr_date = _parse_date(curr.get("air_date"))

                gap = None
                if prev_date and curr_date:
                    gap = (curr_date - prev_date).days

                should_split = False
                # TMDB finale/mid_season 标记 → 强制分季
                prev_type = prev.get("episode_type", "")
                if prev_type in ("finale", "mid_season", "mid_season_finale"):
                    should_split = True
                elif gap:
                    if gap > EPISODE_MAPPER_SEASON_GAP_FORCE_DAYS:
                        should_split = True
                    elif gap > EPISODE_MAPPER_SEASON_GAP_DAYS:
                        current_length = i - block_start_idx
                        if current_length >= EPISODE_MAPPER_MIN_BLOCK_LENGTH:
                            should_split = True

                if should_split:
                    blocks.append((cur_season, start_ep, prev.get("episode_number", start_ep)))
                    cur_season += 1
                    start_ep = curr.get("episode_number", start_ep + 1)
                    block_start_idx = i

            blocks.append((cur_season, start_ep, all_eps[-1].get("episode_number", start_ep)))

            # 如果推断出的季数 <= TMDB 实际季数，验证边界对齐
            if len(blocks) <= max_tmdb_season:
                # 对比每个 block 的起始集号是否与 TMDB 季累计一致
                tmdb_cumulative = 1
                aligned = True
                for i, s in enumerate(normal_seasons):
                    count = s.get("episode_count", 0)
                    if count <= 0:
                        continue
                    if i < len(blocks) and blocks[i][1] != tmdb_cumulative:
                        aligned = False
                        log.info(
                            f"[EpisodeMapper]TMDB {tmdb_id} S{i+1}: "
                            f"推断起始E{blocks[i][1]} ≠ TMDB起始E{tmdb_cumulative}，需要映射"
                        )
                        break
                    tmdb_cumulative += count
                if aligned:
                    return None
                # 边界不一致 — 作为合并季处理
                self._blocks[tmdb_id] = blocks
                log.info(f"[EpisodeMapper]TMDB {tmdb_id} 推断季结构(边界不一致): {blocks}")
                return blocks

            self._blocks[tmdb_id] = blocks
            log.info(f"[EpisodeMapper]TMDB {tmdb_id} 推断季结构: {blocks}")
            return blocks

        except Exception as e:
            log.warn(f"[EpisodeMapper]推断失败: {e}")
            return None

    def map(self, tmdb_id: int, source_season: int | None, source_episode: int | None) -> tuple[int, int] | None:
        """
        将 Parser 解析的季集映射到 TMDB 标准季集

        Returns:
            (target_season, target_episode) 或 None（无需映射/失败）
        """
        if not source_season or not source_episode or source_season < 1:
            return None

        blocks = self._fetch_blocks(tmdb_id)
        if not blocks:
            return None

        if source_season > len(blocks):
            log.warn(f"[EpisodeMapper]源季号 {source_season} > 推断季数 {len(blocks)}，跳过避免误映射")
            return None

        _, start_ep, end_ep = blocks[source_season - 1]
        target_ep = start_ep + source_episode - 1
        if target_ep > end_ep:
            log.warn(f"[EpisodeMapper]映射后集号 {target_ep} 超出范围 (E{start_ep}-E{end_ep})")
            return None

        log.info(f"[EpisodeMapper]TMDB:{tmdb_id} S{source_season:02d}E{source_episode:02d} → S01E{target_ep:02d}")
        return 1, target_ep

    def map_auto(
        self,
        tmdb_id: int,
        source_season: int | None,
        source_episode: int | None,
        source_end_ep: int | None = None,
    ) -> tuple[int, int] | None | tuple[int, int, int, int]:
        """
        自动选择映射策略

        - 高集号(>26)/无季号/season=1: 绝对集号映射
        - season>1: 合并季 / 部分错位映射（→ _fetch_blocks）
        - 返回 None = 无需映射
        """
        if not source_episode or source_episode < 1:
            # 季节包（无集号）：先检查 TMDB 是否有该季
            if source_season and source_season > 1 and self._tmdb:
                cache_key2 = f"seasons:{tmdb_id}"
                seasons = self._blocks.get(cache_key2)
                if not seasons:
                    try:
                        tv_info = self._tmdb.get_tmdb_info(MediaType.TV, tmdb_id)
                        if tv_info:
                            raw = [s for s in tv_info.get("seasons", []) if s.get("season_number", 0) > 0]
                            seasons = sorted(raw, key=lambda s: s.get("season_number", 0))
                            self._blocks[cache_key2] = seasons
                    except Exception:
                        seasons = None
                if seasons:
                    for s in seasons:
                        if s.get("season_number") == source_season:
                            return None  # TMDB 已有该季，不需要映射
                # TMDB 没有该季 → 推断 blocks，范围内才映射
                blocks = self._fetch_blocks(tmdb_id)
                if blocks and source_season <= len(blocks):
                    return 1, 0
            return None

        # 高集号 / 无季号 / season=1 → 先查 TMDB 是否有该季
        if (not source_season or source_season == 1 or source_episode > 26) and self._tmdb:
            cache_key = f"abs:{tmdb_id}"
            seasons = self._blocks.get(cache_key)
            if not seasons:
                try:
                    tv_info = self._tmdb.get_tmdb_info(MediaType.TV, tmdb_id)
                    if tv_info:
                        raw = [s for s in tv_info.get("seasons", []) if s.get("season_number", 0) > 0]
                        seasons = sorted(raw, key=lambda s: s.get("season_number", 0))
                        self._blocks[cache_key] = seasons
                except Exception:
                    seasons = None
            if seasons and source_season:
                for s in seasons:
                    if s.get("season_number") == source_season:
                        if 1 <= (source_episode or 1) <= s.get("episode_count", 0):
                            return None  # TMDB 已有该季且集号在范围内
                        break
            return self.map_absolute(tmdb_id, source_episode, source_end_ep)

        # season>1 + ep≤26 → 先快速检查 TMDB 是否已有该季
        if self._tmdb:
            cache_key = f"abs:{tmdb_id}"
            seasons = self._blocks.get(cache_key)
            if not seasons:
                try:
                    tv_info = self._tmdb.get_tmdb_info(MediaType.TV, tmdb_id)
                    if tv_info:
                        raw = [s for s in tv_info.get("seasons", []) if s.get("season_number", 0) > 0]
                        seasons = sorted(raw, key=lambda s: s.get("season_number", 0))
                        self._blocks[cache_key] = seasons
                except Exception:
                    seasons = None
            if seasons:
                for s in seasons:
                    if s.get("season_number") == source_season:
                        count = s.get("episode_count", 0)
                        if 1 <= source_episode <= count:
                            return None
                        break

        # 快速检查未命中 → 无可靠映射，不猜测
        return None

    def map_batch(self, items: list[dict]) -> list[tuple[int, int] | None]:
        """
        批量映射 — 相同 tmdb_id 共享缓存，不同 tmdb_id 并发查询

        Args:
            items: [{"tmdb_id": int, "season": int, "episode": int}, ...]

        Returns:
            [(target_season, target_episode) 或 None, ...]
        """
        if not items:
            return []

        # 按 tmdb_id 去重，只查未缓存的（合并季缓存）
        tmdb_ids_blocks = {
            item["tmdb_id"]
            for item in items
            if item.get("tmdb_id") and item["tmdb_id"] not in self._blocks and item.get("season") and item["season"] > 1
        }

        # 按 tmdb_id 去重，只查未缓存的（绝对集号缓存）
        # season=None / season=1 / episode>26 都会走 map_absolute
        tmdb_ids_abs = {
            item["tmdb_id"]
            for item in items
            if item.get("tmdb_id")
            and f"abs:{item['tmdb_id']}" not in self._blocks
            and (not item.get("season") or item.get("season") == 1 or (item.get("episode", 0) or 0) > 26)
        }

        # 并发查询多个不同 tmdb_id
        if tmdb_ids_blocks:
            with ThreadPoolExecutor(max_workers=min(len(tmdb_ids_blocks), 5)) as executor:
                list(executor.map(self._fetch_blocks, tmdb_ids_blocks))

        if tmdb_ids_abs:
            with ThreadPoolExecutor(max_workers=min(len(tmdb_ids_abs), 5)) as executor:
                list(executor.map(lambda tid: self.map_absolute(tid, 1), tmdb_ids_abs))

        # 批量计算映射结果
        results = []
        for item in items:
            result = self.map_auto(
                int(item.get("tmdb_id") or 0),
                item.get("season"),
                item.get("episode"),
                item.get("end_episode"),
            )
            results.append(result)
        return results

    def map_absolute(
        self,
        tmdb_id: int,
        absolute_episode: int,
        end_episode: int | None = None,
    ) -> tuple[int, int] | tuple[int, int, int, int] | None:
        """
        将绝对集号映射到 TMDB 标准季集

        Returns:
            单集: (target_season, target_episode)
            范围: (sn, ep_start, end_sn, end_ep) 或 None
        """
        if not absolute_episode or absolute_episode < 1:
            return None
        if not self._tmdb:
            return None

        cache_key = f"abs:{tmdb_id}"
        seasons = self._blocks.get(cache_key)

        try:
            if not seasons:
                tv_info = self._tmdb.get_tmdb_info(MediaType.TV, tmdb_id)
                if not tv_info:
                    return None
                raw = [s for s in tv_info.get("seasons", []) if s.get("season_number", 0) > 0]
                if not raw:
                    return None
                seasons = sorted(raw, key=lambda s: s.get("season_number", 0))
                self._blocks[cache_key] = seasons

            def _find(abs_ep: int) -> tuple[int, int] | None:
                cum = 0
                for season in seasons:
                    sn = season.get("season_number")  # type: ignore[assignment]
                    count = season.get("episode_count", 0)  # type: ignore[assignment]
                    start = cum + 1
                    end_ep_num = cum + count
                    cum += count
                    if start <= abs_ep <= end_ep_num:
                        return sn, abs_ep - start + 1
                return None

            start_result = _find(absolute_episode)
            if not start_result:
                log.warn(f"[EpisodeMapper]绝对集号 {absolute_episode} 超出范围")
                return None

            if not end_episode or end_episode == absolute_episode:
                sn, ep = start_result
                log.info(f"[EpisodeMapper]TMDB:{tmdb_id} 绝对E{absolute_episode} → S{sn:02d}E{ep:02d}")
                return sn, ep

            end_result = _find(end_episode)
            if not end_result:
                log.warn(f"[EpisodeMapper]结束集号 {end_episode} 超出范围，仅映射起始集")
                sn, ep = start_result
                return sn, ep

            sn, ep_s = start_result
            end_sn, ep_e = end_result
            log.info(
                f"[EpisodeMapper]TMDB:{tmdb_id} "
                f"绝对E{absolute_episode}-E{end_episode} → S{sn:02d}E{ep_s:02d}-S{end_sn:02d}E{ep_e:02d}"
            )
            return sn, ep_s, end_sn, ep_e

        except Exception as e:
            log.warn(f"[EpisodeMapper]绝对集号映射失败: {e}")
            return None

    def invalidate(self, tmdb_id: int):
        self._blocks.pop(tmdb_id, None)
        self._blocks.pop(f"abs:{tmdb_id}", None)


def _parse_date(date_str: str | None) -> datetime | None:
    if not date_str:
        return None
    try:
        return datetime.strptime(date_str, "%Y-%m-%d")
    except ValueError:
        return None
