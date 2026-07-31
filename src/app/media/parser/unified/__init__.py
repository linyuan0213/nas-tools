"""统一解析引擎主入口"""

from __future__ import annotations

from app.domain.mediatypes import MediaType
from app.media.parser.base import BaseParser, ParserResult

from .name_extractor import clean_names, extract_name
from .preprocessor import prepare_title
from .rules import get_rule_engine
from .type_inferrer import infer_type
from .types import ParseContext


class UnifiedParser(BaseParser):
    """统一标题解析器 — 合并动漫/影视两条管线"""

    def __init__(self) -> None:
        self._engine = get_rule_engine()

    def parse(self, title: str, subtitle: str = "") -> ParserResult | None:
        if not title:
            return None

        # Phase 1: 预处理
        prepared = prepare_title(title)

        # Phase 2: 元素提取
        ctx = ParseContext(text=prepared)
        self._engine.apply(ctx)

        # Phase 3: 名称提取
        extract_name(ctx, title)
        clean_names(ctx)

        # Phase 4: 类型推断
        media_type = infer_type(ctx)

        # Phase 5: 组装结果
        return self._build_result(ctx, media_type, title)

    def _build_result(self, ctx: ParseContext, media_type: MediaType, original: str) -> ParserResult:
        confidence = self._calculate_confidence(ctx)
        season, end_season = self._to_int_pair(ctx.season)
        episode, end_episode = self._to_int_pair(ctx.episode)

        return ParserResult(
            title_en=ctx.en_name,
            title_cn=ctx.cn_name,
            year=ctx.year,
            season=season,
            end_season=end_season,
            episode=episode,
            end_episode=end_episode,
            resource_pix=ctx.resolution,
            resource_type=ctx.source,
            video_encode=ctx.video_codec,
            audio_encode=ctx.audio_codec,
            resource_team=ctx.resource_team or ctx.release_group,
            type=media_type,
            confidence=confidence,
            org_string=original,
        )

    def _calculate_confidence(self, ctx: ParseContext) -> float:
        if not ctx.elements:
            return 0.3
        total = sum(e.confidence for e in ctx.elements)
        avg = total / len(ctx.elements)
        # 有名称时提升置信度
        if ctx.cn_name or ctx.en_name:
            avg = min(avg + 0.1, 0.98)
        return round(avg, 2)

    def _to_int_pair(self, value: int | list[int] | None) -> tuple[int | None, int | None]:
        if value is None:
            return None, None
        if isinstance(value, list):
            if len(value) == 1:
                return value[0], None
            return value[0], value[-1]
        return value, None
