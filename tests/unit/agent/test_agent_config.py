"""agent 配置读取单元测试"""

import app.agent.config as agent_config


class _StubSettings:
    def __init__(self, cfg: dict):
        self._cfg = cfg

    def get(self, key, default=None):
        return self._cfg.get(key, default)


_AGENT_CFG = {
    "enabled": True,
    "default_provider": "ollama",
    "fallback": ["ollama", "openai"],
    "providers": {
        "ollama": {"api_url": "http://localhost:11434", "model": "qwen2.5:32b"},
        "openai": {"api_key": "sk-x", "api_url": "https://api.openai.com", "model": "gpt-4o"},
    },
    "embedding": {"provider": "ollama", "model": "nomic-embed-text"},
    "rag": {"chunk_size": 500},
    "memory": {"max_steps": 5},
}


class TestAgentConfig:
    def test_disabled_returns_none(self, monkeypatch):
        monkeypatch.setattr(agent_config, "settings", _StubSettings({"agent": {"enabled": False}}))
        assert agent_config.get_provider() is None
        assert agent_config.get_embedding_config() is None
        assert agent_config.get_fallback_providers() == []

    def test_get_provider_default(self, monkeypatch):
        monkeypatch.setattr(agent_config, "settings", _StubSettings({"agent": _AGENT_CFG}))
        p = agent_config.get_provider()
        assert p is not None
        assert p.name == "ollama"
        assert p.model == "qwen2.5:32b"

    def test_fallback_excludes_default(self, monkeypatch):
        monkeypatch.setattr(agent_config, "settings", _StubSettings({"agent": _AGENT_CFG}))
        fallbacks = agent_config.get_fallback_providers()
        assert [p.name for p in fallbacks] == ["openai"]

    def test_embedding_config_inherits_provider_connection(self, monkeypatch):
        monkeypatch.setattr(agent_config, "settings", _StubSettings({"agent": _AGENT_CFG}))
        emb = agent_config.get_embedding_config()
        assert emb is not None
        assert emb.provider == "ollama"
        assert emb.model == "nomic-embed-text"
        assert emb.api_url == "http://localhost:11434"

    def test_rag_config_defaults_and_override(self, monkeypatch):
        monkeypatch.setattr(agent_config, "settings", _StubSettings({"agent": _AGENT_CFG}))
        rag = agent_config.get_rag_config()
        assert rag["chunk_size"] == 500
        assert rag["top_k"] == 6
        assert "faq" in rag["namespaces"]

    def test_vector_store_default_sqlite(self, monkeypatch):
        monkeypatch.setattr(agent_config, "settings", _StubSettings({"agent": _AGENT_CFG}))
        vs = agent_config.get_vector_store_config()
        assert vs["type"] == "sqlite"

    def test_memory_config(self, monkeypatch):
        monkeypatch.setattr(agent_config, "settings", _StubSettings({"agent": _AGENT_CFG}))
        mem = agent_config.get_memory_config()
        assert mem["max_steps"] == 5
        assert mem["short_term"]["store"] == "db"

    def test_reasoning_config_default_high_enabled(self, monkeypatch):
        monkeypatch.setattr(agent_config, "settings", _StubSettings({"agent": {}}))
        rc = agent_config.get_reasoning_config()
        assert rc == {"effort": "high", "enabled": True}

    def test_reasoning_config_override(self, monkeypatch):
        monkeypatch.setattr(
            agent_config, "settings", _StubSettings({"agent": {"reasoning_effort": "low", "disable_thinking": True}})
        )
        rc = agent_config.get_reasoning_config()
        assert rc == {"effort": "low", "enabled": False}

    def test_reasoning_config_invalid_effort_normalized(self, monkeypatch):
        monkeypatch.setattr(agent_config, "settings", _StubSettings({"agent": {"reasoning_effort": "medium"}}))
        rc = agent_config.get_reasoning_config()
        assert rc["effort"] == "high"

    def test_normalize_reasoning_effort(self):
        assert agent_config.normalize_reasoning_effort("low") == "low"
        assert agent_config.normalize_reasoning_effort("HIGH") == "high"
        assert agent_config.normalize_reasoning_effort("max") == "max"
        assert agent_config.normalize_reasoning_effort("") == "high"
        assert agent_config.normalize_reasoning_effort("medium", default="low") == "low"
