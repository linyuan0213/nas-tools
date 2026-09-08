"""Web Push 服务：VAPID 密钥管理 + 订阅管理 + 消息推送."""

import base64
import json
import os

from cryptography.hazmat.primitives import serialization
from py_vapid import Vapid
from pywebpush import WebPushException, webpush

import log
from app.core.settings import settings
from app.db.repositories.push_subscription_repo_adapter import PushSubscriptionRepositoryAdapter
from app.db.repositories.system_dict_repo_adapter import SystemDictRepositoryAdapter

_VAPID_TYPE = "WEB_PUSH_VAPID"
# Apple 校验 VAPID subject：@localhost / .local 域名返回 BadJwtToken（web-push-libs/web-push#947）。
# 联系邮箱来自配置 app.push_contact（或环境变量 PUSH_VAPID_CONTACT），
# 需用可公开解析的真实域名；以下仅作兜底
_DEFAULT_PUSH_CONTACT = "mailto:noreply@example.com"


def _push_contact_email() -> str:
    """VAPID 联系邮箱：环境变量 > app.push_contact > app.domain 推导 > 兜底."""
    env = os.environ.get("PUSH_VAPID_CONTACT", "")
    if env:
        return env
    try:
        cfg = settings.get("app") or {}
        val = cfg.get("push_contact", "")
        if val:
            return val
        # 外网访问地址 app.domain 推导（Apple 要求真实可解析域名）
        domain = str(cfg.get("domain", "") or "").strip()
        if domain:
            host = domain.split("://")[-1].split("/")[0].split(":")[0].lower()
            if host and host not in ("localhost",) and not host.endswith(".local"):
                return f"mailto:noreply@{host}"
    except Exception as _e:  # noqa: BLE001
        log.debug(f"[WebPush]读取配置失败: {str(_e)[:80]}")
    return _DEFAULT_PUSH_CONTACT


class WebPushService:
    """浏览器 Web Push（Service Worker 推送，移动端/后台可达）."""

    def __init__(self):
        self._sub_repo = PushSubscriptionRepositoryAdapter()
        self._sys_repo = SystemDictRepositoryAdapter()

    # ---- VAPID 密钥 -----------------------------------------------------------

    def _vapid_keys(self) -> tuple[str, str]:
        """获取或首次生成 VAPID 密钥对（私钥 PEM + 公钥 PEM）并持久化."""
        private = self._sys_repo.get_by_type_key(_VAPID_TYPE, "private_key")
        public = self._sys_repo.get_by_type_key(_VAPID_TYPE, "public_key")
        if private and public:
            return private.value, public.value
        vapid = Vapid()
        vapid.generate_keys()
        private_pem = vapid.private_pem().decode()
        public_pem = vapid.public_pem().decode()
        self._sys_repo.set(_VAPID_TYPE, "private_key", private_pem, note="VAPID 私钥(PEM)")
        self._sys_repo.set(_VAPID_TYPE, "public_key", public_pem, note="VAPID 公钥(PEM)")
        log.info("[WebPush]首次生成 VAPID 密钥对")
        return private_pem, public_pem

    def get_public_key(self) -> str:
        """供浏览器 pushManager.subscribe 的 VAPID 公钥（URL-safe base64 无填充）."""
        _, public_pem = self._vapid_keys()
        pub = serialization.load_pem_public_key(public_pem.encode())
        raw = pub.public_bytes(
            encoding=serialization.Encoding.X962,
            format=serialization.PublicFormat.UncompressedPoint,
        )
        return base64.urlsafe_b64encode(raw).decode().rstrip("=")

    # ---- 订阅管理 -------------------------------------------------------------

    def subscribe(self, endpoint: str, p256dh: str, auth: str, user_id: str = "") -> None:
        self._sub_repo.upsert(endpoint=endpoint, p256dh=p256dh, auth=auth, user_id=user_id)

    def unsubscribe(self, endpoint: str) -> None:
        self._sub_repo.delete_by_endpoint(endpoint)

    def subscription_count(self) -> int:
        return len(self._sub_repo.list_all())

    # ---- 推送 ------------------------------------------------------------------

    def send_push(self, title: str, body: str, url: str = "/") -> int:
        """向全部订阅端点推送一条通知，返回成功数；过期端点自动清理."""
        subs = self._sub_repo.list_all()
        if not subs:
            return 0
        private_pem, _ = self._vapid_keys()
        # pywebpush 需 Vapid 实例（直接传 PEM 字符串会触发 "Could not deserialize key data"）
        try:
            vapid = Vapid.from_pem(private_pem.encode())
        except Exception as e:  # noqa: BLE001
            log.warn(f"[WebPush]VAPID 私钥解析失败: {str(e)[:120]}")
            return 0
        payload = json.dumps({"title": title, "body": body, "url": url}, ensure_ascii=False)
        sent = 0
        stale: list[str] = []
        for sub in subs:
            try:
                webpush(
                    subscription_info={
                        "endpoint": sub.endpoint,
                        "keys": {"p256dh": sub.p256dh, "auth": sub.auth},
                    },
                    data=payload,
                    vapid_private_key=vapid,
                    vapid_claims={"sub": _push_contact_email()},
                    ttl=3600,
                )
                sent += 1
            except WebPushException as e:
                status = getattr(e.response, "status_code", None)
                if status in (404, 410):
                    stale.append(sub.endpoint)
                    log.debug(f"[WebPush]订阅已失效，清理: {sub.endpoint[:60]}")
                else:
                    resp_body = ""
                    resp_headers = ""
                    try:
                        resp_body = getattr(e.response, "text", "") or ""
                        resp_headers = str(getattr(e.response, "headers", ""))[:300]
                    except Exception as _e:  # noqa: BLE001
                        log.debug(f"[WebPush]读取响应详情失败: {str(_e)[:80]}")
                    log.warn(
                        f"[WebPush]推送失败 {status} ({sub.endpoint[:60]}): "
                        f"{str(e)[:120]} body={str(resp_body)[:200]} headers={resp_headers}"
                    )
            except Exception as e:  # noqa: BLE001
                log.warn(f"[WebPush]推送异常: {str(e)[:120]}")
        for endpoint in stale:
            self._sub_repo.delete_by_endpoint(endpoint)
        if stale:
            log.info(f"[WebPush]清理失效订阅 {len(stale)} 个")
        return sent
