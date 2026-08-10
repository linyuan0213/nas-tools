from dataclasses import dataclass

from app.core.settings import settings


@dataclass
class ProviderConfig:
    """LLM 提供商配置"""

    name: str
    api_key: str
    api_url: str
    model: str
    proxy: str | None = None
    timeout: int = 60


@dataclass
class EmbeddingConfig:
    """Embedding 配置"""

    provider: str
    model: str
    api_key: str = ""
    api_url: str = ""
    proxy: str | None = None
    timeout: int = 60


def _agent_cfg() -> dict:
    return settings.get("agent") or {}


def agent_enabled() -> bool:
    return bool(_agent_cfg().get("enabled"))


def get_provider(provider_name: str = "") -> ProviderConfig | None:
    """获取 LLM 提供商配置"""
    cfg = _agent_cfg()
    if not cfg.get("enabled"):
        return None
    providers = cfg.get("providers", {})
    if not provider_name:
        provider_name = cfg.get("default_provider", "")
    if not provider_name:
        return None
    p = providers.get(provider_name)
    if not p:
        return None
    return ProviderConfig(
        name=provider_name,
        api_key=p.get("api_key", ""),
        api_url=p.get("api_url", ""),
        model=p.get("model", ""),
        proxy=p.get("proxy"),
    )


def get_fallback_providers() -> list[ProviderConfig]:
    """获取故障转移 provider 链（排除主 provider）"""
    cfg = _agent_cfg()
    if not cfg.get("enabled"):
        return []
    default = cfg.get("default_provider", "")
    result = []
    for name in cfg.get("fallback") or []:
        if name == default:
            continue
        p = get_provider(name)
        if p:
            result.append(p)
    return result


def get_embedding_config() -> EmbeddingConfig | None:
    """获取 embedding 配置；未配置时回退用主 provider 的连接参数"""
    cfg = _agent_cfg()
    if not cfg.get("enabled"):
        return None
    emb = cfg.get("embedding") or {}
    provider = emb.get("provider") or cfg.get("default_provider", "")
    model = emb.get("model", "")
    if not provider or not model:
        return None
    base = (cfg.get("providers", {}) or {}).get(provider, {}) or {}
    return EmbeddingConfig(
        provider=provider,
        model=model,
        api_key=emb.get("api_key", base.get("api_key", "")),
        api_url=emb.get("api_url", base.get("api_url", "")),
        proxy=emb.get("proxy", base.get("proxy")),
        timeout=emb.get("timeout", 60),
    )


def get_vector_store_config() -> dict:
    """向量库配置：type + 各后端参数"""
    cfg = _agent_cfg()
    return {
        "type": cfg.get("vector_store", "sqlite"),
        "sqlite": cfg.get("sqlite") or {},
        "lancedb": cfg.get("lancedb") or {},
        "qdrant": cfg.get("qdrant") or {},
    }


def get_rag_config() -> dict:
    """RAG 参数"""
    cfg = _agent_cfg()
    rag = cfg.get("rag") or {}
    return {
        "chunk_size": rag.get("chunk_size", 800),
        "chunk_overlap": rag.get("chunk_overlap", 100),
        "top_k": rag.get("top_k", 6),
        "rerank_top_k": rag.get("rerank_top_k", 3),
        "namespaces": rag.get("namespaces") or ["media_library", "messages", "faq", "operations"],
    }


def get_memory_config() -> dict:
    """记忆参数"""
    cfg = _agent_cfg()
    mem = cfg.get("memory") or {}
    short = mem.get("short_term") or {}
    return {
        "max_steps": mem.get("max_steps", 8),
        "short_term": {
            "store": short.get("store", "db"),
            "max_tokens": short.get("max_tokens", 4000),
            "ttl_days": short.get("ttl_days", 30),
        },
    }
