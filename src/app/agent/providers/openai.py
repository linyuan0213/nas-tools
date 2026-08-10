"""OpenAI / OpenAI 兼容提供商"""

from typing import Any

from openai import APIStatusError, OpenAI

import log
from app.agent.providers.base import BaseEmbeddingProvider, BaseProvider, ProviderConfig


class OpenAIProvider(BaseProvider):
    """OpenAI 兼容提供商 — 支持 OpenAI、Moonshot、DeepSeek 等"""

    def __init__(self, config: ProviderConfig):
        super().__init__(config)
        self._client = OpenAI(
            base_url=config.api_url,
            api_key=config.api_key,
            timeout=config.timeout,
        )

    def chat(
        self,
        messages: list[dict],
        system_prompt: str = "",
        temperature: float = 0.7,
        response_format: type | None = None,
    ) -> Any:
        msgs = []
        if system_prompt:
            msgs.append({"role": "system", "content": system_prompt})
        msgs.extend(messages)

        kwargs = {
            "model": self._config.model,
            "messages": msgs,
            "temperature": temperature,
        }
        if response_format:
            kwargs["response_format"] = {"type": "json_object"}

        try:
            resp = self._client.chat.completions.create(**kwargs)
            return resp.choices[0].message.content
        except Exception as e:
            err_msg = self._format_error(e)
            log.warn(f"[OpenAIProvider]请求失败: {err_msg}")
            return ""

    @staticmethod
    def _format_error(e: Exception) -> str:
        """将异常转换为用户可读的提示"""

        if isinstance(e, APIStatusError):
            code = e.status_code
            body: Any = e.body or {}
            msg = body.get("error", {}).get("message", str(e))
            if code == 401:
                return f"API Key 无效或已过期 ({msg})"
            if code == 402:
                return f"账户余额不足，请充值 ({msg})"
            if code == 429:
                return f"请求过于频繁，请稍后再试 ({msg})"
            if code >= 500:
                return f"Provider 服务端错误 ({code}: {msg})"
            return f"Provider 错误 ({code}: {msg})"
        return str(e)

    def is_available(self) -> bool:
        try:
            self._client.models.list()
            return True
        except Exception:
            return False

    def list_models(self) -> list[str]:
        try:
            models = self._client.models.list()
            return [m.id for m in models.data]
        except Exception as e:
            log.warn(f"[OpenAIProvider]查询模型列表失败: {e}")
            return []


class OpenAIEmbeddingProvider(BaseEmbeddingProvider):
    """OpenAI 兼容 Embedding 提供商（text-embedding-3 系列 / bge 等）"""

    def __init__(self, config: ProviderConfig, model: str):
        super().__init__(config, model)
        self._client = OpenAI(
            base_url=config.api_url,
            api_key=config.api_key,
            timeout=config.timeout,
        )

    def embed(self, texts: list[str]) -> list[list[float]]:
        if not texts:
            return []
        resp = self._client.embeddings.create(model=self._model, input=texts)
        vectors = [list(map(float, item.embedding)) for item in resp.data]
        if vectors and self._dimension is None:
            self._dimension = len(vectors[0])
        return vectors

    def is_available(self) -> bool:
        try:
            self.embed(["health check"])
            return True
        except Exception as e:
            log.warn(f"[OpenAIEmbeddingProvider]不可用: {e}")
            return False
