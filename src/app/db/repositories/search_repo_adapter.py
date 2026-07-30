"""
搜索领域 Repository 适配器
将旧版 SearchRepository 适配为新领域接口
"""

from app.db.repositories.search_repository import SearchRepository
from app.domain.interfaces.search_repo import ISearchRepository


class SearchRepositoryAdapter(ISearchRepository):
    """搜索结果仓储适配器"""

    def __init__(self, repo: SearchRepository | None = None):
        self._repo = repo or SearchRepository()

    def insert_search_results(
        self, media_items: list, title=None, ident_flag=True, session_id: str | None = None, user_id: str | None = None
    ) -> None:
        self._repo.insert_search_results(media_items, title, ident_flag, session_id)

    def get_search_result_by_id(self, dl_id):
        return self._repo.get_search_result_by_id(dl_id)

    def get_search_results(self, session_id: str | None = None, user_id: str | None = None):
        return self._repo.get_search_results(session_id, user_id)

    def delete_all_search_torrents(self) -> None:
        self._repo.delete_all_search_torrents()

    def delete_by_session(self, session_id: str) -> None:
        self._repo.delete_by_session(session_id)

    def delete_expired(self, ttl_hours: int = 24) -> None:
        self._repo.delete_expired(ttl_hours)
