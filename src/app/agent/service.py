"""LLM Agent Service — 统一入口门面"""

from typing import Any

import log
from app.agent.agents.chat_agent import ChatAgent
from app.agent.agents.media_recognizer import MediaRecognizer
from app.agent.agents.search_intent import SearchIntentAgent
from app.agent.config import get_memory_config, get_provider
from app.agent.providers.base import ProviderConfig
from app.agent.providers.gemini import GeminiProvider
from app.agent.providers.ollama import OllamaProvider
from app.agent.providers.openai import OpenAIProvider
from app.core.settings import settings
from app.infrastructure.cache_system import lru_cache_with_ttl
from app.utils.json_utils import JsonUtils


class AgentService:
    """LLM Agent 服务门面 — 管理提供商连接、缓存、重试"""

    def __init__(self):
        self._media_recognizer: MediaRecognizer | None = None
        self._search_intent_agent: SearchIntentAgent | None = None
        self._chat_agent: ChatAgent | None = None
        self._provider: Any | None = None
        self._config: ProviderConfig | None = None
        self._enabled = False
        self._refresh_config()

    def init_chat_agent(self, tool_executor: Any, conversation_store: Any = None) -> None:
        """由 DI 在 ToolExecutor 构建后调用（显式一次性初始化，替代旧 set_tool_executor 后门）。"""
        self._chat_agent = ChatAgent(
            svc=self,
            tool_executor=tool_executor,
            memory=conversation_store,
            max_steps=get_memory_config()["max_steps"],
        )

    @property
    def media_recognizer(self) -> MediaRecognizer:
        if self._media_recognizer is None:
            self._media_recognizer = MediaRecognizer(svc=self)
        return self._media_recognizer

    @property
    def search_intent_agent(self) -> SearchIntentAgent:
        if self._search_intent_agent is None:
            self._search_intent_agent = SearchIntentAgent(svc=self)
        return self._search_intent_agent

    @property
    def chat_agent(self) -> ChatAgent:
        if self._chat_agent is None:
            raise RuntimeError("ChatAgent 未初始化（需 DI 调用 init_chat_agent）")
        return self._chat_agent

    @property
    def ready(self) -> bool:
        return self._enabled and self._provider is not None

    @property
    def provider_name(self) -> str:
        return self._config.name if self._config else ""

    def _refresh_config(self) -> None:
        """刷新配置（支持热重载）"""
        cfg = settings.get("agent") or {}
        self._enabled = bool(cfg.get("enabled"))
        if not self._enabled:
            if self._provider is not None:
                log.info("[AgentService]Agent 已禁用，释放 Provider")
            self._provider = None
            return
        self._config = get_provider()  # type: ignore[assignment]
        if self._config:
            self._provider = self._create_provider(self._config)
            log.info(f"[AgentService]Provider 就绪: {self._config.name} / {self._config.model}")
        else:
            log.warn("[AgentService]Agent 已启用但未找到有效 Provider 配置")
            self._provider = None

    @staticmethod
    def _create_provider(config: ProviderConfig):
        """根据配置创建提供商实例"""
        if config.name == "ollama":
            return OllamaProvider(config)
        if config.name == "gemini":
            return GeminiProvider(config)
        return OpenAIProvider(config)

    def chat(
        self,
        messages: list[dict],
        system_prompt: str = "",
        temperature: float = 0.7,
        response_format: type | None = None,
        use_cache: bool = True,
    ) -> str:
        """通用对话请求"""
        if not self.ready:
            log.warn("[AgentService]chat 调用失败：Provider 未就绪")
            raise RuntimeError("LLM service not configured")
        if not self._provider:
            raise RuntimeError("LLM service not configured")

        if use_cache and not response_format:
            return self._cached_chat(messages, system_prompt, temperature)

        return self._provider.chat(messages, system_prompt, temperature, response_format)

    @lru_cache_with_ttl(ttl=300, maxsize=256)
    def _cached_chat(self, messages: tuple, system_prompt: str, temperature: float) -> str:
        """带缓存的对话（messages 转为 tuple 使其可 hash）"""
        if not self._provider:
            raise RuntimeError("LLM service not configured")
        log.info("[AgentService]缓存未命中，调用 Provider chat")
        return self._provider.chat(list(messages), system_prompt, temperature)

    def chat_tool_calls(
        self,
        messages: list[dict],
        tools: list[dict],
        system_prompt: str = "",
        temperature: float = 0.7,
    ) -> Any:
        """带工具调用的 LLM 对话（原生 function calling / prompt 协议回退；结果不可缓存）"""
        if not self.ready:
            raise RuntimeError("LLM service not configured")
        if not self._provider:
            raise RuntimeError("LLM service not configured")
        return self._provider.chat_with_tools(messages, tools, system_prompt, temperature)

    def structured_chat(
        self,
        messages: list[dict],
        system_prompt: str = "",
        response_model: type | None = None,
        temperature: float = 0.3,
    ) -> Any:
        """结构化输出对话（返回 pydantic 模型实例）"""
        if not self.ready:
            log.warn("[AgentService]structured_chat 调用失败：Provider 未就绪")
            raise RuntimeError("LLM service not configured")
        if not self._provider:
            raise RuntimeError("LLM service not configured")

        prompt = (
            f"{system_prompt}\n\n"
            f"请严格按照以下 JSON Schema 返回结果，不要包含任何其他内容：\n"
            f"{response_model.model_json_schema() if response_model else ''}"
        )
        content = self._provider.chat(messages, prompt, temperature)
        try:
            data = JsonUtils.loads(content)
            if response_model:
                result = response_model.model_validate(data)
                log.info(f"[AgentService]structured_chat 解析成功: {response_model.__name__}")
                return result
            return data
        except Exception as e:
            log.warn(f"[AgentService]结构化解析失败: {e}, content={content[:200]}")
            return None

    def list_models(self) -> list[str]:
        """查询当前提供商支持的模型列表"""
        if not self.ready:
            return []
        if not self._provider:
            return []
        try:
            models = self._provider.list_models()
            log.info(f"[AgentService]查询到 {len(models)} 个模型")
            return models
        except Exception as e:
            log.warn(f"[AgentService]查询模型列表失败: {e}")
            return []

    def chat_with_tools(self, question: str, session_id: str = "") -> str:
        """ChatPort 实现 — 委托 ChatAgent（惰性解析，保证 tool_executor 已注入）"""
        return self.chat_agent.chat_with_tools(question=question, session_id=session_id)

    def is_available(self) -> bool:
        """检查当前提供商是否可用"""
        return self.ready and self._provider is not None and self._provider.is_available()
