"""LLM 提供商集合"""

import ipaddress
import socket
from urllib.parse import urlparse

import log
from app.agent.providers.base import (
    BaseEmbeddingProvider,
    BaseProvider,
    EmbeddingConfig,
    ProviderConfig,
)
from app.agent.providers.gemini import GeminiEmbeddingProvider, GeminiProvider
from app.agent.providers.ollama import OllamaEmbeddingProvider, OllamaProvider
from app.agent.providers.openai import OpenAIEmbeddingProvider, OpenAIProvider

_CURATED_EMBEDDING_MODELS: dict[str, list[str]] = {
    "openai": ["text-embedding-3-small", "text-embedding-3-large", "text-embedding-ada-002"],
    "dashscope": ["text-embedding-v3", "text-embedding-v2", "text-embedding-v1", "qwen3-text-embedding"],
    "gemini": ["text-embedding-004", "gemini-embedding-001"],
    "ollama": ["bge-m3", "nomic-embed-text", "mxbai-embed-large", "qwen3-embedding:0.6b"],
}


def validate_api_url(api_url: str) -> str:
    """校验 API 地址，防止 SSRF 打到云元数据/保留地址等危险目标.

    允许回环与私网（localhost / 局域网 Ollama 为常见部署方式）；
    该模型列接口同时已限为 setting:update（管理员）权限。
    """
    if not api_url:
        raise ValueError("api_url 不能为空")
    parsed = urlparse(api_url)
    if parsed.scheme not in ("http", "https") or not parsed.hostname:
        raise ValueError(f"不支持的 API 地址：{api_url}")
    host = parsed.hostname
    try:
        infos = socket.getaddrinfo(host, None, type=socket.SOCK_STREAM)
    except socket.gaierror as e:
        raise ValueError(f"API 地址无法解析：{api_url}") from e
    for info in infos:
        ip_text = str(info[4][0]).split("%")[0]
        ip = ipaddress.ip_address(ip_text)
        if (
            ip.is_link_local
            or ip.is_multicast
            or ip.is_reserved
            or ip.is_unspecified
            or ip == ipaddress.ip_address("169.254.169.254")
        ):
            raise ValueError(f"API 地址指向内部网络，已拒绝：{api_url}")
    return api_url


def list_embedding_models(provider_name: str, api_url: str = "", api_key: str = "", timeout: int = 15) -> list[str]:
    """动态拉取 embedding 模型列表；失败回退精选清单"""
    provider_key = provider_name or "openai"
    if api_url:
        validate_api_url(api_url)
    try:
        if provider_name == "ollama":
            from ollama import Client  # noqa: PLC0415  # 可选依赖按需导入

            host = api_url.removesuffix("/v1").rstrip("/")
            resp = Client(host=host).list()
            names = [m.model for m in resp.models if m.model] if hasattr(resp, "models") else []
            # Ollama 全量包含对话模型；优先保留精选 embedding 清单中已拉取的，再加其余
            curated = set(_CURATED_EMBEDDING_MODELS["ollama"])
            picked = curated.intersection(names)
            return list(picked) if picked else names
        if provider_name == "gemini":
            return list(_CURATED_EMBEDDING_MODELS["gemini"])
        # OpenAI 兼容（含 DashScope）：尝试 /v1/models 过滤 embed
        import httpx2  # noqa: PLC0415  # httpx 非直接依赖（仅 Ollama 提供方按需使用）

        url = api_url.rstrip("/") + "/models"
        headers = {"Authorization": f"Bearer {api_key}"} if api_key else {}
        resp = httpx2.get(url, headers=headers, timeout=timeout)
        if resp.status_code == 200:
            data = resp.json()
            ids = [m.get("id", "") for m in (data.get("data") or []) if m.get("id")]
            embed_ids = [i for i in ids if "embed" in i.lower()]
            if embed_ids:
                return embed_ids
            if ids and provider_key not in ("openai",):
                return ids[:30]
        return list(_CURATED_EMBEDDING_MODELS.get(provider_key, _CURATED_EMBEDDING_MODELS["openai"]))
    except Exception as e:
        log.warn(f"[EmbeddingService]拉取失败，回退精选: {e}")
        return list(_CURATED_EMBEDDING_MODELS.get(provider_key, _CURATED_EMBEDDING_MODELS["openai"]))


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
    "list_embedding_models",
]
