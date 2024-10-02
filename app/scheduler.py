import datetime
import time

import pytz

from threading import Lock

import log
from app.helper import MetaHelper, ThreadHelper, SubmoduleHelper
from app.mediaserver import MediaServer
from app.rss import Rss
from app.sites import SiteUserInfo
from app.subscribe import Subscribe
from app.sync import Sync
from app.brushtask import BrushTask
from app.downloader import Downloader
from app.rsschecker import RssChecker
from app.torrentremover import TorrentRemover
from app.utils import SchedulerUtils, StringUtils
from app.utils.reflect_utils import ReflectUtils
from app.utils.commons import SingletonMeta
from config import METAINFO_SAVE_INTERVAL, \
    SYNC_TRANSFER_INTERVAL, RSS_CHECK_INTERVAL, \
    RSS_REFRESH_TMDB_INTERVAL, META_DELETE_UNKNOWN_INTERVAL, REFRESH_WALLPAPER_INTERVAL, Config
from web.backend.wallpaper import get_login_wallpaper

from app.scheduler_service import SchedulerService
from app.queue import scheduler_queue


class Scheduler(metaclass=SingletonMeta):
    scheduler = None
    _pt = None
    _douban = None
    _media = None
    _jobstore = 'default'
    _lock = Lock()

    def __init__(self):
        self.init_config()

    def init_config(self):
        self._pt = Config().get_config('pt')
        self._media = Config().get_config('media')
        self.scheduler = SchedulerService()
        self.scheduler.start_service()
        self.run_service()

    def run_service(self):
        """
        读取配置，启动定时服务
        """

        if not self.scheduler:
            return

        if self._pt:
            # 数据统计
            ptrefresh_date_cron = self._pt.get('ptrefresh_date_cron')
            if ptrefresh_date_cron:
                tz = pytz.timezone(Config().get_timezone())
                scheduler_queue.put({
                    "func_str": "SiteUserInfo.refresh_site_data_now",
                    "job_id": "SiteUserInfo.refresh_site_data_now",
                    "func_desc": "数据统计",
                    "cron": str(ptrefresh_date_cron),
                    "next_run_time": datetime.datetime.now(tz) + datetime.timedelta(minutes=1)
                })

            # RSS下载器
            pt_check_interval = self._pt.get('pt_check_interval')
            if pt_check_interval:
                if isinstance(pt_check_interval, str) and pt_check_interval.isdigit():
                    pt_check_interval = int(pt_check_interval)
                else:
                    try:
                        pt_check_interval = round(float(pt_check_interval))
                    except Exception as e:
                        log.error("RSS订阅周期 配置格式错误：%s" % str(e))
                        pt_check_interval = 0
                if pt_check_interval:
                    if pt_check_interval < 300:
                        pt_check_interval = 300

                    scheduler_queue.put({
                        "func_str": "Rss.rssdownload",
                        "args": [],
                        "job_id": "Rss.rssdownload",
                        "trigger": "interval",
                        "seconds": pt_check_interval,
                        "jobstore": self._jobstore
                    })
                    log.info("RSS订阅服务启动")

            # RSS订阅定时搜索
            search_rss_interval = self._pt.get('search_rss_interval')
            if search_rss_interval:
                if isinstance(search_rss_interval, str) and search_rss_interval.isdigit():
                    search_rss_interval = int(search_rss_interval)
                else:
                    try:
                        search_rss_interval = round(float(search_rss_interval))
                    except Exception as e:
                        log.error("订阅定时搜索周期 配置格式错误：%s" % str(e))
                        search_rss_interval = 0
                if search_rss_interval:
                    if search_rss_interval < 2:
                        search_rss_interval = 2

                    scheduler_queue.put({
                        "func_str": "Subscribe.subscribe_search_all",
                        "args": [],
                        "job_id": "Subscribe.subscribe_search_all",
                        "trigger": "interval",
                        "hours": search_rss_interval,
                        "jobstore": self._jobstore
                    })

                    log.info("订阅定时搜索服务启动")

        # # 媒体库同步
        if self._media:
            mediasync_interval = self._media.get("mediasync_interval")
            if mediasync_interval:
                if isinstance(mediasync_interval, str):
                    if mediasync_interval.isdigit():
                        mediasync_interval = int(mediasync_interval)
                    else:
                        try:
                            mediasync_interval = round(
                                float(mediasync_interval))
                        except Exception as e:
                            log.info("豆瓣同步服务启动失败：%s" % str(e))
                            mediasync_interval = 0
                if mediasync_interval:
                    scheduler_queue.put({
                        "func_str": "MediaServer.sync_mediaserver",
                        "args": [],
                        "job_id": "MediaServer.sync_mediaserver",
                        "trigger": "interval",
                        "hours": mediasync_interval,
                        "jobstore": self._jobstore
                    })
                    log.info("媒体库同步服务启动")

        # 元数据定时保存
        scheduler_queue.put({
            "func_str": "MetaHelper.save_meta_data",
                        "args": [],
                        "trigger": "interval",
                        "job_id": "MetaHelper.save_meta_data",
                        "seconds": METAINFO_SAVE_INTERVAL,
                        "jobstore": self._jobstore
        })

        # 定时把队列中的监控文件转移走
        scheduler_queue.put({
            "func_str": "Sync.transfer_mon_files",
                        "args": [],
                        "job_id": "Sync.transfer_mon_files",
                        "trigger": "interval",
                        "seconds": SYNC_TRANSFER_INTERVAL,
                        "jobstore": self._jobstore
        })

        # RSS队列中搜索
        scheduler_queue.put({
            "func_str": "Subscribe.subscribe_search",
                        "args": [],
                        "job_id": "Subscribe.subscribe_search",
                        "trigger": "interval",
                        "seconds": RSS_CHECK_INTERVAL,
                        "jobstore": self._jobstore
        })

        # 豆瓣RSS转TMDB，定时更新TMDB数据
        scheduler_queue.put({
            "func_str": "Subscribe.refresh_rss_metainfo",
                        "args": [],
                        "job_id": "Subscribe.refresh_rss_metainfo",
                        "trigger": "interval",
                        "hours": RSS_REFRESH_TMDB_INTERVAL,
                        "jobstore": self._jobstore
        })

        # 定时清除未识别的缓存
        scheduler_queue.put({
            "func_str": "MetaHelper.delete_unknown_meta",
                        "args": [],
                        "job_id": "MetaHelper.delete_unknown_meta",
                        "trigger": "interval",
                        "hours": META_DELETE_UNKNOWN_INTERVAL,
                        "jobstore": self._jobstore
        })

        # 定时刷新壁纸
        scheduler_queue.put({
            "func_str": "get_login_wallpaper",
                        "args": [],
                        "trigger": "interval",
                        "job_id": "get_login_wallpaper",
                        "hours": REFRESH_WALLPAPER_INTERVAL,
                        "next_run_time": datetime.datetime.now(),
                        "jobstore": self._jobstore
        })

        ThreadHelper().start_thread(self.add_task, ())

    def add_task(self):
        while True:
            data = scheduler_queue.get()
            if not data:
                time.sleep(5)
                continue

            job = None
            func_str = data.get('func_str')
            try:
                if data.get('func_desc'):
                    if data.get('type') == 'plugin':
                        func = ReflectUtils.get_plugin_method(
                            data.get('func_str'))
                    else:
                        func = ReflectUtils.get_func_by_str(
                            __name__, data.get('func_str'))
                    job = SchedulerUtils.start_job(scheduler=self.scheduler.SCHEDULER,
                                                   func=func,
                                                   job_id=data.get('job_id'),
                                                   func_desc=data.get(
                                                       'func_desc'),
                                                   cron=data.get('cron'),
                                                   next_run_time=data.get('next_run_time'))
                else:
                    if data.get('type') == 'plugin':
                        func = ReflectUtils.get_plugin_method(
                            data.get('func_str'))
                        data.pop("func_str")
                        data.pop("type")
                    else:
                        func = ReflectUtils.get_func_by_str(
                            __name__, data.get('func_str'))
                        data.pop("func_str")

                    job = self.scheduler.start_job({
                        "func": func,
                        **data
                    })
                log.info(f'【System】成功添加任务 {job.id}: {job}')
            except Exception as err:
                log.error(f"【System】添加任务失败：{func_str} {str(err)}")

    def stop_service(self):
        self.scheduler.stop_service()
