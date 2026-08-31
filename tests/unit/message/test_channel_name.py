"""消息渠道标识规范化与注册表注销单元测试."""

from app.domain.enums import SearchType, channel_key, channel_name
from app.message import registry


class TestChannelName:
    def test_enum_channel(self):
        assert channel_name(SearchType.TG) == "Telegram"

    def test_string_channel(self):
        assert channel_name("FEISHU") == "FEISHU"

    def test_none_channel(self):
        assert channel_name(None) == ""

    def test_empty_channel(self):
        assert channel_name("") == ""


class TestChannelKey:
    def test_enum_channel(self):
        assert channel_key(SearchType.TG) == "TG"

    def test_string_channel(self):
        assert channel_key("FEISHU") == "FEISHU"

    def test_none_channel(self):
        assert channel_key(None) == ""


class TestRegistryUnregister:
    def test_unregister_removes_class(self):
        registry.unregister("__nonexistent__")
        assert registry.get_client_class("__nonexistent__") is None

    def test_unregister_registered_class(self):
        class _FakeClient:
            schema = "__fake_feishu__"

        registry.register(_FakeClient)
        assert registry.get_client_class("__fake_feishu__") is _FakeClient
        registry.unregister("__fake_feishu__")
        assert registry.get_client_class("__fake_feishu__") is None
        registry.unregister("__fake_feishu__")
