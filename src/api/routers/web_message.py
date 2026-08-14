"""内置消息交互 Router — Web 入站命令 + SSE 消息流

- POST /message/interact：WEB 入站命令（订阅/下载/搜索/插件命令），与第三方渠道同一套处理逻辑
- GET /message/stream：SSE 消息流（命令回复 + 事件通知），游标增量推送
"""

import asyncio
import json
import time
from typing import Any

from fastapi import APIRouter, Depends
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

import log
from api.deps import get_app_context, require_permission
from app.agent.agents.memory import MemoryKey
from app.di.context import AppContext
from app.domain.enums import SearchType
from app.message.web_store import WebMessageStore
from app.services.message_handler_factory import get_message_command_handler
from app.utils.response import fail, success

router = APIRouter()


class InteractRequest(BaseModel):
    text: str


class MarkReadRequest(BaseModel):
    ids: list[int] | None = None


@router.post("/message/interact")
def message_interact(
    req: InteractRequest,
    user: Any = Depends(require_permission("agent:view")),
    ctx: AppContext = Depends(get_app_context),
):
    """内置消息页命令入口：与 TG/WX 渠道共用 MessageCommandHandler"""
    text = req.text.strip()
    if not text:
        return fail(msg="内容不能为空")
    try:
        handler = get_message_command_handler(ctx, ctx.message)
        handler.handle_message_job(
            msg=text,
            in_from=SearchType.WEB,
            user_id=str(user.user_id),
            user_permissions=list(user.permissions),
        )
    except Exception as e:
        log.error(f"[WebMessage]命令处理失败: {e}")
        return fail(msg=f"命令处理失败: {e}")
    return success(data={"accepted": True})


@router.get("/conversation")
def conversation(
    session_id: str = "",
    user: Any = Depends(require_permission("agent:view")),
    ctx: AppContext = Depends(get_app_context),
):
    """返回持久化的对话历史（user/assistant），供前端刷新后恢复"""
    store = ctx.conversation_store
    if store is None:
        return fail(msg="记忆存储未启用")
    sid = session_id or f"web:{user.user_id}"
    key = MemoryKey(user_id=str(user.user_id), channel="web", session_id=sid)
    return success(data={"messages": store.chat_history(key)})


@router.get("/message/history")
def message_history(
    limit: int = 50,
    user: Any = Depends(require_permission("agent:view")),
):
    """最近通知历史（刷新后恢复显示；全局通知 + 本人消息）"""
    store = WebMessageStore.instance()
    items = store.history(str(user.user_id), limit=max(1, min(limit, 200)))
    return success(data={"messages": items})


@router.get("/message/unread-count")
def message_unread_count(
    user: Any = Depends(require_permission("agent:view")),
):
    """当前用户未读消息数（通知栏红点徽标）"""
    store = WebMessageStore.instance()
    return success(data={"unread": store.unread_count(str(user.user_id))})


@router.post("/message/read")
def message_mark_read(
    req: MarkReadRequest,
    user: Any = Depends(require_permission("agent:view")),
):
    """标记已读（ids 为空则全部已读），供通知去重与徽标清零"""
    store = WebMessageStore.instance()
    count = store.mark_read(str(user.user_id), req.ids)
    return success(data={"marked": count})


@router.get("/message/stream")
def message_stream(
    cursor: int = 0,
    user: Any = Depends(require_permission("agent:view")),
):
    """SSE 消息流：游标之后的消息增量推送（按当前用户过滤）+ 心跳保活"""
    store = WebMessageStore.instance()
    current_user_id = str(user.user_id)

    async def _gen():
        current = cursor
        last_heartbeat = time.time()
        while True:
            items = store.after(current, user_id=current_user_id)
            for item in items:
                current = max(current, item["cursor"])
                yield f"data: {json.dumps(item, ensure_ascii=False)}\n\n"
            now = time.time()
            if now - last_heartbeat >= 25:
                last_heartbeat = now
                yield ": heartbeat\n\n"
            # async 睡眠让出事件循环，避免每连接占用线程池 worker
            await asyncio.sleep(1.5)

    return StreamingResponse(_gen(), media_type="text/event-stream")
