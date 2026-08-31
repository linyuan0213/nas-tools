"""异步刮削队列服务 — 将转移/同步链路中的刮削移出热路径，后台限并发执行."""

import log
from app.infrastructure.thread import ThreadExecutor
from app.media.scraper import Scraper
from app.utils import ExceptionUtils


class ScrapeQueueService:
    """异步刮削队列服务.

    转移（数据移动）与刮削（NFO/图片/FFmpeg）解耦：
    - submit_file_scrape / submit_folder_scrape 非阻塞提交
    - 独立命名线程池限并发（默认 3）；图片下载另有全局信号量限速
    - 刮削失败仅记日志，不阻塞主流程；重启丢失的任务由整库/目录刮削兜底
    """

    def __init__(self, scraper: Scraper, max_workers: int = 3):
        self._scraper = scraper
        self._executor = ThreadExecutor.named("scrape", max_workers=max_workers)

    def submit_file_scrape(self, media, dir_path: str, file_name: str, file_ext: str, dst_backend=None) -> None:
        """提交单文件刮削任务（非阻塞）."""
        # 深拷贝隔离 media，避免异步刮削与转移线程消息聚合并发修改同一对象
        self._executor.submit(
            self._scrape_file, media.model_copy(deep=True), dir_path, file_name, file_ext, dst_backend
        )

    def submit_folder_scrape(self, path: str, dst_backend=None, mode: str = "force_all") -> None:
        """提交目录刮削任务（非阻塞）."""
        self._executor.submit(self._scrape_folder, path, dst_backend, mode)

    def _scrape_file(self, media, dir_path: str, file_name: str, file_ext: str, dst_backend) -> None:
        try:
            self._scraper.gen_scraper_files(
                media=media,
                dir_path=dir_path,
                file_name=file_name,
                file_ext=file_ext,
                dst_backend=dst_backend,
            )
        except Exception as e:
            ExceptionUtils.exception_traceback(e)
            log.error(f"[ScrapeQueue]单文件刮削失败 {dir_path}/{file_name}: {e}")

    def _scrape_folder(self, path: str, dst_backend, mode: str) -> None:
        try:
            self._scraper.folder_scraper(path=path, mode=mode, dst_backend=dst_backend)
        except Exception as e:
            ExceptionUtils.exception_traceback(e)
            log.error(f"[ScrapeQueue]目录刮削失败 {path}: {e}")
