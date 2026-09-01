"""
日志来源提取。

日志消息中的 `[xxx]` 前缀即来源标识，日志调用处已统一为规范组件名，
此处仅负责提取；LEGACY 映射用于兼容统一前写入磁盘的历史日志文件。
"""

import re

__all__ = ["extract_source", "normalize_source"]

_SOURCE_PATTERN = re.compile(r"^\[(.*?)\]")

# 历史日志中的 Plugin:xxx 前缀 → 插件 ID（与新版日志一致）
_PLUGIN_TAG_PATTERN = re.compile(r"^[Pp]lugin\s*[:：]\s*(\S+)$")

# 历史日志文件（统一前写入）中的旧标签 → 规范组件名
LEGACY_SOURCE_MAP: dict[str, str] = {
    "telegram": "Telegram",
    "slack": "Slack",
    "douban": "Douban",
    "feishu": "Feishu",
    "dingtalk": "DingTalk",
    "synologychat": "SynologyChat",
    "bangumi": "Bangumi",
    "wework": "Wework",
    "plugin": "Plugin",
    "sync_service": "Sync",
    "engine": "SiteEngine",
    "html_searcher": "HtmlSiteSearcher",
    "prefetch": "SiteEngine",
    "engine_user_info": "SiteUserInfo",
    "config_html": "SiteConfigUpdater",
    "nexus_php": "Sites",
    "small_horse": "Sites",
    "site_userinfo": "SiteUserInfo",
    "hdsky": "Sites",
    "tjupt": "Sites",
    "_call_endpoint": "SiteEngine",
    "_fetch_csrf_token": "SiteEngine",
    "_resolve_auth_token": "SiteEngine",
    "test_html_connection": "SiteEngine",
    "service": "MediaService",
    "media_detail": "MediaService",
    "media_recommendation_service": "MediaService",
    "get_nt_image_url": "MediaServer",
    "_base": "MediaServer",
    "adapters": "Cache",
    "decorators": "Cache",
    "deps": "API",
    "core": "ImageProxy",
    "get_proxy_image_url": "ImageProxy",
    "list_embedding_models": "EmbeddingService",
    "plugin_framework_service": "PluginFrameworkService",
    "task_service": "Brush",
    "search_result_service": "Search",
    "file_index_service": "FileIndex",
    "media_file_service": "FileOps",
    "cross_backend": "CrossBackend",
    "existence_checker": "FileTransfer",
    "smb": "SMB",
    "RBAC初始化": "RBAC",
    "内置索引器": "BuiltinIndexer",
}


def normalize_source(raw: str) -> str:
    """统一历史日志中的旧来源标签."""
    match = _PLUGIN_TAG_PATTERN.match(raw)
    if match:
        return match.group(1)
    return LEGACY_SOURCE_MAP.get(raw, raw)


def extract_source(text: str) -> tuple[str, str]:
    """从日志消息提取来源，返回 (来源, 去掉前缀后的消息文本)."""
    match = _SOURCE_PATTERN.match(text)
    if match:
        source = normalize_source(match.group(1))
        text = text[len(match.group(0)) :].lstrip()
    else:
        source = "系统"
    return source, text
