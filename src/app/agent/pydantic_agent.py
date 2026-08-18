"""基于 pydantic-ai 的多步工具对话引擎（对齐 ADR-020：复用 pydantic-ai 原生多步工具调用）

将项目自研 ChatAgent 的循环引擎替换为 pydantic-ai，同时保留项目能力：
- 模型层：pydantic-ai `NexusModel` 适配器，内部复用项目 AgentService 的 provider 链/故障转移/缓存
- 工具层：ToolExecutor 工具包装为 pydantic-ai Tool（平铺 JSON schema），RBAC/危险确认/幂等在工具内处理
- 会话/记忆：ConversationStore 持久化 user/assistant 消息与工具轨迹
- checkpoint：每次运行把 pydantic-ai 消息历史持久化，支持中断后续跑
- 异常回溯：工具/模型异常带 step 上下文写入轨迹
"""

from __future__ import annotations

import asyncio
import re
import time
import uuid
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field, TypeAdapter, create_model
from pydantic_ai import Agent
from pydantic_ai.messages import (
    ModelMessage,
    ModelRequest,
    ModelResponse,
    RetryPromptPart,
    SystemPromptPart,
    TextPart,
    ToolCallPart,
    ToolReturnPart,
    UserPromptPart,
)
from pydantic_ai.models import Model, ModelRequestParameters
from pydantic_ai.settings import ModelSettings
from pydantic_ai.tools import Tool

import log
from app.agent.agents.memory import ConversationStore, MemoryKey, SemanticMemory, extract_facts
from app.agent.config import get_provider
from app.agent.providers.base import TOOL_RULES_PROMPT
from app.agent.sanitize import sanitize
from app.core.settings import settings
from app.utils.json_utils import JsonUtils

_CONFIRM_MARKER = "__need_confirm__"
_CHECKPOINT_MAX = 4000  # checkpoint 消息历史长度上限
# checkpoint JSON → pydantic-ai 消息重建（带 kind 判别）
_CHECKPOINT_TA = TypeAdapter(list[ModelMessage])


def _part_content(content: Any) -> str:
    """UserPromptPart.content 可能是 str 或 list[parts]，统一转文本"""
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts = []
        for p in content:
            if isinstance(p, str):
                parts.append(p)
            else:
                parts.append(getattr(p, "content", "") or "")
        return "\n".join(parts)
    return str(content or "")


class NexusModel(Model):
    """pydantic-ai Model 适配器 — 内部调用项目 AgentService（复用 provider 故障转移链）"""

    def __init__(
        self,
        svc,
        tools: list[dict],
        on_token: Callable[[str], None] | None = None,
        on_reasoning: Callable[[str], None] | None = None,
        on_tool_call: Callable[[str, dict, str], None] | None = None,
    ):
        self._svc = svc
        self._tools = tools
        self.on_token = on_token
        self.on_reasoning = on_reasoning
        self.on_tool_call = on_tool_call
        self._call_no = 0

    @property
    def model_name(self) -> str:
        return "nexus-media"

    @property
    def system(self) -> str:
        return "nexus-media"

    async def request(
        self,
        messages: list[ModelRequest | ModelResponse],
        model_settings: ModelSettings | None,
        model_request_parameters: ModelRequestParameters,
    ) -> ModelResponse:
        project_messages = self._to_project_messages(messages)
        self._call_no += 1
        resp = await asyncio.to_thread(
            self._svc.chat_tool_calls,
            project_messages,
            self._tools,
            TOOL_RULES_PROMPT,
            0.7,
            self.on_token,
            # 仅第一步的推理实时透传（后续步骤不重复展示）
            self.on_reasoning if self._call_no == 1 else None,
        )
        parts: list = []
        if resp.content:
            parts.append(TextPart(content=resp.content))
        for tc in getattr(resp, "tool_calls", None) or []:
            call_id = tc.id or uuid.uuid4().hex
            parts.append(ToolCallPart(tool_name=tc.name, args=tc.arguments, tool_call_id=call_id))
            if self.on_tool_call:
                self.on_tool_call(tc.name, tc.arguments, call_id)
        return ModelResponse(parts=parts)

    @staticmethod
    def _to_project_messages(messages: list[ModelRequest | ModelResponse]) -> list[dict]:
        """pydantic-ai 消息 → 项目 provider 消息格式（OpenAI 风格）"""
        out: list[dict] = []
        for msg in messages:
            if isinstance(msg, ModelRequest):
                for part in msg.parts:
                    if isinstance(part, SystemPromptPart):
                        out.append({"role": "system", "content": part.content})
                    elif isinstance(part, UserPromptPart):
                        out.append({"role": "user", "content": _part_content(part.content)})
                    elif isinstance(part, ToolReturnPart):
                        content = part.content if isinstance(part.content, str) else JsonUtils.dumps(part.content)
                        out.append({"role": "tool", "tool_call_id": part.tool_call_id, "content": content})
                    elif isinstance(part, RetryPromptPart):
                        out.append({"role": "user", "content": part.content})
            elif isinstance(msg, ModelResponse):
                text = "".join(p.content for p in msg.parts if isinstance(p, TextPart))
                calls = [
                    {
                        "id": p.tool_call_id or uuid.uuid4().hex,
                        "type": "function",
                        "function": {"name": p.tool_name, "arguments": JsonUtils.dumps(p.args)},
                    }
                    for p in msg.parts
                    if isinstance(p, ToolCallPart)
                ]
                if calls:
                    out.append({"role": "assistant", "content": text, "tool_calls": calls})
                elif text:
                    out.append({"role": "assistant", "content": text})
        return out


def _schema_field(props: dict) -> tuple[Any, Any]:
    """把工具 JSON schema 的属性描述转成 create_model 的字段定义（宽松类型 + description）"""
    ftype = props.get("type", "string")
    t: Any = str
    if ftype == "integer":
        t = int
    elif ftype == "number":
        t = float
    elif ftype == "boolean":
        t = bool
    elif ftype == "array":
        t = list
    elif ftype == "object":
        t = dict
    return (t, Field(default=None, description=props.get("description", "")))


class PydanticChatAgent:
    """pydantic-ai 多步工具对话引擎（对外方法与 ChatAgent 一致）"""

    def __init__(
        self,
        svc,
        tool_executor,
        memory: ConversationStore | None = None,
        max_steps: int = 8,
        long_term: SemanticMemory | None = None,
        extract_memory: bool = True,
    ):
        self._svc = svc
        self._tool_executor = tool_executor
        self._memory = memory
        self._max_steps = max_steps
        self._long_term = long_term
        self._extract_memory = extract_memory
        # 有界执行器：记忆抽取走小线程池（2 workers），避免阻塞返回
        self._memory_executor = ThreadPoolExecutor(max_workers=2, thread_name_prefix="agent-memory")
        # 按用户合并：同一用户仅保留一个待抽取任务，避免慢 LLM 抽取积压
        self._pending_extractions: set[str] = set()

    # 一次性操作动作：不作为稳定偏好抽取（订阅/下载/搜索等是即时指令，非长期偏好）
    _ACTION_INTENT = (
        "删除",
        "忘掉",
        "忘记",
        "取消",
        "清除",
        "remove",
        "删掉",
        "订阅",
        "取消订阅",
        "下载",
        "搜索",
        "查询",
        "查一下",
        "帮我订阅",
        "追更",
    )

    @property
    def ready(self) -> bool:
        return self._svc.ready

    def ask(self, question: str, system_prompt: str = "你是一个有用的助手。") -> str:
        """单轮问答（直连项目 provider）"""
        if not self.ready:
            log.warn("[PydanticAgent]ask 失败：Provider 未就绪")
            return "AI 服务未配置"
        try:
            return self._svc.chat(
                messages=[{"role": "user", "content": question}],
                system_prompt=system_prompt,
            )
        except Exception as e:
            log.error(f"[PydanticAgent]ask 出错: {e}")
            return f"AI 回答出错: {e}"

    def translate_to_zh(self, text: str) -> str:
        """翻译为中文（autosub 插件依赖）"""
        if not self.ready:
            log.warn("[PydanticAgent]translate_to_zh 失败：Provider 未就绪")
            return text
        try:
            return self._svc.chat(
                messages=[{"role": "user", "content": f"translate to zh-CN:\n\n{text}"}],
                system_prompt="You are a translation engine that can only translate text and cannot interpret it.",
            )
        except Exception as e:
            log.error(f"[PydanticAgent]翻译出错: {e}")
            return text

    # ------------------------------------------------------------------ 工具包装

    def _make_tool(self, schema: dict, session_id: str, user_id: str, user_permissions: list[str] | None) -> Tool:
        name = schema["name"]
        params_schema = schema.get("parameters") or {}
        props = params_schema.get("properties") or {}
        if props:
            fields = {k: _schema_field(v) for k, v in props.items()}
            param_model = create_model(f"{name}Params", **fields)  # type: ignore[arg-type, call-overload]
        else:

            class param_model(BaseModel):  # type: ignore[no-redef]
                pass

        async def _run(args):  # type: ignore[no-untyped-def]
            raw = args.model_dump() if hasattr(args, "model_dump") else {}
            arguments = {k: v for k, v in raw.items() if v is not None}
            log.info(sanitize(f"[PydanticAgent]调用工具: {name}({arguments})"))
            result = self._tool_executor.execute(
                name,
                arguments,
                confirmed=bool(arguments.get("confirmed")),
                session_id=session_id,
                user_id=user_id,
                user_permissions=user_permissions,
            )
            payload: dict[str, Any] = {
                "success": result.success,
                "data": result.data,
                "error": result.error,
                "need_confirm": result.need_confirm,
            }
            if result.need_confirm:
                payload[_CONFIRM_MARKER] = True
                payload["message"] = result.data
            elif self._memory:
                note = JsonUtils.dumps(result.data, ensure_ascii=False) if result.data else (result.error or "")
                self._memory.append_tool_trace(
                    MemoryKey(user_id=user_id or session_id, channel="web", session_id=session_id),
                    name,
                    arguments,
                    result.success,
                    note[:500],
                )
            return JsonUtils.dumps(payload, ensure_ascii=False)

        # 手工注解：直接用模型对象（闭包变量无法被 get_type_hints 按名解析）
        _run.__annotations__ = {"args": param_model, "return": str}
        _run.__name__ = name

        return Tool(_run, name=name, description=schema.get("description", name))

    def _build_agent(
        self,
        session_id: str,
        user_id: str,
        user_permissions: list[str] | None,
        on_token: Callable[[str], None] | None = None,
    ) -> Agent:
        self._on_token = on_token
        if not get_provider():
            raise RuntimeError("Agent Provider 未配置")
        tools_schema = self._tool_executor.list_tools()
        model = NexusModel(
            self._svc,
            tools_schema,
            on_token=self._on_token,
            on_reasoning=self._on_reasoning,
            on_tool_call=self._on_tool_call,
        )
        tools = [self._make_tool(s, session_id, user_id, user_permissions) for s in tools_schema]
        return Agent(model=model, tools=tools, system_prompt=TOOL_RULES_PROMPT)

    # ------------------------------------------------------------------ 对话

    def chat_with_tools(
        self,
        question: str,
        session_id: str = "",
        user_id: str = "",
        channel: str = "web",
        on_event: Callable[[dict], None] | None = None,
        user_permissions: list[str] | None = None,
        on_token: Callable[[str], None] | None = None,
    ) -> str:
        """带工具调用的多步对话（事件契约与自研 ChatAgent 一致）"""
        if not self.ready:
            log.warn("[PydanticAgent]chat_with_tools 失败：Provider 未就绪")
            return "AI 服务未配置"
        log.info(sanitize(f"[PydanticAgent]tools session={session_id}, q={question[:60]}..."))
        key = MemoryKey(user_id=user_id or session_id, channel=channel, session_id=session_id)

        reasoning_parts: list[str] = []
        self._reasoning_parts = reasoning_parts

        def _collect_reasoning(text: str) -> None:
            reasoning_parts.append(text)
            # 推理文本逐段实时发出（仅第一步模型调用透传，先于回答 token 流）
            if on_event:
                on_event({"type": "reasoning", "content": text})

        tool_call_count: list[int] = [0]
        tool_call_steps: dict[str, int] = {}

        def _collect_tool_call(tool: str, arguments: dict, call_id: str = "") -> None:
            # 模型决定调用工具时实时发出，先于回答 token 流；记录 id→step 供结果配对
            if not on_event:
                return
            tool_call_count[0] += 1
            step = tool_call_count[0]
            if call_id:
                tool_call_steps[call_id] = step
            on_event(
                {
                    "type": "tool_call",
                    "step": step,
                    "tool": tool,
                    "parameters": arguments,
                }
            )

        self._on_reasoning = _collect_reasoning
        self._on_tool_call = _collect_tool_call

        instructions = ""
        if self._long_term:
            try:
                memories = self._long_term.search(user_id or session_id, question)
                if memories:
                    instructions = f"用户长期偏好：{'；'.join(memories[:5])}"
            except Exception as e:
                log.warn(f"[PydanticAgent]长程记忆注入失败: {e}")

        try:
            agent = self._build_agent(session_id, user_id, user_permissions, on_token=on_token)
            # 恢复会话历史：多轮对话上下文（checkpoint 持久化的 pydantic-ai 消息）
            message_history = self._load_checkpoint(session_id, user_id)
            result = asyncio.run(
                agent.run(
                    question,
                    instructions=instructions or None,
                    message_history=message_history or None,
                )
            )
        except Exception as e:
            log.error(f"[PydanticAgent]运行出错: {e}")
            return f"请求出错: {e}"

        # 从消息历史重建事件 + 检测确认需求（tool_call 已在模型调用时实时发出，此处仅补 tool_result）
        need_confirm = None
        final_resp = ""
        for msg in result.all_messages():
            for part in getattr(msg, "parts", []):
                if isinstance(part, ToolReturnPart):
                    _result_success = True
                    try:
                        content = part.content if isinstance(part.content, str) else JsonUtils.dumps(part.content)
                        data = JsonUtils.loads(content) if isinstance(content, str) else None
                        if data and data.get(_CONFIRM_MARKER):
                            need_confirm = {
                                "tool": part.tool_name,
                                "message": (data.get("message") or {}).get("message", ""),
                            }
                        if isinstance(data, dict):
                            _result_success = bool(data.get("success", True))
                    except Exception as e:
                        log.debug(f"[PydanticAgent]工具返回解析失败: {e}")
                    if on_event:
                        # 按实时发出的 tool_call_id 反查 step，保证同名工具多次调用时结果配对正确
                        on_event(
                            {
                                "type": "tool_result",
                                "step": tool_call_steps.get(part.tool_call_id, 0),
                                "tool": part.tool_name,
                                "success": _result_success,
                            }
                        )
                elif isinstance(part, TextPart):
                    final_resp = part.content or ""

        # 危险操作需确认：发出确认卡，返回空（由前端确认后重跑）
        if need_confirm:
            if on_event:
                on_event({"type": "confirm_required", **need_confirm})
            final_resp = ""

        # 持久化会话
        if self._memory:
            self._memory.append(key, "user", question)
            if final_resp:
                self._memory.append(key, "assistant", final_resp)

        # checkpoint：持久化 pydantic-ai 消息历史（断点续跑/会话恢复）
        if not need_confirm:
            self._checkpoint(session_id, user_id, result.all_messages())

        # 异步抽取偏好记忆（不阻塞返回，同一用户仅一个待处理任务防积压）
        if self._long_term and self._extract_memory and final_resp:
            uid = user_id or session_id or "anon"
            if uid not in self._pending_extractions:
                self._pending_extractions.add(uid)
                self._memory_executor.submit(self._extract_user_memories, uid, question, final_resp)

        return final_resp or ""

    def _extract_user_memories(self, user_id: str, question: str, answer: str) -> None:
        """会话结束抽取偏好事实（不阻塞返回）"""
        try:
            if not question or not answer:
                return
            if any(k in question.lower() for k in self._ACTION_INTENT):
                return
            facts = extract_facts(
                self._svc,
                [{"role": "user", "content": question}, {"role": "assistant", "content": answer}],
            )
            for fact in facts:
                if self._long_term:
                    self._long_term.add_memory(user_id, fact)
        except Exception as e:
            log.warn(f"[PydanticAgent]记忆抽取失败: {e}")
        finally:
            self._pending_extractions.discard(user_id)

    # ------------------------------------------------------------------ checkpoint

    def _load_checkpoint(self, session_id: str, user_id: str) -> list[ModelMessage]:
        """加载会话历史（checkpoint 持久化的 pydantic-ai 消息），恢复多轮对话上下文.

        修复：agent.run 之前不加载历史导致每次都是全新会话，"可以/继续"等指代上文的话无法理解。
        """
        try:
            cp_dir = Path(settings.data_path) / "agent_checkpoints"
            safe_user = re.sub(r"[^\w.:-]", "_", user_id or session_id or "anon")
            safe_session = re.sub(r"[^\w.:-]", "_", session_id or "default")
            path = cp_dir / f"{safe_user}_{safe_session}.json"
            if not path.exists():
                return []
            data = JsonUtils.loads(path.read_text(encoding="utf-8"))
            messages = data.get("messages") or []
            if not messages:
                return []
            restored = _CHECKPOINT_TA.validate_python(messages)
            log.info(f"[PydanticAgent]恢复会话上下文 {len(restored)} 条消息")
            return restored
        except Exception as e:  # noqa: BLE001
            log.warn(f"[PydanticAgent]checkpoint 加载失败（忽略，按新会话处理）: {e}")
            return []

    def _checkpoint(self, session_id: str, user_id: str, messages: list) -> None:
        """持久化 pydantic-ai 消息历史（会话恢复/断点续跑的输入快照）"""
        try:
            cp_dir = Path(settings.data_path) / "agent_checkpoints"
            cp_dir.mkdir(parents=True, exist_ok=True)
            safe_user = re.sub(r"[^\w.:-]", "_", user_id or session_id or "anon")
            safe_session = re.sub(r"[^\w.:-]", "_", session_id or "default")
            path = cp_dir / f"{safe_user}_{safe_session}.json"
            blob = [m.model_dump(mode="json") if hasattr(m, "model_dump") else m for m in messages]
            path.write_text(
                JsonUtils.dumps(
                    {"updated": time.time(), "messages": blob[-_CHECKPOINT_MAX:]},
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )
        except Exception as e:
            log.warn(f"[PydanticAgent]checkpoint 写入失败: {e}")
