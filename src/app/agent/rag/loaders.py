"""内置知识来源 Loader — docs 文档 / 消息模板

media_library 命名空间的 Loader 待 Phase 3 工具层提供库枚举能力后再补
（库内容问答优先走 library_check 工具查实时数据，RAG 只承载静态知识）。
"""

from collections.abc import Iterable
from pathlib import Path

import log
from app.agent.rag.ingestor import KnowledgeLoader
from app.agent.rag.namespaces import Namespace
from app.core.root_path import get_project_root
from app.message.templates import DEFAULT_MESSAGE_TEMPLATES

_DOCS_DIR = Path(get_project_root()) / "docs"

# operations 命名空间：配置 / 运维类文档子集
_OPERATIONS_FILES = ["configuration.md", "development.md", "plugins.md", "plugin_development_guide.md"]

# faq 命名空间排除项（决策记录与资源目录不入库）
_EXCLUDE_DIRS = {"decisions", "assets"}
_EXCLUDE_FILES = set(_OPERATIONS_FILES)


class DocsLoader(KnowledgeLoader):
    """docs/*.md → faq 命名空间"""

    namespace = Namespace.FAQ

    def load(self) -> Iterable[tuple[str, str]]:
        if not _DOCS_DIR.is_dir():
            log.warn(f"[DocsLoader]文档目录不存在: {_DOCS_DIR}")
            return []
        items = []
        for md in sorted(_DOCS_DIR.glob("*.md")):
            if md.name in _EXCLUDE_FILES:
                continue
            try:
                items.append((f"docs/{md.name}", md.read_text(encoding="utf-8")))
            except OSError as e:
                log.warn(f"[DocsLoader]读取失败 {md.name}: {e}")
        return items


class OperationsLoader(KnowledgeLoader):
    """docs 配置/运维子集 → operations 命名空间"""

    namespace = Namespace.OPERATIONS

    def load(self) -> Iterable[tuple[str, str]]:
        if not _DOCS_DIR.is_dir():
            log.warn(f"[OperationsLoader]文档目录不存在: {_DOCS_DIR}")
            return []
        items = []
        for name in _OPERATIONS_FILES:
            md = _DOCS_DIR / name
            if not md.is_file():
                continue
            try:
                items.append((f"docs/{name}", md.read_text(encoding="utf-8")))
            except OSError as e:
                log.warn(f"[OperationsLoader]读取失败 {name}: {e}")
        return items


class MessageTemplateLoader(KnowledgeLoader):
    """消息模板 → messages 命名空间"""

    namespace = Namespace.MESSAGES

    def load(self) -> Iterable[tuple[str, str]]:
        items = []
        for msg_type, tpl in DEFAULT_MESSAGE_TEMPLATES.items():
            text = f"消息类型: {msg_type}\n标题模板: {tpl.get('title', '')}\n内容模板:\n{tpl.get('text', '')}"
            items.append((f"message_template/{msg_type}", text))
        return items


class MediaLibraryLoader(KnowledgeLoader):
    """媒体库 → media_library 命名空间（best-effort：统计 + 最近入库项，非全量目录）"""

    namespace = Namespace.MEDIA_LIBRARY

    def __init__(self, media_library_service, latest_num: int = 200):
        self._service = media_library_service
        self._latest_num = latest_num

    def load(self) -> Iterable[tuple[str, str]]:
        if self._service is None:
            return []
        try:
            counts = self._service.get_media_count() or {}
            text = (
                "媒体库统计："
                f"电影 {counts.get('Movie', 0)} 部；"
                f"剧集 {counts.get('TV', 0)} 部；"
                f"动漫 {counts.get('Anime', 0)} 部。"
            )
            yield ("media_library/statistics", text)
        except Exception as e:
            log.warn(f"[MediaLibraryLoader]读取统计失败: {e}")
        try:
            items = self._service.get_latest(num=self._latest_num) or []
        except Exception as e:
            log.warn(f"[MediaLibraryLoader]读取最近入库失败: {e}")
            return
        for item in items:
            if not isinstance(item, dict):
                continue
            name = item.get("name") or item.get("title") or ""
            if not name:
                continue
            lines = [f"类型：{item.get('type', '')}", f"标题：{name}"]
            if item.get("year"):
                lines.append(f"年份：{item['year']}")
            yield (f"media_library/item/{name}", "\n".join(lines))


def default_loaders(media_library_service=None) -> list[KnowledgeLoader]:
    """MVP 默认知识来源（media_library 需已配置媒体服务器）"""
    loaders: list[KnowledgeLoader] = [DocsLoader(), OperationsLoader(), MessageTemplateLoader()]
    if media_library_service is not None:
        loaders.append(MediaLibraryLoader(media_library_service))
    return loaders
