"""Google Gemini 提供商"""

import warnings
from typing import Any

with warnings.catch_warnings():
    warnings.simplefilter("ignore", DeprecationWarning)
    from google import genai  # type: ignore  # noqa: PGH003
    from google.genai import types
    from google.genai.errors import ClientError

import log
from app.agent.providers.base import BaseEmbeddingProvider, BaseProvider, ProviderConfig, ReasoningConfig

# 推理强度 → thinkingBudget（token 预算；0 = 关闭思考）
_THINKING_BUDGET = {"low": 1024, "high": 4096, "max": 16384}


class GeminiProvider(BaseProvider):
    """Google Gemini 提供商"""

    def __init__(self, config: ProviderConfig):
        super().__init__(config)
        self._client = genai.Client(api_key=config.api_key)
        # 已确认不支持 thinking_config 的模型（剥离重试成功时记录）
        self._thinking_unsupported: set[str] = set()

    def chat(
        self,
        messages: list[dict],
        system_prompt: str = "",
        temperature: float = 0.7,
        response_format: type | None = None,
        reasoning: ReasoningConfig | None = None,
    ) -> Any:
        contents = []
        for m in messages:
            if m.get("role") == "user":
                contents.append(m.get("content", ""))

        config = types.GenerateContentConfig(
            response_mime_type="application/json" if response_format else None,
            temperature=temperature,
        )
        if reasoning and self._config.model not in self._thinking_unsupported:
            budget = 0 if not reasoning.enabled else _THINKING_BUDGET.get(reasoning.effort, 4096)
            config.thinking_config = types.ThinkingConfig(thinking_budget=budget)

        try:
            resp = self._client.models.generate_content(
                model=self._config.model,
                contents=contents,
                config=config,
            )
        except ClientError as e:
            # 模型不支持 thinking_config 时剥离后重试一次（并记忆该模型）
            if e.code == 400 and config.thinking_config and "thinking" in str(e).lower():
                log.debug("[GeminiProvider]模型不支持 thinking_config，剥离后重试")
                config.thinking_config = None
                self._thinking_unsupported.add(self._config.model)
                resp = self._client.models.generate_content(
                    model=self._config.model,
                    contents=contents,
                    config=config,
                )
            else:
                raise
        return resp.text

    def is_available(self) -> bool:
        try:
            self._client.models.list()
            return True
        except Exception:
            return False

    def list_models(self) -> list[str]:
        try:
            models = self._client.models.list()
            return [name for m in models if (name := m.name) is not None]
        except Exception as e:
            log.warn(f"[GeminiProvider]查询模型列表失败: {e}")
            return []


class GeminiEmbeddingProvider(BaseEmbeddingProvider):
    """Google Gemini Embedding 提供商（gemini-embedding 系列）"""

    def __init__(self, config: ProviderConfig, model: str):
        super().__init__(config, model)
        self._client = genai.Client(api_key=config.api_key)

    def embed(self, texts: list[str]) -> list[list[float]]:
        if not texts:
            return []
        contents: list[Any] = [types.Part.from_text(text=t) for t in texts]
        resp = self._client.models.embed_content(model=self._model, contents=contents)
        vectors = [list(map(float, e.values)) for e in resp.embeddings or [] if e.values]
        if vectors and self._dimension is None:
            self._dimension = len(vectors[0])
        return vectors

    def is_available(self) -> bool:
        try:
            self.embed(["health check"])
            return True
        except Exception as e:
            log.warn(f"[GeminiEmbeddingProvider]不可用: {e}")
            return False
