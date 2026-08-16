"""订阅续订的连续集数计算（下载记录与转移记录共用）."""

import re
from collections.abc import Iterable

_SEASON_RE = re.compile(r"S(\d+)", flags=re.IGNORECASE)
_EPISODE_RANGE_RE = re.compile(r"S(\d+)\s*E(\d+)(?:\s*[-~]\s*E?(\d+))?", flags=re.IGNORECASE)


def contiguous_episodes(se_values: Iterable[str | None], season: int, start: int = 1) -> int:
    """计算某季「从订阅起点 start 起连续」的最大集号（重订阅续订点）.

    中途订阅场景：订阅可能从第 N 集才开始跟踪（历史只有 N 之后的集），
    此时不能从第 1 集数起（会误判为 0），应从订阅起点 start 数起。
    只按明确集号统计：单集 "S08 E07" / "S08E07"、范围 "S08E01-E12" / "S08 E01-E12"。
    季包仅记季号 "S08" 时保守记为 start 已存在——不能假设整季已获得
    （季包可能只包含一集），宁少勿多，缺失集交由去重层补齐。
    返回：从 start 起连续存在的最大集号（无记录时返回 start-1，调用方据此不推导）。
    """
    season_num = int(season or 1)
    start_num = int(start or 1)
    present: set[int] = set()
    for se in se_values:
        if not se:
            continue
        sm = _SEASON_RE.search(se)
        if not sm or int(sm.group(1)) != season_num:
            continue
        em = _EPISODE_RANGE_RE.search(se)
        if not em:
            present.add(start_num)  # 季包，保守记为订阅起点已存在
            continue
        ep_start = int(em.group(2))
        ep_end = int(em.group(3)) if em.group(3) else ep_start
        present.update(range(ep_start, ep_end + 1))
    # 只考虑订阅起点之后的集号
    present = {e for e in present if e >= start_num}
    if start_num not in present:
        # 起点集未转移 → 无连续（保守：不跳过起点向后数）
        return start_num - 1
    # 从 start_num 起找连续段终点
    cursor = start_num
    while cursor in present:
        cursor += 1
    return cursor - 1
