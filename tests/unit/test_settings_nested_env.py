"""settings 嵌套字段标量环境变量过滤修复的回归测试

背景：宿主环境存在 AGENT=1 这类与嵌套模型字段同名的标量环境变量时，
pydantic-settings 会用它覆盖整个嵌套配置段（agent=1），
导致 _validate_agent 收到非 dict 并静默回退默认值。
修复：_NestedSafeEnvSource / _NestedSafeDotEnvSource 丢弃此类标量覆盖。
"""

from app.core.settings import AppSettings, _drop_scalar_overrides


class TestDropScalarOverrides:
    def test_scalar_env_dropped(self):
        data = {"agent": 1, "database": "sqlite"}
        result = _drop_scalar_overrides(AppSettings, data)
        assert "agent" not in result
        assert "database" not in result

    def test_dict_values_kept(self):
        data = {"agent": {"enabled": True}, "database": {"type": "sqlite"}}
        result = _drop_scalar_overrides(AppSettings, data)
        assert result["agent"] == {"enabled": True}
        assert result["database"] == {"type": "sqlite"}

    def test_non_model_fields_untouched(self):
        data = {"nexus_media_config": "/tmp/x", "tz": "Asia/Shanghai"}
        result = _drop_scalar_overrides(AppSettings, data)
        assert result == data

    def test_agent_yaml_survives_scalar_env(self, monkeypatch, tmp_path):
        """AGENT=1 标量环境下，yaml 中的 agent 配置仍应生效"""
        cfg = tmp_path / "c.yaml"
        cfg.write_text("agent:\n  enabled: true\n  default_provider: deepseek\n", encoding="utf-8")
        monkeypatch.setenv("NEXUS_MEDIA_CONFIG", str(cfg))
        monkeypatch.setenv("AGENT", "1")
        s = AppSettings()
        assert s.agent.enabled is True
        assert s.agent.default_provider == "deepseek"
