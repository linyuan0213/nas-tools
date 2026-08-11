"""Ollama 本地模型提供商"""

from typing import Any

from ollama import Client

import log
from app.agent.providers.base import (
    BaseEmbeddingProvider,
    BaseProvider,
    ChatToolResponse,
    ProviderConfig,
    ToolCall,
)


class OllamaProvider(BaseProvider):
    """Ollama 本地模型提供商"""

    def __init__(self, config: ProviderConfig):
        super().__init__(config)
        self._client = Client(host=config.api_url)

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
        resp = self._client.chat(
            model=self._config.model,
            messages=msgs,
            options={"temperature": temperature},
        )
        return resp["message"]["content"]

    def chat_with_tools(
        self,
        messages: list[dict],
        tools: list[dict],
        system_prompt: str = "",
        temperature: float = 0.7,
    ) -> ChatToolResponse:
        """Ollama 原生 function calling"""
        msgs: list[dict] = []
        if system_prompt:
            msgs.append({"role": "system", "content": system_prompt})
        msgs.extend(messages)
        tool_specs = [
            {
                "type": "function",
                "function": {
                    "name": t["name"],
                    "description": t.get("description", ""),
                    "parameters": t.get("parameters") or {"type": "object", "properties": {}},
                },
            }
            for t in tools
        ]
        try:
            resp = self._client.chat(
                model=self._config.model,
                messages=msgs,
                tools=tool_specs,
                options={"temperature": temperature},
            )
        except Exception as e:
            log.warn(f"[OllamaProvider]工具调用请求失败，回退 prompt 协议: {e}")
            return super().chat_with_tools(messages, tools, system_prompt, temperature)

        message = resp.get("message", {})
        calls = []
        for tc in message.get("tool_calls") or []:
            fn = tc.get("function", {})
            raw_args = fn.get("arguments")
            args = raw_args if isinstance(raw_args, dict) else {}
            calls.append(ToolCall(name=fn.get("name", ""), arguments=args, id=tc.get("id", "")))
        return ChatToolResponse(content=message.get("content", ""), tool_calls=calls, native=True)

    def is_available(self) -> bool:
        try:
            self._client.list()
            return True
        except Exception:
            return False

    def list_models(self) -> list[str]:
        try:
            result = self._client.list()
            return [m.model for m in result.models if m.model is not None] if hasattr(result, "models") else []
        except Exception as e:
            log.warn(f"[OllamaProvider]查询模型列表失败: {e}")
            return []


class OllamaEmbeddingProvider(BaseEmbeddingProvider):
    """Ollama Embedding 提供商（如 nomic-embed-text / bge-m3）"""

    def __init__(self, config: ProviderConfig, model: str):
        super().__init__(config, model)
        # chat 预设 api_url 常带 /v1 后缀，ollama SDK host 不带
        host = config.api_url.removesuffix("/v1").rstrip("/")
        self._client = Client(host=host)

    def embed(self, texts: list[str]) -> list[list[float]]:
        if not texts:
            return []
        resp = self._client.embed(model=self._model, input=texts)
        embeddings = resp.embeddings if hasattr(resp, "embeddings") else resp["embeddings"]
        vectors = [list(map(float, e)) for e in embeddings]
        if vectors and self._dimension is None:
            self._dimension = len(vectors[0])
        return vectors

    def is_available(self) -> bool:
        try:
            self.embed(["health check"])
            return True
        except Exception as e:
            log.warn(f"[OllamaEmbeddingProvider]不可用: {e}")
            return False
