"""搜索意图理解 Agent — 实现 domain 层 IntentResolver 端口（LLM 增强）"""

import log
from app.agent.prompts.search import SEARCH_INTENT_PROMPT
from app.domain.interfaces.intent import SearchIntent


class SearchIntentAgent:
    """搜索意图理解 Agent — LLM 实现 IntentResolver 端口"""

    def __init__(self, svc):

        self._svc = svc

    @property
    def ready(self) -> bool:
        return self._svc.ready

    def resolve(self, text: str) -> SearchIntent:
        """LLM 意图解析（IntentResolver 端口实现）；失败返回空意图"""
        if not self.ready:
            return SearchIntent(raw_text=text)
        log.info(f"[SearchIntentAgent]解析意图: {text[:80]}...")
        result = self._svc.structured_chat(
            messages=[{"role": "user", "content": text}],
            system_prompt=SEARCH_INTENT_PROMPT,
            response_model=SearchIntent,
        )
        if result is None:
            log.warn("[SearchIntentAgent]解析失败")
            return SearchIntent(raw_text=text)
        result.raw_text = text
        if result.is_specific:
            log.info(
                f"[SearchIntentAgent]解析成功: keywords={result.keywords}, type={result.media_type}, "
                f"season={result.season}, ep={result.episode}, year={result.year}"
            )
        else:
            log.info(f"[SearchIntentAgent]意图不明确: keywords={result.keywords}")
        return result

    def parse(self, query: str) -> SearchIntent:
        """兼容旧接口（parse → resolve）"""
        return self.resolve(query)
