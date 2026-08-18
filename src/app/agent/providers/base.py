"""LLM 提供商抽象基类"""

import json
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any

from app.utils.json_utils import JsonUtils

_TOOL_COMMON_RULES = """2. 不需要工具（闲聊、问候、简单回答）时直接回复文字
3. 知识类问题（怎么配置/怎么用/报错原因）优先调用 kb_search；无结果时不要编造，如实说明
4. 操作类问题（下载进度/订阅状态/库内容）必须调用对应工具查询真实数据，禁止臆测
5. 删除/修改类危险操作（删除订阅、删除下载任务等）不要预先向用户征求确认，直接调用对应工具；
   系统会自动弹出确认卡供用户批准
6. 任何写操作（添加订阅、下载、转移等）必须真实调用对应工具并收到成功结果后，才能声称操作成功；
   未调用工具时严禁声称"已成功"，应如实说明需要执行
"""

_TOOL_PROMPT = (
    """你是一个智能助手，可以帮助用户管理 NAS 媒体库系统。

你可以使用以下工具来完成用户的请求。如果需要用工具，请按以下格式回复（只返回 JSON，不要其他文字）：

```json
{{"tool": "工具名", "parameters": {{"参数名": "参数值"}}}}
```

可用工具列表：
{tools}

回复规则：
1. 需要工具时只返回上述 JSON 格式；工具结果会以 [工具结果] 形式返回给你，可继续调用其他工具或给出最终回答
"""
    + _TOOL_COMMON_RULES
)

TOOL_RULES_PROMPT = (
    """回复规则：
1. 需要工具时直接调用对应工具；工具结果会以 [工具结果] 形式返回，可继续调用其他工具或给出最终回答
"""
    + _TOOL_COMMON_RULES
)


@dataclass(frozen=True)
class ToolCall:
    """一次工具调用"""

    name: str
    arguments: dict
    id: str = ""


@dataclass
class ChatToolResponse:
    """带工具调用的对话响应；native=False 表示走 prompt-JSON 协议回退"""

    content: str = ""
    tool_calls: list[ToolCall] = field(default_factory=list)
    reasoning: str = ""
    native: bool = False

    @property
    def has_tool_calls(self) -> bool:
        return bool(self.tool_calls)


@dataclass
class ProviderConfig:
    """LLM 提供商配置"""

    name: str
    api_key: str
    api_url: str
    model: str
    proxy: str | None = None
    timeout: int = 60


@dataclass
class EmbeddingConfig:
    """Embedding 配置"""

    provider: str
    model: str
    api_key: str = ""
    api_url: str = ""
    proxy: str | None = None
    timeout: int = 60


@dataclass
class ReasoningConfig:
    """推理强度与思考模式配置（统一作用于对话 / 识别 / 意图 / 记忆等所有 LLM 调用）

    - effort: low | high | max（默认 high）
    - enabled: False = 关闭思考模式
    """

    effort: str = "high"
    enabled: bool = True


_EFFORT_MAP = {"low": "low", "high": "high", "max": "high"}


def map_reasoning_effort(effort: str, default: str = "high") -> str:
    """low/high/max → OpenAI 兼容 / Ollama 档位（max 归并为最高档 high）"""
    return _EFFORT_MAP.get(effort, default)


class BaseProvider(ABC):
    """LLM 提供商抽象基类"""

    def __init__(self, config: ProviderConfig):
        self._config = config

    @property
    def name(self) -> str:
        return self._config.name

    @abstractmethod
    def chat(
        self,
        messages: list[dict],
        system_prompt: str = "",
        temperature: float = 0.7,
        response_format: type | None = None,
        reasoning: ReasoningConfig | None = None,
    ) -> Any:
        """执行对话请求"""

    def _build_tool_request(
        self,
        messages: list[dict],
        tools: list[dict],
        system_prompt: str = "",
    ) -> tuple[list[dict], list[dict]]:
        """组装工具请求：system 提示词前置 + 工具 schema 列表（sync/stream 共用，避免重复）"""
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
        return msgs, tool_specs

    def chat_with_tools(
        self,
        messages: list[dict],
        tools: list[dict],
        system_prompt: str = "",
        temperature: float = 0.7,
        reasoning: ReasoningConfig | None = None,
    ) -> ChatToolResponse:
        """带工具调用的对话。

        默认实现 = prompt-JSON 协议（无原生工具调用能力的 provider 回退）；
        OpenAI 兼容 / Ollama 等 provider 可 override 为原生 function calling。
        """
        prompt = _TOOL_PROMPT.replace("{tools}", JsonUtils.dumps(tools, ensure_ascii=False, indent=2))
        content = self.chat(messages=messages, system_prompt=prompt, temperature=temperature, reasoning=reasoning)
        return self._parse_prompt_tool_response(content)

    @staticmethod
    def _parse_prompt_tool_response(content: str) -> ChatToolResponse:
        """解析 prompt-JSON 协议响应中的工具调用"""
        text = (content or "").strip()
        if "```json" in text:
            start = text.find("```json") + 7
            end = text.find("```", start)
            if end > start:
                text = text[start:end].strip()
        elif "```" in text:
            start = text.find("```") + 3
            end = text.find("```", start)
            if end > start:
                text = text[start:end].strip()
        try:
            data = JsonUtils.loads(text)
            if isinstance(data, dict) and "tool" in data and "parameters" in data:
                return ChatToolResponse(
                    content=content,
                    tool_calls=[ToolCall(name=str(data["tool"]), arguments=data.get("parameters") or {})],
                )
        except (json.JSONDecodeError, TypeError):
            pass
        return ChatToolResponse(content=content)

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
        """流式工具对话：content 逐 token 回调 on_token；返回完整 ChatToolResponse。

        默认实现 = 非流式降级（一次回调完整内容）；OpenAI 兼容 / Ollama 覆盖为真流式。
        """
        resp = self.chat_with_tools(messages, tools, system_prompt, temperature, reasoning)
        if on_token and resp.content:
            on_token(resp.content)
        if on_reasoning and resp.reasoning:
            on_reasoning(resp.reasoning)
        return resp

    @abstractmethod
    def is_available(self) -> bool:
        """检查提供商是否可用"""

    def list_models(self) -> list[str]:
        """查询可用模型列表（可选实现）"""
        return []


class BaseEmbeddingProvider(ABC):
    """Embedding 提供商抽象基类"""

    def __init__(self, config: ProviderConfig, model: str):
        self._config = config
        self._model = model
        self._dimension: int | None = None

    @property
    def name(self) -> str:
        return self._config.name

    @property
    def dimension(self) -> int:
        """向量维度，首次 embed 后确定并缓存"""
        if self._dimension is None:
            raise RuntimeError("dimension 未知：请先执行一次 embed")
        return self._dimension

    @abstractmethod
    def embed(self, texts: list[str]) -> list[list[float]]:
        """批量文本转向量"""

    def embed_query(self, text: str) -> list[float]:
        """单条查询转向量"""
        return self.embed([text])[0]

    @abstractmethod
    def is_available(self) -> bool:
        """检查提供商是否可用"""
