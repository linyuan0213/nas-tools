"""Tests for app.services.subscribe coordinator, search engine, and strategies."""

from unittest.mock import MagicMock, patch

from app.domain.mediatypes import MediaType
from app.services.subscribe.coordinator import DownloadCoordinator
from app.services.subscribe.search_engine import SubscribeSearchEngine
from app.services.subscribe.strategies.indexer_search import IndexerSearchStrategy
from app.services.subscribe.strategies.queue_search import QueueSearchStrategy
from app.services.subscribe.strategies.rss_feed import RssFeedStrategy


class TestDownloadCoordinator:
    """Test suite for DownloadCoordinator."""

    def _make_media(self, tmdb_id="123", season="S01"):
        media = MagicMock()
        media.tmdb_id = tmdb_id
        media.get_season_string.return_value = season
        return media

    def test_try_acquire_success(self):
        lock_manager = MagicMock()
        lock = MagicMock()
        lock.acquire.return_value = True
        lock_manager.create_lock.return_value = lock
        coord = DownloadCoordinator(lock_manager=lock_manager)
        media = self._make_media()
        assert coord.try_acquire(media) is True
        lock_manager.create_lock.assert_called_once_with("subscribe:download:123:S01", ttl_seconds=300)

    def test_try_acquire_already_held(self):
        lock_manager = MagicMock()
        lock = MagicMock()
        lock.acquire.return_value = True
        lock_manager.create_lock.return_value = lock
        coord = DownloadCoordinator(lock_manager=lock_manager)
        media = self._make_media()
        coord.try_acquire(media)
        result = coord.try_acquire(media)
        assert result is True
        assert lock_manager.create_lock.call_count == 2

    def test_try_acquire_failure(self):
        lock_manager = MagicMock()
        lock = MagicMock()
        lock.acquire.return_value = False
        lock_manager.create_lock.return_value = lock
        coord = DownloadCoordinator(lock_manager=lock_manager)
        media = self._make_media()
        assert coord.try_acquire(media) is False

    def test_release(self):
        lock_manager = MagicMock()
        lock = MagicMock()
        lock.acquire.return_value = True
        lock_manager.create_lock.return_value = lock
        coord = DownloadCoordinator(lock_manager=lock_manager)
        media = self._make_media()
        coord.try_acquire(media)
        coord.release(media)
        lock.release.assert_called_once()

    def test_is_locked_local(self):
        lock_manager = MagicMock()
        lock = MagicMock()
        lock.acquire.return_value = True
        lock_manager.create_lock.return_value = lock
        coord = DownloadCoordinator(lock_manager=lock_manager)
        media = self._make_media()
        coord.try_acquire(media)
        assert coord.is_locked(media) is True

    def test_is_locked_not_held(self):
        lock_manager = MagicMock()
        lock = MagicMock()
        lock.acquire.return_value = True
        lock_manager.create_lock.return_value = lock
        coord = DownloadCoordinator(lock_manager=lock_manager)
        media = self._make_media()
        assert coord.is_locked(media) is False

    def test_is_locked_remote_held(self):
        lock_manager = MagicMock()
        local_lock = MagicMock()
        local_lock.acquire.return_value = False
        lock_manager.create_lock.return_value = local_lock
        coord = DownloadCoordinator(lock_manager=lock_manager)
        media = self._make_media()
        assert coord.is_locked(media) is True


class TestSubscribeSearchEngine:
    """Test suite for SubscribeSearchEngine facade."""

    def test_subscribe_search_all(self):
        indexer = MagicMock()
        queue = MagicMock()
        engine = SubscribeSearchEngine(indexer_strategy=indexer, queue_strategy=queue)
        engine.subscribe_search_all()
        indexer.run.assert_called_once()
        queue.run.assert_not_called()

    def test_subscribe_search_state_r(self):
        indexer = MagicMock()
        queue = MagicMock()
        engine = SubscribeSearchEngine(indexer_strategy=indexer, queue_strategy=queue)
        engine.subscribe_search(state="R")
        indexer.run.assert_called_once()
        queue.run.assert_not_called()

    def test_subscribe_search_state_d(self):
        indexer = MagicMock()
        queue = MagicMock()
        engine = SubscribeSearchEngine(indexer_strategy=indexer, queue_strategy=queue)
        engine.subscribe_search(state="D")
        queue.run.assert_called_once()
        indexer.run.assert_not_called()

    def test_subscribe_search_movie_state_r(self):
        indexer = MagicMock()
        queue = MagicMock()
        engine = SubscribeSearchEngine(indexer_strategy=indexer, queue_strategy=queue)
        engine.subscribe_search_movie(rssid=1, state="R")
        indexer._search_movies.assert_called_once_with(state="R", rssid=1)

    def test_subscribe_search_movie_state_d(self):
        indexer = MagicMock()
        queue = MagicMock()
        engine = SubscribeSearchEngine(indexer_strategy=indexer, queue_strategy=queue)
        engine.subscribe_search_movie(rssid=1, state="D")
        queue._search_movies.assert_called_once_with(state="D", rssid=1)

    def test_subscribe_search_tv_state_r(self):
        indexer = MagicMock()
        queue = MagicMock()
        engine = SubscribeSearchEngine(indexer_strategy=indexer, queue_strategy=queue)
        engine.subscribe_search_tv(rssid=1, state="R")
        indexer._search_tvs.assert_called_once_with(state="R", rssid=1)

    def test_subscribe_search_tv_state_d(self):
        indexer = MagicMock()
        queue = MagicMock()
        engine = SubscribeSearchEngine(indexer_strategy=indexer, queue_strategy=queue)
        engine.subscribe_search_tv(rssid=1, state="D")
        queue._search_tvs.assert_called_once_with(state="D", rssid=1)


class TestIndexerSearchStrategy:
    """Test suite for IndexerSearchStrategy."""

    def test_run_acquires_lock(self):
        with patch("app.services.subscribe.strategy_lock.get_lock_manager") as mock_lm:
            lock = MagicMock()
            lock.acquire.return_value = True
            mock_lm.return_value.create_lock.return_value = lock
            svc = MagicMock()
            strategy = IndexerSearchStrategy(
                service=svc,
                searcher=MagicMock(),
                media_service=MagicMock(),
                media_cache=MagicMock(),
                downloader=MagicMock(),
                filter_service=MagicMock(),
                message=MagicMock(),
                movie_repo=MagicMock(),
                tv_repo=MagicMock(),
            )
            strategy._search_movies = MagicMock()
            strategy._search_tvs = MagicMock()
            strategy.run()
            lock.acquire.assert_called_once()
            lock.release.assert_called_once()

    def test_run_skips_when_locked(self):
        with patch("app.services.subscribe.strategy_lock.get_lock_manager") as mock_lm:
            lock = MagicMock()
            lock.acquire.return_value = False
            mock_lm.return_value.create_lock.return_value = lock
            strategy = IndexerSearchStrategy(
                service=MagicMock(),
                searcher=MagicMock(),
                media_service=MagicMock(),
                media_cache=MagicMock(),
                downloader=MagicMock(),
                filter_service=MagicMock(),
                message=MagicMock(),
                movie_repo=MagicMock(),
                tv_repo=MagicMock(),
            )
            strategy._search_movies = MagicMock()
            strategy.run()
            strategy._search_movies.assert_not_called()


class TestQueueSearchStrategy:
    """Test suite for QueueSearchStrategy."""

    def test_run_acquires_lock(self):
        with patch("app.services.subscribe.strategy_lock.get_lock_manager") as mock_lm:
            lock = MagicMock()
            lock.acquire.return_value = True
            mock_lm.return_value.create_lock.return_value = lock
            strategy = QueueSearchStrategy(
                service=MagicMock(),
                searcher=MagicMock(),
                media_service=MagicMock(),
                media_cache=MagicMock(),
                downloader=MagicMock(),
                filter_service=MagicMock(),
                message=MagicMock(),
                movie_repo=MagicMock(),
                tv_repo=MagicMock(),
            )
            strategy._search_movies = MagicMock()
            strategy._search_tvs = MagicMock()
            strategy.run()
            lock.acquire.assert_called_once()
            lock.release.assert_called_once()

    def test_run_skips_when_locked(self):
        with patch("app.services.subscribe.strategy_lock.get_lock_manager") as mock_lm:
            lock = MagicMock()
            lock.acquire.return_value = False
            mock_lm.return_value.create_lock.return_value = lock
            strategy = QueueSearchStrategy(
                service=MagicMock(),
                searcher=MagicMock(),
                media_service=MagicMock(),
                media_cache=MagicMock(),
                downloader=MagicMock(),
                filter_service=MagicMock(),
                message=MagicMock(),
                movie_repo=MagicMock(),
                tv_repo=MagicMock(),
            )
            strategy._search_movies = MagicMock()
            strategy.run()
            strategy._search_movies.assert_not_called()


class TestRssFeedStrategy:
    """Test suite for RssFeedStrategy."""

    def _make_strategy(self):
        return RssFeedStrategy(
            media=MagicMock(),
            downloader=MagicMock(),
            sites=MagicMock(),
            siteconf=MagicMock(),
            download_repo=MagicMock(),
            rss_repo=MagicMock(),
            rsshelper=MagicMock(),
            subscribe=MagicMock(),
            matcher=MagicMock(),
            message=MagicMock(),
            coordinator=None,
        )

    def test_run_lock_not_acquired(self):
        strategy = self._make_strategy()
        with patch("app.services.subscribe.strategy_lock.get_lock_manager") as mock_lm:
            lock = MagicMock()
            lock.acquire.return_value = False
            mock_lm.return_value.create_lock.return_value = lock
            strategy.run()
            lock.acquire.assert_called_once()

    def test_do_rss_poll_no_rss_sites(self):
        strategy = self._make_strategy()
        strategy.sites.get_sites.return_value = []  # type: ignore[union-attr]
        strategy.run = lambda: strategy._do_rss_poll()  # type: ignore[method-assign]
        strategy._do_rss_poll()

    def test_do_rss_poll_no_subscriptions(self):
        strategy = self._make_strategy()
        strategy.sites.get_sites.return_value = [{"name": "site1", "rssurl": "http://rss"}]  # type: ignore[union-attr]
        strategy.subscribe.get_subscribe_movies.return_value = {}  # type: ignore[union-attr]
        strategy.subscribe.get_subscribe_tvs.return_value = {}  # type: ignore[union-attr]
        strategy.run = lambda: strategy._do_rss_poll()  # type: ignore[method-assign]
        strategy._do_rss_poll()

    def test_download_matched_torrents_empty(self):
        strategy = self._make_strategy()
        strategy._download_matched_torrents([], {})
        strategy.downloader.batch_download.assert_not_called()  # type: ignore[union-attr]

    def test_download_matched_torrents_no_subscribe(self):
        strategy = self._make_strategy()
        strategy.subscribe = None
        media = MagicMock()
        strategy._download_matched_torrents([media], {})

    def test_download_matched_torrents_with_coordinator(self):
        strategy = self._make_strategy()
        coord = MagicMock()
        coord.try_acquire.return_value = True
        strategy._coordinator = coord
        media = MagicMock()
        media.type = MagicMock()
        media.type.value = "movie"
        media.total_episodes = 0
        media.begin_season = None
        media.begin_episode = None
        media.get_episode_list.return_value = []
        media.res_order = 1
        media.site_order = 1
        media.seeders = 1
        strategy.downloader.batch_download.return_value = ([], [])  # type: ignore[union-attr]
        strategy._download_matched_torrents([media], {})
        coord.try_acquire.assert_called_once()

    def test_get_default_rss_sites_no_system_config(self):
        strategy = self._make_strategy()
        strategy._system_config = None
        assert strategy._get_default_rss_sites(MediaType.TV) == []

    def test_get_default_rss_sites_tv(self):
        strategy = self._make_strategy()
        sys_config = MagicMock()
        sys_config.get.return_value = {"rss_sites": ["siteA", "siteB"]}
        strategy._system_config = sys_config
        assert strategy._get_default_rss_sites(MediaType.TV) == ["siteA", "siteB"]

    def test_get_default_rss_sites_movie(self):
        strategy = self._make_strategy()
        sys_config = MagicMock()
        sys_config.get.return_value = {"rss_sites": ["siteM"]}
        strategy._system_config = sys_config
        assert strategy._get_default_rss_sites(MediaType.MOVIE) == ["siteM"]

    def test_get_default_rss_sites_invalid_setting(self):
        strategy = self._make_strategy()
        sys_config = MagicMock()
        sys_config.get.return_value = "not_a_dict"
        strategy._system_config = sys_config
        assert strategy._get_default_rss_sites(MediaType.TV) == []

    def test_get_default_rss_sites_exception_returns_empty(self):
        strategy = self._make_strategy()
        sys_config = MagicMock()
        sys_config.get.side_effect = RuntimeError("db error")
        strategy._system_config = sys_config
        assert strategy._get_default_rss_sites(MediaType.TV) == []
