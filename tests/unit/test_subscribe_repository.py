"""Tests for app.db.repositories.subscribe_repository update defaults."""

from unittest.mock import MagicMock, patch

from app.db.models.subscribe import SubscribeTvs
from app.db.repositories.subscribe_repository import SubscribeRepository


class TestSubscribeRepositoryUpdateDefaults:
    """Test suite for update_rss_movie/update_rss_tv None handling."""

    @patch("app.db.repositories.subscribe_repository.JsonUtils.dumps", return_value='"[]"')
    def test_update_rss_movie_skips_none_fields(self, _mock_dumps):
        """None 字段不更新（保留原值），仅更新显式提供的字段"""
        repo = SubscribeRepository()
        mock_session = MagicMock()
        mock_query = MagicMock()
        mock_session.__enter__.return_value.query.return_value = mock_query

        with patch.object(repo, "session", return_value=mock_session):
            repo.update_rss_movie(
                rssid=1,
                name="Test",
                save_path=None,
                filter_rule=None,
                download_setting=None,
                fuzzy_match=None,
                over_edition=None,
                rss_sites=["site"],
            )

        update_fields = mock_query.filter.return_value.update.call_args[0][0]
        assert update_fields["NAME"] == "Test"
        assert "SAVE_PATH" not in update_fields
        assert "FILTER_RULE" not in update_fields
        assert "DOWNLOAD_SETTING" not in update_fields
        assert "FUZZY_MATCH" not in update_fields
        assert "OVER_EDITION" not in update_fields

    @patch("app.db.repositories.subscribe_repository.JsonUtils.dumps", return_value='"[]"')
    def test_update_rss_tv_skips_none_fields(self, _mock_dumps):
        """None 字段不更新（保留原值），仅更新显式提供的字段"""
        repo = SubscribeRepository()
        mock_session = MagicMock()
        mock_query = MagicMock()
        mock_session.__enter__.return_value.query.return_value = mock_query

        with patch.object(repo, "session", return_value=mock_session):
            repo.update_rss_tv(
                rssid=1,
                name="Test",
                season=None,
                save_path=None,
                filter_rule=None,
                download_setting=None,
                total_ep=None,
                current_ep=None,
                total=None,
                lack=None,
            )

        update_fields = mock_query.filter.return_value.update.call_args[0][0]
        assert update_fields["NAME"] == "Test"
        assert "SEASON" not in update_fields
        assert "SAVE_PATH" not in update_fields
        assert "FILTER_RULE" not in update_fields
        assert "DOWNLOAD_SETTING" not in update_fields
        assert "TOTAL_EP" not in update_fields
        assert "CURRENT_EP" not in update_fields
        assert "TOTAL" not in update_fields
        assert "LACK" not in update_fields
        assert update_fields["NAME"] == "Test"


class TestUpdateRssTvLackAdvancesCurrentEp:
    """update_rss_tv_lack 同步推进 current_ep（首个待下载 = 缺失集最小值）"""

    def _setup_repo(self):
        from sqlalchemy import create_engine
        from sqlalchemy.orm import sessionmaker

        from app.db.models.base import Base
        from app.db.models.subscribe import SubscribeTvs
        from app.db.session import SessionManager

        engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False})
        Base.metadata.create_all(engine)
        mgr = SessionManager()
        mgr._engine = engine
        mgr._factory = sessionmaker(bind=engine, expire_on_commit=False)
        SubscribeRepository._session_manager = mgr
        with mgr.session_scope() as db:
            db.add(
                SubscribeTvs(
                    NAME="测试剧",
                    YEAR="2023",
                    SEASON="S01",
                    TMDBID="223564",
                    TOTAL_EP=48,
                    CURRENT_EP=26,
                    TOTAL=48,
                    LACK=23,
                    STATE="R",
                )
            )
        return mgr

    def test_advances_to_first_missing(self):
        mgr = self._setup_repo()
        repo = SubscribeRepository()
        repo.update_rss_tv_lack(title=None, year=None, season=None, rssid=1, lack_episodes=[31, 32, 33])
        with mgr.session_scope() as db:
            row = db.query(SubscribeTvs).filter(SubscribeTvs.ID == 1).first()
            assert row.LACK == 3
            assert row.CURRENT_EP == 31  # 首个待下载集推进

    def test_advances_as_episodes_transfer(self):
        """转移 26-30 后缺失集变为 31.. → current_ep 从 26 推进到 31"""
        mgr = self._setup_repo()
        repo = SubscribeRepository()
        # 模拟转移完成：缺失集从 [26..48] 减去已转移 26-30 → [31..48]
        repo.update_rss_tv_lack(title=None, year=None, season=None, rssid=1, lack_episodes=list(range(31, 49)))
        with mgr.session_scope() as db:
            row = db.query(SubscribeTvs).filter(SubscribeTvs.ID == 1).first()
            assert row.LACK == 18
            assert row.CURRENT_EP == 31

    def test_empty_missing_keeps_current_ep(self):
        mgr = self._setup_repo()
        repo = SubscribeRepository()
        repo.update_rss_tv_lack(title=None, year=None, season=None, rssid=1, lack_episodes=[])
        with mgr.session_scope() as db:
            row = db.query(SubscribeTvs).filter(SubscribeTvs.ID == 1).first()
            assert row.LACK == 0
            assert row.CURRENT_EP == 26  # 无缺失集时不改 current_ep（完成态由 STATE 表达）
