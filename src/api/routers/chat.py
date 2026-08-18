"""Agent 对话 Router — SSE 流式对话与会话管理"""

import json
import queue
import threading

from fastapi import APIRouter, Depends
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

import log
from api.deps import get_app_context, require_permission
from app.agent.config import normalize_reasoning_effort
from app.agent.providers.base import ReasoningConfig
from app.di.context import AppContext
from app.utils.response import fail, success

router = APIRouter()


class ChatRequest(BaseModel):
    question: str
    session_id: str = ""
    # 推理强度：low | high | max，空 = 使用配置默认
    reasoning_effort: str = ""
    # 关闭思考模式，None = 使用配置默认
    disable_thinking: bool | None = None


class ClearRequest(BaseModel):
    session_id: str = ""


class MemoryDeleteRequest(BaseModel):
    text: str


class ConfirmRequest(BaseModel):
    tool: str
    arguments: dict = {}
    session_id: str = ""


@router.post("/chat")
def agent_chat(
    req: ChatRequest,
    user=Depends(require_permission("agent:view")),
    ctx: AppContext = Depends(get_app_context),
):
    """SSE 流式对话：事件类型 tool_call / tool_result / answer / error"""
    if not req.question.strip():
        return fail(msg="问题不能为空")
    agent_service = ctx.agent_service
    if not agent_service.ready:
        return fail(msg="AI 服务未配置或未启用")
    session_id = req.session_id or f"web:{user.user_id}"
    user_id = str(user.user_id)

    reasoning = agent_service.reasoning_for()
    if req.reasoning_effort or req.disable_thinking is not None:
        effort = normalize_reasoning_effort(req.reasoning_effort, reasoning.effort)
        enabled = reasoning.enabled if req.disable_thinking is None else not req.disable_thinking
        reasoning = ReasoningConfig(effort=effort, enabled=enabled)

    event_queue: queue.Queue = queue.Queue()

    def _run():
        try:
            answer = agent_service.chat_agent.chat_with_tools(
                question=req.question,
                session_id=session_id,
                user_id=user_id,
                channel="web",
                on_event=lambda e: event_queue.put(e),
                user_permissions=list(user.permissions),
                on_token=lambda t: event_queue.put({"type": "token", "content": t}),
                reasoning=reasoning,
            )
            event_queue.put({"type": "answer", "content": answer})
        except Exception as e:
            log.error(f"[AgentChat]对话失败: {e}")
            event_queue.put({"type": "error", "content": str(e)})
        finally:
            event_queue.put(None)

    threading.Thread(target=_run, daemon=True).start()

    def _gen():
        while True:
            item = event_queue.get()
            if item is None:
                break
            yield f"data: {json.dumps(item, ensure_ascii=False)}\n\n"

    return StreamingResponse(_gen(), media_type="text/event-stream")


@router.post("/chat/confirm")
def agent_chat_confirm(
    req: ConfirmRequest,
    user=Depends(require_permission("agent:manage")),
    ctx: AppContext = Depends(get_app_context),
):
    """确认并执行危险操作（chat 流程中 need_confirm 后的批准入口）"""
    schema = ctx.tool_executor.get_schema(req.tool)
    if not schema or schema.get("level") != "dangerous":
        return fail(msg="仅支持确认危险操作工具")
    result = ctx.tool_executor.execute(
        req.tool,
        req.arguments,
        confirmed=True,
        session_id=req.session_id,
        user_id=str(user.user_id),
        user_permissions=list(user.permissions),
    )
    if result.success:
        return success(data=result.data)
    return fail(msg=result.error or "执行失败", data=result.data)


@router.get("/memory")
def agent_memory_list(
    user=Depends(require_permission("agent:view")),
    ctx: AppContext = Depends(get_app_context),
):
    """列出当前用户的长程语义记忆（偏好管理）"""
    semantic = ctx.semantic_memory
    if semantic is None:
        return fail(msg="长程语义记忆未启用")
    memories = semantic.list(str(user.user_id), limit=50)
    return success(data={"memories": memories})


@router.post("/memory/delete")
def agent_memory_delete(
    req: MemoryDeleteRequest,
    user=Depends(require_permission("agent:manage")),
    ctx: AppContext = Depends(get_app_context),
):
    """删除指定长程记忆"""
    semantic = ctx.semantic_memory
    if semantic is None:
        return fail(msg="长程语义记忆未启用")
    deleted = semantic.forget(str(user.user_id), req.text)
    return success(data={"deleted": deleted})


@router.post("/chat/clear")
def agent_chat_clear(
    req: ClearRequest,
    user=Depends(require_permission("agent:view")),
    ctx: AppContext = Depends(get_app_context),
):
    """清空会话记忆"""
    conversation_store = ctx.conversation_store
    if conversation_store is None:
        return fail(msg="记忆存储未启用")
    session_id = req.session_id or f"web:{user.user_id}"
    conversation_store.clear_session(session_id=session_id, user_id=str(user.user_id), channel="web")
    return success(data={"cleared": True})
