"""sanitize 公共脱敏助手单元测试"""

from app.agent.sanitize import is_secret_key, mask_config_values, mask_tree, sanitize_dict


class TestIsSecretKey:
    def test_builtin_hints(self):
        assert is_secret_key("API_KEY")
        assert is_secret_key("client_secret")
        assert is_secret_key("cookie")
        assert is_secret_key("admin_token")
        assert is_secret_key("passkey")

    def test_plain_keys_not_secret(self):
        assert not is_secret_key("host")
        assert not is_secret_key("username")
        assert not is_secret_key("port")

    def test_extra_hints(self):
        assert is_secret_key("sckey", extra_hints=("key",))
        assert not is_secret_key("sckey")


class TestMaskConfigValues:
    def test_masks_secret_values_keeps_plain(self):
        out = mask_config_values({"api_key": "sk-123", "host": "127.0.0.1", "note": ""})
        assert out["api_key"] == "***"
        assert out["host"] == "127.0.0.1"
        assert out["note"] == ""

    def test_extra_hints(self):
        out = mask_config_values({"sckey": "abc", "topic": "t"}, extra_hints=("key",))
        assert out["sckey"] == "***"
        assert out["topic"] == "t"


class TestMaskTree:
    def test_recursive_nested(self):
        data = {"app": {"api_key": "k", "nested": {"token": "t", "keep": 1}}}
        out = mask_tree(data)
        assert out["app"]["api_key"] == "***"
        assert out["app"]["nested"]["token"] == "***"
        assert out["app"]["nested"]["keep"] == 1

    def test_list_recursion(self):
        out = mask_tree([{"password": "p"}, {"name": "x"}])
        assert out[0]["password"] == "***"
        assert out[1]["name"] == "x"

    def test_original_untouched(self):
        data = {"cookie": "c", "other": 2}
        mask_tree(data)
        assert data["cookie"] == "c"


class TestSanitizeDict:
    def test_masks_secret_values_and_sk_patterns(self):
        out = sanitize_dict({"cookie": "abc", "host": "sk-1234567890123456", "ok": 1})
        assert out["cookie"] == "***"
        assert "sk-" not in out["host"]
        assert out["ok"] == 1
