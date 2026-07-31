"""
搜索领域 Repository 接口（Python Protocol）
定义搜索结果仓储契约
"""

from typing import Any, Protocol


class ISearchRepository(Protocol):
    """搜索结果仓储接口"""

    def insert_search_results(
        self, media_items: list, title=None, ident_flag=True, session_id: str | None = None, user_id: str | None = None
    ) -> None:
        """保存搜索结果到数据库"""
        ...

    def get_search_result_by_id(self, dl_id) -> Any:
        """根据ID获取搜索结果"""
        ...

    def get_search_results(self, session_id: str | None = None, user_id: str | None = None) -> list[Any]:
        """获取搜索结果，支持按会话隔离"""
        ...

    def delete_all_search_torrents(self) -> None:
        """删除所有搜索结果（全局清理）"""
        ...

    def delete_by_session(self, session_id: str) -> None:
        """按搜索会话删除结果"""
        ...

    def delete_expired(self, ttl_hours: int = 24) -> None:
        """清理过期搜索结果"""
        ...
