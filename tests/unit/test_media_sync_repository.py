"""MEDIASYNC_ITEMS 仓储 PostgreSQL 类型一致性回归测试.

varchar 列（TMDBID/YEAR/ITEM_ID）与 int 入参比较在 PostgreSQL 报
"operator does not exist: character varying = integer"，本测试覆盖统一转 str 逻辑。
"""

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.db.models import Base
from app.db.repositories.media_sync_repository import MediaSyncRepository
from app.db.session import SessionManager


@pytest.fixture
def repo():
    engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False})
    Base.metadata.create_all(engine)
    manager = SessionManager()
    manager._engine = engine
    manager._factory = sessionmaker(bind=engine, expire_on_commit=False)
    MediaSyncRepository._session_manager = manager
    yield MediaSyncRepository()
    engine.dispose()


class TestMediaSyncTypeCoercion:
    def test_insert_and_query_with_int_tmdbid(self, repo):
        """int tmdbid 写入后按 int 查询命中（写入/查询均转 str）"""
        ok = repo.insert_item(
            "emby",
            {
                "id": "item-1",
                "library": "电影",
                "type": "movie",
                "title": "星际穿越",
                "originalTitle": "Interstellar",
                "year": 2014,
                "tmdbid": 157336,
                "imdbid": "tt0816692",
                "path": "/m/Interstellar",
                "note": "",
            },
        )
        assert ok
        item = repo.query_item(server_type="emby", title="星际穿越", year=2014, tmdbid=157336)
        assert item is not None
        assert item.TMDBID == "157336"
        assert item.YEAR == "2014"

    def test_query_item_with_int_year_and_tmdbid_matches(self, repo):
        repo.insert_item(
            "jellyfin",
            {
                "id": "x",
                "library": "剧集",
                "type": "series",
                "title": "TT",
                "originalTitle": "TT O",
                "year": 2020,
                "tmdbid": 1668,
                "path": "/t/TT",
                "note": "",
            },
        )
        # 全部 int 入参（PG 下历史崩溃路径）
        item = repo.query_item(server_type="jellyfin", title="TT", year=2020, tmdbid=1668)
        assert item is not None and item.TMDBID == "1668" and item.YEAR == "2020"

    def test_query_item_no_match_returns_none(self, repo):
        assert repo.query_item(server_type="emby", title="不存在", tmdbid=0) is None
