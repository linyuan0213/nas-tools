"""ChromeTransport.close() 必须执行会话删除（MRO 回归）.

httpx2.BaseTransport.close() 是空实现，若在继承顺序中排在 _BaseChromeTransport
之前，close() 会被解析成空实现，非持久会话永不删除（nexus-chrome 标签页堆积）。
"""

from app.infrastructure.http.browser_transport import ChromeTransport
from app.infrastructure.http.config import BrowserModeConfig


class _FakeServer:
    def __init__(self, *args, **kwargs):
        self.deleted: list[str] = []
        self.closed = False

    def ensure_session(self, session_key, browser):
        return {}

    def request(self, session_key, browser, url, method, headers, data, cookie):
        return {"data": {"status_code": 200}}

    def delete_session(self, session_key):
        self.deleted.append(session_key)

    def close(self):
        self.closed = True


def _transport(monkeypatch, persistent: bool) -> tuple[ChromeTransport, _FakeServer]:
    fake = _FakeServer()
    monkeypatch.setattr("app.infrastructure.http.browser_transport._ChromeServerClient", lambda *a, **k: fake)
    browser = BrowserModeConfig(
        enabled=True,
        server_url="http://chrome:9850",
        session_key="site-x",
        site_key="site-x",
        persistent_session=persistent,
    )
    return ChromeTransport(browser), fake


class TestChromeTransportClose:
    def test_close_deletes_non_persistent_session(self, monkeypatch):
        transport, fake = _transport(monkeypatch, persistent=False)
        assert ChromeTransport.close.__qualname__.startswith("_BaseChromeTransport")
        transport.close()
        assert fake.deleted == ["site-x"]
        assert fake.closed is True

    def test_close_keeps_persistent_session(self, monkeypatch):
        transport, fake = _transport(monkeypatch, persistent=True)
        transport.close()
        assert fake.deleted == []
        assert fake.closed is True
