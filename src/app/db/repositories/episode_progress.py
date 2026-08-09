"""订阅续订的连续集数计算（下载记录与转移记录共用）."""

import re
from collections.abc import Iterable

_SEASON_RE = re.compile(r"S(\d+)", flags=re.IGNORECASE)
_EPISODE_RANGE_RE = re.compile(r"S(\d+)\s*E(\d+)(?:\s*[-~]\s*E?(\d+))?", flags=re.IGNORECASE)


def contiguous_episodes(se_values: Iterable[str | None], season: int) -> int:
    """计算某季「从第 1 集起连续」的集数.

    只按明确集号统计：单集 "S08 E07" / "S08E07"、范围 "S08E01-E12" / "S08 E01-E12"。
    季包仅记季号 "S08" 时保守记为第 1 集已存在——不能假设整季已获得
    （季包可能只包含一集），宁少勿多，缺失集交由去重层补齐。
    取连续段长度而非最大集数，避免中间缺集时跳过缺失集。
    """
    season_num = int(season or 1)
    present: set[int] = set()
    for se in se_values:
        if not se:
            continue
        sm = _SEASON_RE.search(se)
        if not sm or int(sm.group(1)) != season_num:
            continue
        em = _EPISODE_RANGE_RE.search(se)
        if not em:
            present.add(1)  # 季包，保守记为至少第 1 集已存在
            continue
        start = int(em.group(2))
        end = int(em.group(3)) if em.group(3) else start
        present.update(range(start, end + 1))
    contiguous = 0
    while (contiguous + 1) in present:
        contiguous += 1
    return contiguous
