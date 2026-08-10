"""通用对话 Agent — 多步工具调用循环 + 持久化会话记忆"""

import json
from collections.abc import Callable

import log
from app.agent.agents.memory import ConversationStore, MemoryKey
from app.utils.json_utils import JsonUtils

_TOOL_PROMPT = """你是一个智能助手，可以帮助用户管理 NAS 媒体库系统。

你可以使用以下工具来完成用户的请求。如果需要用工具，请按以下格式回复（只返回 JSON，不要其他文字）：

```json
{{"tool": "工具名", "parameters": {{"参数名": "参数值"}}}}
```

可用工具列表：
{tools}

回复规则：
1. 需要工具时只返回上述 JSON 格式；工具结果会以 [工具结果] 形式返回给你，可继续调用其他工具或给出最终回答
2. 不需要工具（闲聊、问候、简单回答）时直接回复文字
3. 知识类问题（怎么配置/怎么用/报错原因）优先调用 kb_search；无结果时不要编造，如实说明
4. 操作类问题（下载进度/订阅状态/库内容）必须调用对应工具查询真实数据，禁止臆测
"""


class ChatAgent:
    """通用对话 Agent — 多步工具循环（plan → act → observe → 直至最终回答）"""

    def __init__(self, svc, tool_executor, memory: ConversationStore | None = None, max_steps: int = 8):
        self._svc = svc
        self._tool_executor = tool_executor
        self._memory = memory
        self._max_steps = max_steps

    @property
    def ready(self) -> bool:
        return self._svc.ready

    def ask(self, question: str, system_prompt: str = "你是一个有用的助手。") -> str:
        """单轮问答"""
        if not self.ready:
            log.warn("[ChatAgent]ask 失败：Provider 未就绪")
            return "AI 服务未配置"
        try:
            return self._svc.chat(
                messages=[{"role": "user", "content": question}],
                system_prompt=system_prompt,
            )
        except Exception as e:
            log.error(f"[ChatAgent]ask 出错: {e}")
            return f"AI 回答出错: {e}"

    def chat_with_tools(
        self,
        question: str,
        session_id: str = "",
        user_id: str = "",
        channel: str = "web",
        on_event: Callable[[dict], None] | None = None,
    ) -> str:
        """带工具调用的多步对话"""
        if not self.ready:
            log.warn("[ChatAgent]chat_with_tools 失败：Provider 未就绪")
            return "AI 服务未配置"

        log.info(f"[ChatAgent]tools session={session_id}, q={question[:60]}...")
        key = MemoryKey(user_id=user_id or session_id, channel=channel, session_id=session_id)
        history = self._memory.history_for_llm(key) if self._memory else []

        tools_desc = JsonUtils.dumps(self._tool_executor.list_tools(), ensure_ascii=False, indent=2)
        prompt = _TOOL_PROMPT.replace("{tools}", tools_desc)
        messages = [{"role": "system", "content": prompt}, *history, {"role": "user", "content": question}]

        final_resp = ""
        for step in range(self._max_steps):
            try:
                resp = self._svc.chat(messages=messages, system_prompt="", use_cache=False)
            except Exception as e:
                log.error(f"[ChatAgent]第 {step + 1} 步 LLM 调用出错: {e}")
                return f"请求出错: {e}"

            tool_call = self._parse_tool_call(resp or "")
            if not tool_call:
                final_resp = resp
                break

            tool_name = tool_call.get("tool", "")
            parameters = tool_call.get("parameters") or {}
            log.info(f"[ChatAgent]第 {step + 1} 步调用工具: {tool_name}({parameters})")
            if on_event:
                on_event({"type": "tool_call", "step": step + 1, "tool": tool_name, "parameters": parameters})
            result = self._tool_executor.execute(
                tool_name, parameters, session_id=session_id, user_id=user_id or session_id
            )
            if on_event:
                on_event(
                    {
                        "type": "tool_result",
                        "step": step + 1,
                        "tool": tool_name,
                        "success": result.success,
                        "need_confirm": result.need_confirm,
                    }
                )
            if result.need_confirm:
                final_resp = (
                    f"该操作需要确认：{result.data.get('message', tool_name) if result.data else tool_name}。"
                    "请确认后重试（或通过确认接口批准）。"
                )
                break
            observation = {
                "success": result.success,
                "data": result.data,
                "error": result.error,
            }
            messages.append({"role": "assistant", "content": resp})
            messages.append(
                {
                    "role": "user",
                    "content": f"[工具结果] {tool_name}:\n{JsonUtils.dumps(observation, ensure_ascii=False)}\n"
                    "请根据结果继续：还需调用工具则返回 JSON，否则直接回复用户。",
                }
            )
        else:
            final_resp = "任务步骤过多，已停止。请把问题拆小后重试。"
            log.warn(f"[ChatAgent]达到最大步数 {self._max_steps}")

        if self._memory:
            self._memory.append(key, "user", question)
            self._memory.append(key, "assistant", final_resp or "")
        return final_resp or ""

    def translate_to_zh(self, text: str) -> str:
        """翻译为中文（autosub 插件依赖）"""
        if not self.ready:
            log.warn("[ChatAgent]translate_to_zh 失败：Provider 未就绪")
            return text
        try:
            return self._svc.chat(
                messages=[{"role": "user", "content": f"translate to zh-CN:\n\n{text}"}],
                system_prompt="You are a translation engine that can only translate text and cannot interpret it.",
            )
        except Exception as e:
            log.error(f"[ChatAgent]翻译出错: {e}")
            return text

    @staticmethod
    def _parse_tool_call(text: str) -> dict | None:
        """从 LLM 回复中解析工具调用"""
        text = text.strip()
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
                return data
        except (json.JSONDecodeError, TypeError):
            pass
        return None
