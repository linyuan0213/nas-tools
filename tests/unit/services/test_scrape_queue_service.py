"""ScrapeQueueService 异步刮削队列单元测试."""

import threading
from unittest.mock import MagicMock

from app.domain.mediatypes import MediaType
from app.infrastructure.thread import ThreadExecutor
from app.media.models import MediaInfo
from app.services.scrape_queue_service import ScrapeQueueService


class TestScrapeQueueService:
    def teardown_method(self):
        ThreadExecutor.reset_instance("scrape")

    def test_submit_file_scrape_executes_async(self):
        scraper = MagicMock()
        done = threading.Event()
        scraper.gen_scraper_files.side_effect = lambda **kwargs: done.set()
        svc = ScrapeQueueService(scraper=scraper, max_workers=1)

        media = MediaInfo(title="Test", type=MediaType.MOVIE)
        svc.submit_file_scrape(media, "/dst", "Test.mkv", ".mkv")

        assert done.wait(timeout=5)
        scraper.gen_scraper_files.assert_called_once()
        call_kwargs = scraper.gen_scraper_files.call_args.kwargs
        assert call_kwargs["dir_path"] == "/dst"
        assert call_kwargs["file_name"] == "Test.mkv"

    def test_submit_file_scrape_isolates_media_copy(self):
        scraper = MagicMock()
        done = threading.Event()

        def capture(media, **kwargs):
            captured.append(media)
            done.set()

        captured = []
        scraper.gen_scraper_files.side_effect = capture
        svc = ScrapeQueueService(scraper=scraper, max_workers=1)

        media = MediaInfo(title="Test", type=MediaType.MOVIE)
        svc.submit_file_scrape(media, "/dst", "Test.mkv", ".mkv")
        assert done.wait(timeout=5)
        assert len(captured) == 1
        assert captured[0] is not media  # 深拷贝隔离，避免与转移线程共享对象

    def test_submit_folder_scrape_executes_async(self):
        scraper = MagicMock()
        done = threading.Event()
        scraper.folder_scraper.side_effect = lambda **kwargs: done.set()
        svc = ScrapeQueueService(scraper=scraper, max_workers=1)

        svc.submit_folder_scrape("/media/Test", mode="force_all")
        assert done.wait(timeout=5)
        scraper.folder_scraper.assert_called_once_with(path="/media/Test", mode="force_all", dst_backend=None)

    def test_scrape_failure_does_not_raise(self):
        scraper = MagicMock()
        scraper.gen_scraper_files.side_effect = RuntimeError("boom")
        svc = ScrapeQueueService(scraper=scraper, max_workers=1)

        media = MediaInfo(title="Test", type=MediaType.MOVIE)
        svc.submit_file_scrape(media, "/dst", "Test.mkv", ".mkv")

        # 不抛异常即为通过；等待任务结束
        import time

        time.sleep(0.5)
