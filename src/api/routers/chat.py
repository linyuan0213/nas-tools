"""Agent 对话 Router — SSE 流式对话与会话管理"""

import json
import queue
import threading

from fastapi import APIRouter, Depends
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

import log
from api.deps import get_app_context, require_permission
from app.di.context import AppContext
from app.utils.response import fail, success

router = APIRouter()


class ChatRequest(BaseModel):
    question: str
    session_id: str = ""


class ClearRequest(BaseModel):
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

    event_queue: queue.Queue = queue.Queue()

    def _run():
        try:
            answer = agent_service.chat_agent.chat_with_tools(
                question=req.question,
                session_id=session_id,
                user_id=user_id,
                channel="web",
                on_event=lambda e: event_queue.put(e),
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
