"""
目标匹配器（ADR-014 P3）

匹配语义：work_id 判等 + EditionGraph 距离，输出可解释结果。
名称不确定性已在识别层消化，本层不做任何名称比较。
"""

from dataclasses import dataclass

from app.media.identity.graph import get_edition_graph
from app.media.identity.index import get_alias_index
from app.media.models import MediaInfo


@dataclass
class MatchResult:
    matched: bool
    reason: str = ""


class TargetMatcher:
    """work_id 相等 + edition 距离的目标匹配"""

    def __init__(self, graph=None, index=None):
        self._graph = graph or get_edition_graph()
        self._index = index or get_alias_index()

    def match(self, media_info: MediaInfo, match_media: MediaInfo) -> MatchResult:
        if not match_media or not getattr(match_media, "tmdb_id", None):
            return MatchResult(True, "no_target")
        if not media_info or not media_info.tmdb_id:
            return MatchResult(False, "no_identity")

        if str(media_info.tmdb_id) == str(match_media.tmdb_id):
            return MatchResult(True, "id_match")

        # 同 franchise 不同 edition → 可解释拒绝
        franchise = self._shared_franchise(media_info.tmdb_id, match_media.tmdb_id)
        if franchise:
            reason = f"同系列不同版本({franchise}): {media_info.tmdb_id} ≠ 目标 {match_media.tmdb_id}"
        else:
            reason = (
                f"非同一作品: {media_info.get_title_string()}/{media_info.tmdb_id} "
                f"≠ {match_media.get_title_string()}/{match_media.tmdb_id}"
            )
        return MatchResult(False, reason)

    def _shared_franchise(self, tmdb_id_a, tmdb_id_b) -> str | None:
        """两个 tmdb 作品是否同属一个 franchise（有图时判断；无图返回 None）"""
        try:
            a = int(tmdb_id_a)
            b = int(tmdb_id_b)
        except (TypeError, ValueError):
            return None
        wa = self._index.get_work("tmdb", a)
        wb = self._index.get_work("tmdb", b)
        if not wa or not wb or not wa.franchise or not wb.franchise:
            return None
        if wa.franchise == wb.franchise:
            return wa.franchise
        return None


_matcher: TargetMatcher | None = None


def get_target_matcher() -> TargetMatcher:
    global _matcher
    if _matcher is None:
        _matcher = TargetMatcher()
    return _matcher


def set_target_matcher(matcher: TargetMatcher | None) -> None:
    """DI 装配入口：注入 builder 显式构建的实例；None 复位（测试隔离）。"""
    global _matcher
    _matcher = matcher
