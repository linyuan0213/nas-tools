"""WebPushService 单元测试：VAPID 持久化、订阅管理、推送清理."""

from types import SimpleNamespace

import pytest

import app.services.web_push_service as mod
from app.services.web_push_service import WebPushService


class _FakeSysRepo:
    def __init__(self):
        self._store: dict[tuple, str] = {}

    def get_by_type_key(self, dtype, key):
        if (dtype, key) in self._store:
            return SimpleNamespace(value=self._store[(dtype, key)])
        return None

    def set(self, dtype, key, value, note=""):
        self._store[(dtype, key)] = value
        return True


class _FakeSubRepo:
    def __init__(self):
        self.rows: dict[str, dict] = {}

    def upsert(self, endpoint, p256dh, auth, user_id=""):
        self.rows[endpoint] = {"p256dh": p256dh, "auth": auth, "user_id": user_id}

    def delete_by_endpoint(self, endpoint):
        return self.rows.pop(endpoint, None) is not None

    def list_all(self):
        return [SimpleNamespace(endpoint=e, **v) for e, v in self.rows.items()]


@pytest.fixture
def svc(monkeypatch):
    s = WebPushService()
    s._sys_repo = _FakeSysRepo()  # type: ignore[assignment]
    s._sub_repo = _FakeSubRepo()  # type: ignore[assignment]
    return s


class TestVapidKeys:
    def test_generate_and_persist(self, svc):
        pub1 = svc.get_public_key()
        pub2 = svc.get_public_key()
        # 两次调用公钥一致（持久化），且为 URL-safe base64 无填充
        assert pub1 == pub2
        assert "=" not in pub1 and "+" not in pub1 and "/" not in pub1
        assert len(pub1) > 40


class TestSubscribe:
    def test_subscribe_and_count(self, svc):
        svc.subscribe("https://push.example/x", "p1", "a1", "u1")
        assert svc.subscription_count() == 1
        # 同 endpoint 幂等
        svc.subscribe("https://push.example/x", "p2", "a2", "u1")
        assert svc.subscription_count() == 1

    def test_unsubscribe(self, svc):
        svc.subscribe("https://push.example/x", "p1", "a1")
        assert svc.unsubscribe("https://push.example/x") is None
        assert svc.subscription_count() == 0


class TestSendPush:
    def test_no_subscriptions_returns_zero(self, svc):
        assert svc.send_push("t", "b") == 0

    def test_send_counts_and_cleans_stale(self, svc, monkeypatch):
        svc.subscribe("https://push.example/ok", "p", "a")
        svc.subscribe("https://push.example/gone", "p", "a")

        def fake_webpush(subscription_info, data, vapid_private_key, vapid_claims, **kwargs):
            ep = subscription_info["endpoint"]
            if "gone" in ep:
                resp = SimpleNamespace(status_code=410)
                raise mod.WebPushException("gone", response=resp)
            return None

        monkeypatch.setattr(mod, "webpush", fake_webpush)
        sent = svc.send_push("t", "b")
        assert sent == 1
        # 410 失效端点已清理
        assert svc.subscription_count() == 1
