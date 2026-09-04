"""OpenAI / OpenAI 兼容提供商"""

from typing import Any

from openai import APIStatusError, OpenAI

import log
from app.agent.providers.base import (
    BaseEmbeddingProvider,
    BaseProvider,
    ChatToolResponse,
    ProviderConfig,
    ReasoningConfig,
    ToolCall,
    map_reasoning_effort,
)
from app.utils.json_utils import JsonUtils


def _reasoning_rejected(e: APIStatusError) -> bool:
    """400 错误是否源于推理参数不支持（按错误消息判断，避免掩盖真实拒绝）"""
    body: Any = e.body or {}
    msg = ""
    if isinstance(body, dict):
        err = body.get("error")
        if isinstance(err, dict):
            msg = str(err.get("message", ""))
        elif err is not None:
            msg = str(err)
        else:
            msg = str(body.get("message", ""))
    else:
        msg = str(body)
    text = f"{e.message} {msg}".lower()
    return any(k in text for k in ("reasoning_effort", "reasoning", "thinking"))


class OpenAIProvider(BaseProvider):
    """OpenAI 兼容提供商 — 支持 OpenAI、Moonshot、DeepSeek 等"""

    def __init__(self, config: ProviderConfig):
        super().__init__(config)
        self._client = OpenAI(
            base_url=config.api_url,
            api_key=config.api_key,
            timeout=config.timeout,
        )
        # 已确认不支持推理参数的模型（剥离后重试成功时记录，避免每次请求双重往返）
        self._reasoning_unsupported: set[str] = set()

    def _apply_reasoning(self, kwargs: dict[str, Any], reasoning: ReasoningConfig | None) -> None:
        """OpenAI 兼容参数映射：启用时发 reasoning_effort，关闭思考时走 extra_body（不支持的 API 会忽略）"""
        if not reasoning:
            return
        if self._config.model in self._reasoning_unsupported:
            return
        if reasoning.enabled:
            kwargs["reasoning_effort"] = map_reasoning_effort(reasoning.effort)
        else:
            kwargs["extra_body"] = {"thinking": {"type": "disabled"}}

    def chat(
        self,
        messages: list[dict],
        system_prompt: str = "",
        temperature: float = 0.7,
        response_format: type | None = None,
        reasoning: ReasoningConfig | None = None,
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
        self._apply_reasoning(kwargs, reasoning)

        try:
            resp = self._create(kwargs)
            return resp.choices[0].message.content
        except Exception as e:
            # 不吞错：上抛以便 AgentService 故障转移链切换备用 Provider（否则空结果还会被缓存）
            err_msg = self._format_error(e)
            log.warn(f"[OpenAIProvider]请求失败: {err_msg}")
            raise

    def _create(self, kwargs: dict[str, Any]) -> Any:
        """发起补全请求；模型不支持推理参数时剥离 reasoning 后重试一次（并记忆该模型）"""
        try:
            return self._client.chat.completions.create(**kwargs)
        except APIStatusError as e:
            if (
                e.status_code == 400
                and _reasoning_rejected(e)
                and ("reasoning_effort" in kwargs or kwargs.get("extra_body"))
            ):
                stripped = {k: v for k, v in kwargs.items() if k not in ("reasoning_effort", "extra_body")}
                log.debug("[OpenAIProvider]模型不支持推理参数，剥离后重试")
                resp = self._client.chat.completions.create(**stripped)
                self._reasoning_unsupported.add(self._config.model)
                return resp
            raise

    def chat_with_tools(
        self,
        messages: list[dict],
        tools: list[dict],
        system_prompt: str = "",
        temperature: float = 0.7,
        reasoning: ReasoningConfig | None = None,
    ) -> ChatToolResponse:
        """原生 function calling（OpenAI 兼容接口：DeepSeek / DashScope / Ollama /v1 等）"""
        msgs, tool_specs = self._build_tool_request(messages, tools, system_prompt)
        kwargs: dict[str, Any] = {
            "model": self._config.model,
            "messages": msgs,
            "temperature": temperature,
            "tools": tool_specs,
        }
        self._apply_reasoning(kwargs, reasoning)
        try:
            resp = self._create(kwargs)
        except Exception as e:
            err_msg = self._format_error(e)
            log.warn(f"[OpenAIProvider]工具调用请求失败，回退 prompt 协议: {err_msg}")
            return super().chat_with_tools(messages, tools, system_prompt, temperature, reasoning)

        message: Any = resp.choices[0].message
        calls = []
        for tc in message.tool_calls or []:
            try:
                args = JsonUtils.loads(tc.function.arguments or "{}")
            except (ValueError, TypeError):
                args = {}
            calls.append(
                ToolCall(name=tc.function.name or "", arguments=args if isinstance(args, dict) else {}, id=tc.id or "")
            )
        reasoning_text = getattr(message, "reasoning_content", "") or ""
        return ChatToolResponse(content=message.content or "", tool_calls=calls, reasoning=reasoning_text, native=True)

    def chat_with_tools_stream(
        self,
        messages: list[dict],
        tools: list[dict],
        system_prompt: str = "",
        temperature: float = 0.7,
        on_token: Any = None,
        on_reasoning: Any = None,
        reasoning: ReasoningConfig | None = None,
    ) -> ChatToolResponse:
        """流式工具对话（OpenAI 兼容：DeepSeek / DashScope / Ollama /v1 等）"""
        msgs, tool_specs = self._build_tool_request(messages, tools, system_prompt)
        kwargs: dict[str, Any] = {
            "model": self._config.model,
            "messages": msgs,
            "temperature": temperature,
            "tools": tool_specs,
            "stream": True,
        }
        self._apply_reasoning(kwargs, reasoning)
        try:
            stream = self._create(kwargs)
        except Exception as e:
            err_msg = self._format_error(e)
            log.warn(f"[OpenAIProvider]流式请求失败，回退非流式: {err_msg}")
            return super().chat_with_tools_stream(
                messages, tools, system_prompt, temperature, on_token, on_reasoning, reasoning
            )

        content_parts: list[str] = []
        reasoning_parts: list[str] = []
        tool_entries: dict[int, dict[str, str]] = {}
        for chunk in stream:
            if not chunk.choices:
                continue
            delta = chunk.choices[0].delta
            if delta.content:
                content_parts.append(delta.content)
                if on_token:
                    on_token(delta.content)
            r = getattr(delta, "reasoning_content", None)
            if r:
                reasoning_parts.append(r)
                if on_reasoning:
                    on_reasoning(r)
            for tc in delta.tool_calls or []:
                entry = tool_entries.setdefault(tc.index, {"id": "", "name": "", "arguments": ""})
                if tc.id:
                    entry["id"] = tc.id
                if tc.function and tc.function.name:
                    entry["name"] = tc.function.name
                if tc.function and tc.function.arguments:
                    entry["arguments"] += tc.function.arguments
        calls = []
        for idx in sorted(tool_entries):
            entry = tool_entries[idx]
            try:
                args = JsonUtils.loads(entry["arguments"] or "{}")
            except (ValueError, TypeError):
                args = {}
            calls.append(ToolCall(name=entry["name"], arguments=args if isinstance(args, dict) else {}, id=entry["id"]))
        return ChatToolResponse(
            content="".join(content_parts), tool_calls=calls, reasoning="".join(reasoning_parts), native=True
        )

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
