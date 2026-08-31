"""飞书开放平台 API 客户端.

- 应用模式：tenant_access_token 获取（缓存）、im/v1/messages 发送、ws_endpoint 获取
- Webhook 模式：自定义机器人发送（可选签名）
"""

import threading
import time

from app.infrastructure.http.client import HttpClient
from app.infrastructure.http.config import HttpClientConfig
from app.plugin_framework.builtin_plugins.feishu.backend.signer import gen_sign
from app.utils import ExceptionUtils
from app.utils.json_utils import JsonUtils


class FeishuApi:
    """飞书 API 封装（token 线程安全缓存 + 发送 + 长连接地址获取）"""

    _BASE_URL = "https://open.feishu.cn/open-apis"

    def __init__(self, app_id: str = "", app_secret: str = "", webhook_url: str = "", secret: str = ""):
        self._app_id = app_id
        self._app_secret = app_secret
        self._webhook_url = webhook_url
        self._secret = secret
        self._token = ""
        self._expires_at = 0.0
        self._token_lock = threading.Lock()

    # ---------- 应用模式：token ----------

    def get_tenant_access_token(self) -> str:
        """获取 tenant_access_token（本地缓存，提前 5 分钟刷新）"""
        if self._token and time.time() < self._expires_at:
            return self._token
        with self._token_lock:
            if self._token and time.time() < self._expires_at:
                return self._token
            resp = HttpClient(config=HttpClientConfig(timeout=10)).post(
                f"{self._BASE_URL}/auth/v3/tenant_access_token/internal",
                json={"app_id": self._app_id, "app_secret": self._app_secret},
            )
            data = resp.json()
            if not data or data.get("code") != 0 or not data.get("tenant_access_token"):
                raise RuntimeError(str((data or {}).get("msg") or "获取 tenant_access_token 失败"))
            self._token = data["tenant_access_token"]
            self._expires_at = time.time() + max(int(data.get("expire", 7200)) - 300, 60)
            return self._token

    def _auth_headers(self) -> dict:
        return {"Authorization": f"Bearer {self.get_tenant_access_token()}"}

    @staticmethod
    def _infer_receive_id_type(target: str) -> str:
        """根据接收人 ID 前缀推断 receive_id_type"""
        return "open_id" if target.startswith("ou_") else "chat_id"

    def _extract_error(self, err: Exception) -> str:
        """从请求异常中提取飞书业务错误信息（4xx/5xx 响应体携带 code/msg）"""
        # HttpClientError 包装了原始 httpx 异常（__cause__ 携带 response）
        raw = getattr(err, "__cause__", None) or err
        response = getattr(raw, "response", None)
        if response is not None:
            try:
                data = response.json()
                code = data.get("code")
                msg = data.get("msg")
                if code is not None:
                    return f"{code}: {msg}"
            except Exception:  # noqa: S110 - 响应体非 JSON 时回退默认错误文案
                pass
        return str(err)

    # ---------- 应用模式：图片 ----------

    def upload_image(self, image_bytes: bytes) -> tuple[bool, str]:
        """上传图片到飞书，返回 (是否成功, image_key 或错误信息)"""
        try:
            resp = HttpClient(config=HttpClientConfig(timeout=20)).post(
                f"{self._BASE_URL}/im/v1/images",
                headers=self._auth_headers(),
                data={"image_type": "message"},
                files={"image": ("image.jpg", image_bytes, "image/jpeg")},
            )
            data = resp.json()
            if data and data.get("code") == 0:
                return True, str(((data.get("data") or {}).get("image_key") or ""))
            return False, str((data or {}).get("msg") or "图片上传失败")
        except Exception as e:
            err_msg = self._extract_error(e)
            ExceptionUtils.exception_traceback(e)
            return False, err_msg

    # ---------- 应用模式：发送 ----------

    def send_card(self, target: str, card: dict) -> tuple[bool, str]:
        """向指定用户/群发送交互卡片消息"""
        try:
            resp = HttpClient(config=HttpClientConfig(timeout=15)).post(
                f"{self._BASE_URL}/im/v1/messages?receive_id_type={self._infer_receive_id_type(target)}",
                headers=self._auth_headers(),
                json={
                    "receive_id": target,
                    "msg_type": "interactive",
                    "content": JsonUtils.dumps(card, ensure_ascii=False),
                },
            )
            data = resp.json()
            if data and data.get("code") == 0:
                return True, ""
            return False, str((data or {}).get("msg") or resp.text[:200])
        except Exception as e:
            err_msg = self._extract_error(e)
            ExceptionUtils.exception_traceback(e)
            return False, err_msg

    # ---------- Webhook 模式：发送 ----------

    def send_webhook(self, payload: dict, secret: str | None = None) -> tuple[bool, str]:
        """向自定义机器人 Webhook 发送消息（可选签名）"""
        try:
            headers = {"Content-Type": "application/json"}
            if secret:
                timestamp = str(int(time.time()))
                headers.update(
                    {
                        "X-Lark-Request-Timestamp": timestamp,
                        "X-Lark-Request-Signature": gen_sign(secret, timestamp),
                    }
                )
            resp = HttpClient(config=HttpClientConfig(timeout=15)).post(
                self._webhook_url, json=payload, headers=headers
            )
            data = resp.json()
            if data and data.get("code") == 0:
                return True, ""
            return False, str((data or {}).get("msg") or resp.text[:200])
        except Exception as e:
            err_msg = self._extract_error(e)
            ExceptionUtils.exception_traceback(e)
            return False, err_msg
