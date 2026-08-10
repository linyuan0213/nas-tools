"""搜索意图解析链 — 规则解析优先，LLM 可选增强，归一化为统一 SearchIntent"""

import log
from app.domain.interfaces.intent import IntentResolver, SearchIntent
from app.domain.mediatypes import MediaType
from app.utils import StringUtils

_MEDIA_TYPE_STR = {
    MediaType.MOVIE: "movie",
    MediaType.TV: "tv",
    MediaType.ANIME: "anime",
}


class IntentResolverChain:
    """意图解析链：规则（get_keyword_from_string）→ LLM 增强（可选）→ 归一化"""

    def __init__(self, llm_resolver: IntentResolver | None = None):
        self._llm = llm_resolver

    def resolve(self, text: str) -> SearchIntent:
        intent = self._rule_resolve(text)
        if self._llm and not intent.is_specific:
            intent = self._llm_enhance(text, intent)
        return intent

    @staticmethod
    def _rule_resolve(text: str) -> SearchIntent:
        """规则解析：正则提取 类型/季/集/年份/关键词"""
        if not text:
            return SearchIntent()
        mtype, key_word, season_num, episode_num, year, content = StringUtils.get_keyword_from_string(text)
        keywords = (content or key_word or text).strip()
        is_specific = bool(keywords and (mtype or season_num or episode_num or year))
        return SearchIntent(
            keywords=keywords,
            media_type=_MEDIA_TYPE_STR.get(mtype) if mtype else None,
            year=int(year) if year and str(year).isdigit() else None,
            season=season_num,
            episode=episode_num,
            raw_text=text,
            is_specific=is_specific,
        )

    def _llm_enhance(self, text: str, intent: SearchIntent) -> SearchIntent:
        """LLM 增强：仅补充规则未识别的字段，不覆盖规则结果"""
        try:
            llm_intent = self._llm.resolve(text) if self._llm else None
        except Exception as e:
            log.warn(f"[IntentResolverChain]LLM 意图解析失败，使用规则结果: {e}")
            return intent
        if not llm_intent:
            return intent
        if not intent.keywords and llm_intent.keywords:
            intent.keywords = llm_intent.keywords
        if not intent.media_type and llm_intent.media_type:
            intent.media_type = llm_intent.media_type
        if intent.year is None and llm_intent.year is not None:
            intent.year = llm_intent.year
        if intent.season is None and llm_intent.season is not None:
            intent.season = llm_intent.season
        if intent.episode is None and llm_intent.episode is not None:
            intent.episode = llm_intent.episode
        if llm_intent.is_specific:
            intent.is_specific = True
        return intent
