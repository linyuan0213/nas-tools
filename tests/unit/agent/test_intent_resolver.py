"""IntentResolverChain 单元测试"""

from app.domain.interfaces.intent import SearchIntent
from app.services.search_intent_resolver import IntentResolverChain


class _FakeLLMResolver:
    def __init__(self, intent: SearchIntent | None = None, fail: bool = False):
        self._intent = intent
        self._fail = fail
        self.calls = 0

    def resolve(self, text: str) -> SearchIntent:
        self.calls += 1
        if self._fail:
            raise RuntimeError("LLM 不可用")
        return self._intent or SearchIntent(raw_text=text)


class TestRuleResolve:
    def test_movie_with_year(self):
        chain = IntentResolverChain()
        intent = chain.resolve("电影 流浪地球 2019")
        # 规则行为：电影前缀仅剥离不设类型（与旧流水线一致），年份可提取
        assert intent.media_type is None
        assert intent.year == 2019
        assert "流浪地球" in intent.keywords
        assert intent.is_specific

    def test_tv_with_season_episode(self):
        chain = IntentResolverChain()
        intent = chain.resolve("权力的游戏 第2季 第3集")
        assert intent.media_type == "tv"
        assert intent.season == 2
        assert intent.episode == 3
        assert intent.is_specific

    def test_plain_keyword_not_specific(self):
        chain = IntentResolverChain()
        intent = chain.resolve("流浪地球")
        assert intent.keywords == "流浪地球"
        assert not intent.is_specific
        assert intent.media_type is None

    def test_empty_text(self):
        chain = IntentResolverChain()
        intent = chain.resolve("")
        assert intent.keywords == ""


class TestLLMEnhance:
    def test_llm_fills_missing_fields(self):
        llm = _FakeLLMResolver(SearchIntent(keywords="流浪地球", media_type="movie", year=2019, is_specific=True))
        chain = IntentResolverChain(llm_resolver=llm)
        intent = chain.resolve("流浪地球")
        assert intent.media_type == "movie"
        assert intent.year == 2019
        assert intent.is_specific

    def test_llm_not_called_when_rule_specific(self):
        llm = _FakeLLMResolver(SearchIntent(keywords="x"))
        chain = IntentResolverChain(llm_resolver=llm)
        chain.resolve("电影 流浪地球 2019")
        assert llm.calls == 0

    def test_llm_does_not_override_rule_fields(self):
        llm = _FakeLLMResolver(SearchIntent(keywords="别的", media_type="tv", year=2020, is_specific=True))
        chain = IntentResolverChain(llm_resolver=llm)
        # 规则未识别（非 specific）→ LLM 增强，但 keywords 已有值则保留
        intent = chain.resolve("流浪地球")
        assert intent.keywords == "流浪地球"

    def test_llm_failure_degrades_to_rule(self):
        llm = _FakeLLMResolver(fail=True)
        chain = IntentResolverChain(llm_resolver=llm)
        intent = chain.resolve("流浪地球")
        assert intent.keywords == "流浪地球"

    def test_no_llm_pure_rule(self):
        chain = IntentResolverChain(llm_resolver=None)
        intent = chain.resolve("电视剧 漫长的季节 第1季")
        assert intent.media_type == "tv"
        assert intent.season == 1
