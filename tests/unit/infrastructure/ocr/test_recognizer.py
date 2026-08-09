"""Tests for the image recognition module."""

from typing import Any
from unittest.mock import patch

import httpx2
import pytest

from app.infrastructure.ocr.core import (
    ProviderNotFoundError,
    ProviderRegistry,
    ProviderUnavailableError,
    RecognitionError,
    RecognitionResult,
    RecognitionTask,
    TaskType,
)
from app.infrastructure.ocr.engine import RecognitionEngine
from app.infrastructure.ocr.providers.base import Provider
from app.infrastructure.ocr.providers.remote import RemoteProvider
from app.infrastructure.ocr.recognizer import OcrRecognizer


class FakeResponse:
    """Fake HTTP response for HttpClient mocking."""

    def __init__(self, json_data: Any = None, content: bytes = b"", status_code: int = 200) -> None:
        self._json = json_data
        self.content = content
        self.status_code = status_code

    def json(self) -> Any:
        return self._json

    def raise_for_status(self) -> None:
        if self.status_code >= 400:
            raise httpx2.HTTPError(f"HTTP {self.status_code}")


class DummyProvider(Provider):
    """Provider mock for tests."""

    name = "dummy"
    tasks = {TaskType.CAPTCHA}

    @property
    def available(self) -> bool:
        return True

    def verify(self, task: RecognitionTask) -> RecognitionResult:
        return RecognitionResult(text="DUMMY")


class UnavailableProvider(Provider):
    """Unavailable provider mock for tests."""

    name = "unavailable"
    tasks = {TaskType.CAPTCHA}

    @property
    def available(self) -> bool:
        return False

    def verify(self, task: RecognitionTask) -> RecognitionResult:
        return RecognitionResult(text="")


@pytest.fixture
def remote_provider() -> RemoteProvider:
    return RemoteProvider(base_url="http://127.0.0.1:9300")


@pytest.fixture
def recognizer() -> OcrRecognizer:
    registry = ProviderRegistry()
    registry.register(RemoteProvider(base_url="http://127.0.0.1:9300"))
    return OcrRecognizer(engine=RecognitionEngine(registry=registry))


@pytest.fixture
def engine_with_dummy() -> RecognitionEngine:
    registry = ProviderRegistry()
    registry.register(DummyProvider())
    return RecognitionEngine(registry=registry)


def test_remote_provider_available_when_host_configured(remote_provider: RemoteProvider) -> None:
    assert remote_provider.available is True


def test_remote_provider_unavailable_when_host_missing() -> None:
    provider = RemoteProvider(base_url="")
    assert provider.available is False


class _FakeSettings:
    def __init__(self, enabled: bool, host: str) -> None:
        self._enabled = enabled
        self._host = host

    def get(self, node: str | None = None) -> dict[str, Any]:
        if node == "laboratory":
            return {"ocr_enabled": self._enabled, "ocr_server_host": self._host}
        return {}


def test_remote_provider_disabled_by_setting(monkeypatch) -> None:
    monkeypatch.setattr(
        "app.infrastructure.ocr.providers.remote.settings",
        _FakeSettings(enabled=False, host="http://127.0.0.1:9300"),
    )
    provider = RemoteProvider()
    assert provider.available is False


def test_remote_provider_enabled_by_setting(monkeypatch) -> None:
    monkeypatch.setattr(
        "app.infrastructure.ocr.providers.remote.settings",
        _FakeSettings(enabled=True, host="http://127.0.0.1:9300"),
    )
    provider = RemoteProvider()
    assert provider.available is True


def test_remote_provider_routes_captcha(remote_provider: RemoteProvider) -> None:
    mock_response = FakeResponse(
        json_data={
            "code": 0,
            "data": {
                "task_type": "captcha",
                "provider": "remote",
                "result": {"text": "abc123"},
            },
        }
    )
    with patch("app.infrastructure.ocr.providers.remote.HttpClient") as mock_http:
        mock_http.return_value.__enter__.return_value = mock_http.return_value
        mock_http.return_value.post.return_value = mock_response
        task = RecognitionTask(task_type=TaskType.CAPTCHA, image_b64="data")
        result = remote_provider.verify(task)

    assert result.text == "abc123"
    mock_http.return_value.post.assert_called_once()


def test_remote_provider_raises_on_error_response(remote_provider: RemoteProvider) -> None:
    mock_response = FakeResponse(json_data={"code": 500, "message": "ocr failed"})
    with patch("app.infrastructure.ocr.providers.remote.HttpClient") as mock_http:
        mock_http.return_value.__enter__.return_value = mock_http.return_value
        mock_http.return_value.post.return_value = mock_response
        task = RecognitionTask(task_type=TaskType.CAPTCHA, image_b64="data")
        with pytest.raises(RecognitionError):
            remote_provider.verify(task)


def test_registry_selects_provider_by_name() -> None:
    registry = ProviderRegistry()
    registry.register(DummyProvider())
    task = RecognitionTask(task_type=TaskType.CAPTCHA, provider="dummy")
    provider = registry.get(task)
    assert provider.name == "dummy"


def test_registry_raises_for_unknown_provider() -> None:
    registry = ProviderRegistry()
    task = RecognitionTask(task_type=TaskType.CAPTCHA, provider="missing")
    with pytest.raises(ProviderNotFoundError):
        registry.get(task)


def test_registry_raises_for_unavailable_provider() -> None:
    registry = ProviderRegistry()
    registry.register(UnavailableProvider())
    task = RecognitionTask(task_type=TaskType.CAPTCHA)
    with pytest.raises(ProviderUnavailableError):
        registry.get(task)


def test_engine_routes_to_provider(engine_with_dummy: RecognitionEngine) -> None:
    result = engine_with_dummy.verify(RecognitionTask(task_type=TaskType.CAPTCHA))
    assert result.text == "DUMMY"


def test_engine_lists_providers(engine_with_dummy: RecognitionEngine) -> None:
    providers = engine_with_dummy.providers()
    assert len(providers) == 1
    assert providers[0]["name"] == "dummy"


def test_ocr_recognizer_returns_captcha_text(recognizer: OcrRecognizer) -> None:
    mock_response = FakeResponse(
        json_data={
            "code": 0,
            "data": {
                "task_type": "captcha",
                "provider": "remote",
                "result": {"text": "abc123"},
            },
        }
    )
    with patch("app.infrastructure.ocr.providers.remote.HttpClient") as mock_http:
        mock_http.return_value.__enter__.return_value = mock_http.return_value
        mock_http.return_value.post.return_value = mock_response
        text = recognizer.get_captcha_text(image_b64="data")

    assert text == "abc123"


def test_ocr_recognizer_downloads_image_url(recognizer: OcrRecognizer) -> None:
    get_response = FakeResponse(content=b"imagedata")
    post_response = FakeResponse(
        json_data={
            "code": 0,
            "data": {
                "task_type": "captcha",
                "provider": "remote",
                "result": {"text": "abc123"},
            },
        }
    )

    def fake_post(*args: Any, **kwargs: Any) -> FakeResponse:
        return post_response

    def fake_get(*args: Any, **kwargs: Any) -> FakeResponse:
        return get_response

    with patch("app.infrastructure.ocr.providers.remote.HttpClient") as mock_http:
        mock_http.return_value.__enter__.return_value = mock_http.return_value
        mock_http.return_value.post.side_effect = fake_post
        with patch("app.infrastructure.ocr.utils.HttpClient") as mock_utils_http:
            mock_utils_http.return_value.__enter__.return_value = mock_utils_http.return_value
            mock_utils_http.return_value.get.side_effect = fake_get
            text = recognizer.get_captcha_text(image_url="http://example.com/captcha.png", cookie="a=1", ua="Test")

    assert text == "abc123"
    mock_utils_http.return_value.get.assert_called_once()


def test_ocr_recognizer_returns_empty_on_failure(recognizer: OcrRecognizer) -> None:
    mock_response = FakeResponse(json_data={"code": 500, "message": "failed"})
    with patch("app.infrastructure.ocr.providers.remote.HttpClient") as mock_http:
        mock_http.return_value.__enter__.return_value = mock_http.return_value
        mock_http.return_value.post.return_value = mock_response
        text = recognizer.get_captcha_text(image_b64="data")

    assert text == ""


def test_ocr_recognizer_recognize_task(recognizer: OcrRecognizer) -> None:
    mock_response = FakeResponse(
        json_data={
            "code": 0,
            "data": {
                "task_type": "slide_captcha",
                "provider": "remote",
                "result": {"distance": 42},
            },
        }
    )
    with patch("app.infrastructure.ocr.providers.remote.HttpClient") as mock_http:
        mock_http.return_value.__enter__.return_value = mock_http.return_value
        mock_http.return_value.post.return_value = mock_response
        result = recognizer.recognize({"task_type": "slide_captcha", "image_b64": "data"})

    assert result.distance == 42
