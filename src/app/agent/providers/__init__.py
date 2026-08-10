"""LLM 提供商集合"""

from app.agent.config import EmbeddingConfig
from app.agent.providers.base import BaseEmbeddingProvider, BaseProvider, ProviderConfig
from app.agent.providers.gemini import GeminiEmbeddingProvider, GeminiProvider
from app.agent.providers.ollama import OllamaEmbeddingProvider, OllamaProvider
from app.agent.providers.openai import OpenAIEmbeddingProvider, OpenAIProvider


def create_embedding_provider(cfg: EmbeddingConfig) -> BaseEmbeddingProvider:
    """按配置创建 embedding 提供商"""
    provider_cfg = ProviderConfig(
        name=cfg.provider,
        api_key=cfg.api_key,
        api_url=cfg.api_url,
        model=cfg.model,
        proxy=cfg.proxy,
        timeout=cfg.timeout,
    )
    if cfg.provider == "ollama":
        return OllamaEmbeddingProvider(provider_cfg, cfg.model)
    if cfg.provider == "gemini":
        return GeminiEmbeddingProvider(provider_cfg, cfg.model)
    return OpenAIEmbeddingProvider(provider_cfg, cfg.model)


__all__ = [
    "BaseProvider",
    "BaseEmbeddingProvider",
    "ProviderConfig",
    "OpenAIProvider",
    "OllamaProvider",
    "GeminiProvider",
    "OpenAIEmbeddingProvider",
    "OllamaEmbeddingProvider",
    "GeminiEmbeddingProvider",
    "create_embedding_provider",
]
