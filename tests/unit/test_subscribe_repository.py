"""Tests for app.db.repositories.subscribe_repository update defaults."""

from unittest.mock import MagicMock, patch

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
