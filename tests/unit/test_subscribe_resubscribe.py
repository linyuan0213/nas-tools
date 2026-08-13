"""订阅重订阅续订：结合转移记录与下载记录推导开始集数的回归测试"""

import pytest
from sqlalchemy.orm import sessionmaker

from app.db.engine import get_engine
from app.db.models import DOWNLOADHISTORY, TRANSFERHISTORY, Base
from app.db.repositories.download_repository import DownloadRepository
from app.db.repositories.transfer_repository import TransferRepository


@pytest.fixture(autouse=True)
def _clean_db():
    """每个用例清空全局引擎的表，保证 repo 查询隔离"""
    engine = get_engine()
    Base.metadata.drop_all(engine)
    Base.metadata.create_all(engine)
    yield
    Base.metadata.drop_all(engine)


def _session():
    return sessionmaker(bind=get_engine())()


def _download_row(tmdb: str, se: str, state: str = "completed"):
    return DOWNLOADHISTORY(
        TITLE="t",
        YEAR="",
        TYPE="TV",
        TMDBID=tmdb,
        SE=se,
        VOTE="",
        POSTER="",
        OVERVIEW="",
        TORRENT="",
        ENCLOSURE="",
        SITE="",
        DESC="",
        DOWNLOADER="d",
        DOWNLOAD_ID="x",
        SAVE_PATH="/p",
        STATE=state,
        DATE="",
    )


def _transfer_row(tmdb: int, se: str):
    return TRANSFERHISTORY(
        MODE="link",
        TYPE="TV",
        CATEGORY="",
        TMDBID=tmdb,
        TITLE="t",
        YEAR="",
        SEASON_EPISODE=se,
        SOURCE="",
        SOURCE_PATH="/s",
        SOURCE_FILENAME="f.mkv",
        DEST="/tv",
        DEST_PATH="/tv",
        DEST_FILENAME="f.mkv",
        DST_BACKEND="",
        DATE="",
    )


def test_download_contiguous_basic():
    """下载记录：明确单集（含空格格式），中间缺口截断"""
    s = _session()
    s.add_all(
        [
            _download_row("80748", "S08 E01"),  # 真实 SE 带空格
            _download_row("80748", "S08E02"),
            _download_row("80748", "S08 E04"),  # 缺 E03 → 连续止于 2
            _download_row("80748", "S08E06"),
            _download_row("80748", "S09 E01"),
        ]
    )
    s.commit()
    s.close()
    repo = DownloadRepository()
    assert repo.get_contiguous_completed_episode_by_tmdb(80748, 8) == 2
    assert repo.get_contiguous_completed_episode_by_tmdb(80748, 9) == 1
    assert repo.get_contiguous_completed_episode_by_tmdb(80748, 1) == 0


def test_download_range_counted():
    """下载记录：范围集号全计数"""
    s = _session()
    s.add_all([_download_row("80748", "S08E01"), _download_row("80748", "S08E02-E05")])
    s.commit()
    s.close()
    assert DownloadRepository().get_contiguous_completed_episode_by_tmdb(80748, 8) == 5


def test_download_only_season_pack_is_one():
    """只有季包记录时保守返回 1，而不是整季"""
    s = _session()
    s.add(_download_row("80748", "S08"))
    s.commit()
    s.close()
    assert DownloadRepository().get_contiguous_completed_episode_by_tmdb(80748, 8) == 1


def test_download_incomplete_not_counted():
    """未完成的下载不计入"""
    s = _session()
    s.add_all(
        [
            _download_row("80748", "S08E01", state="completed"),
            _download_row("80748", "S08E02", state="downloading"),
        ]
    )
    s.commit()
    s.close()
    assert DownloadRepository().get_contiguous_completed_episode_by_tmdb(80748, 8) == 1


def test_transfer_contiguous_formats():
    """转移记录：带空格/范围格式"""
    s = _session()
    s.add_all(
        [
            _transfer_row(80748, "S08 E01"),
            _transfer_row(80748, "S08E02"),
            _transfer_row(80748, "S08 E03-E08"),  # 范围 3-8 → 集合 {1..8}
            _transfer_row(80748, "S09 E01"),
            _transfer_row(80748, "S09 E02"),
        ]
    )
    s.commit()
    s.close()
    repo = TransferRepository()
    assert repo.get_contiguous_transferred_episode_by_tmdb(80748, 8) == 8
    assert repo.get_contiguous_transferred_episode_by_tmdb(80748, 9) == 2
    assert repo.get_contiguous_transferred_episode_by_tmdb(80748, 1) == 0


def test_transfer_only_season_pack_is_one():
    s = _session()
    s.add(_transfer_row(80748, "S08"))
    s.commit()
    s.close()
    assert TransferRepository().get_contiguous_transferred_episode_by_tmdb(80748, 8) == 1


def test_combine_takes_max_of_both():
    """结合转移与下载记录：转移到 3，下载到 5 → 取较大值 5"""
    s = _session()
    s.add_all([_transfer_row(80748, "S08 E01"), _transfer_row(80748, "S08 E02"), _transfer_row(80748, "S08 E03")])
    s.commit()
    s.close()
    transfer_ep = TransferRepository().get_contiguous_transferred_episode_by_tmdb(80748, 8)
    assert transfer_ep == 3

    s = _session()
    s.add_all(
        [
            _download_row("80748", "S08E01"),
            _download_row("80748", "S08E02"),
            _download_row("80748", "S08E03"),
            _download_row("80748", "S08E04"),
            _download_row("80748", "S08E05"),
        ]
    )
    s.commit()
    s.close()
    download_ep = DownloadRepository().get_contiguous_completed_episode_by_tmdb(80748, 8)
    assert download_ep == 5
    assert max(transfer_ep, download_ep) == 5
