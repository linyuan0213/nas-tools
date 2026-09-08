"""Web Push 订阅管理 Router — 浏览器 Service Worker 推送."""

from typing import Any

from fastapi import APIRouter, Depends
from pydantic import BaseModel

import log
from api.deps import require_any_permission
from app.services.web_push_service import WebPushService
from app.utils.response import success

router = APIRouter()


class PushSubscribeRequest(BaseModel):
    endpoint: str
    keys: dict[str, str]


class PushUnsubscribeRequest(BaseModel):
    endpoint: str


def _svc(ctx) -> WebPushService:
    return WebPushService()


@router.get("/push/vapid-public-key", summary="获取 VAPID 公钥（用于浏览器订阅）")
def vapid_public_key(user: Any = Depends(require_any_permission("agent:view", "site:view"))):
    return success(data={"public_key": WebPushService().get_public_key()})


@router.get("/push/status", summary="推送订阅状态")
def push_status(user: Any = Depends(require_any_permission("agent:view", "site:view"))):
    return success(data={"subscriptions": WebPushService().subscription_count()})


@router.post("/push/subscribe", summary="订阅浏览器推送")
def push_subscribe(
    req: PushSubscribeRequest,
    user: Any = Depends(require_any_permission("agent:view", "site:view")),
):
    keys = req.keys or {}
    log.info(f"[WebPush]subscribe endpoint={str(req.endpoint)[:60]} user={getattr(user, 'username', '')}")
    WebPushService().subscribe(
        endpoint=req.endpoint,
        p256dh=keys.get("p256dh", ""),
        auth=keys.get("auth", ""),
    )
    return success()


@router.post("/push/unsubscribe", summary="取消浏览器推送订阅")
def push_unsubscribe(
    req: PushUnsubscribeRequest,
    user: Any = Depends(require_any_permission("agent:view", "site:view")),
):
    log.info(f"[WebPush]unsubscribe endpoint={str(req.endpoint)[:60]} user={getattr(user, 'username', '')}")
    WebPushService().unsubscribe(endpoint=req.endpoint)
    return success()
