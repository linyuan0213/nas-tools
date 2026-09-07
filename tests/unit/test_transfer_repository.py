"""TransferRepository.get_transfer_series_statistics 回归测试."""

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.db.models import TRANSFERHISTORY, Base
from app.db.repositories.transfer_repository import TransferRepository
from app.db.session import SessionManager


@pytest.fixture
def repo():
    engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False})
    Base.metadata.create_all(engine)
    manager = SessionManager()
    manager._engine = engine
    manager._factory = sessionmaker(bind=engine)
    TransferRepository._session_manager = manager
    yield TransferRepository()
    engine.dispose()


def _insert(repo: TransferRepository, mtype: str, tmdbid: int, date: str) -> None:
    with repo.session() as db:
        db.add(
            TRANSFERHISTORY(
                MODE="link",
                TYPE=mtype,
                CATEGORY="",
                TMDBID=tmdbid,
                TITLE=f"title-{tmdbid}",
                YEAR="2024",
                SEASON_EPISODE="S01E01",
                SOURCE="",
                SOURCE_PATH="/src",
                SOURCE_FILENAME="f.mkv",
                DEST="",
                DEST_PATH="/dst",
                DEST_FILENAME="f.mkv",
                DATE=date,
            )
        )
        db.commit()


class TestGetTransferSeriesStatistics:
    def test_distinct_series_per_day(self, repo):
        _insert(repo, "tv", 101, "2024-01-01 10:00:00")
        _insert(repo, "tv", 101, "2024-01-01 11:00:00")
        _insert(repo, "tv", 102, "2024-01-01 12:00:00")
        _insert(repo, "tv", 103, "2024-01-02 09:00:00")
        result = repo.get_transfer_series_statistics(days=0)
        assert result == [("2024-01-01", 2), ("2024-01-02", 1)]

    def test_ignores_movie_and_zero_tmdbid(self, repo):
        _insert(repo, "movie", 201, "2024-01-01 10:00:00")
        _insert(repo, "tv", 0, "2024-01-01 10:00:00")
        _insert(repo, "tv", 202, "2024-01-01 10:00:00")
        result = repo.get_transfer_series_statistics(days=0)
        assert result == [("2024-01-01", 1)]

    def test_empty(self, repo):
        assert repo.get_transfer_series_statistics(days=0) == []
