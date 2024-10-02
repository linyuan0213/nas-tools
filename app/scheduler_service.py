import os

import log

from apscheduler.executors.pool import ThreadPoolExecutor
from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.jobstores.memory import MemoryJobStore
from apscheduler.util import undefined

from app.utils.commons import SingletonMeta
from config import Config
from app.utils import ExceptionUtils, RedisStore
from app.queue import scheduler_queue


class SchedulerService(metaclass=SingletonMeta):
    SCHEDULER = None
    INSTANCE = ""
    redis_store = None
    _jobstores = {
        'default': MemoryJobStore(),
        'brushtask': MemoryJobStore(),
        'rsscheck': MemoryJobStore(),
        'torrent_remove': MemoryJobStore(),
        'download': MemoryJobStore(),
        'plugin': MemoryJobStore()
    }

    def __init__(self):
        self.INSTANCE = os.environ.get('SERVER_INSTANCE')
        self.redis_store = RedisStore()
        self.SCHEDULER = None

    def start_job(self, task):
        """
        启动单个定时任务
        task = {
            'job_id':
            'jobstore':
            'func':
            'args':
            'trigger':
            'run_date':
            'seconds':
        }
        """
        if not task:
            return

        if task.get('trigger') == 'interval':
            if task.get('hours'):
                trigger_args = {
                    'hours': task.get('hours')
                }
            if task.get('minutes'):
                trigger_args = {
                    'minutes': task.get('minutes')
                }
            if task.get('seconds'):
                trigger_args = {
                    'seconds': task.get('seconds')
                }

            next_run_time = task.get("next_run_time")
            if not next_run_time:
                next_run_time = undefined

            return self.SCHEDULER.add_job(func=task.get("func"), args=task.get("args"),
                                          trigger=task.get("trigger"),
                                          **trigger_args,
                                          id=task.get("job_id"),
                                          next_run_time=next_run_time,
                                          jobstore=task.get('jobstore'),
                                          replace_existing=True)
        elif task.get('trigger') == 'date':
            return self.SCHEDULER.add_job(func=task.get("func"), args=task.get("args"),
                                          trigger=task.get("trigger"),
                                          id=task.get("job_id"),
                                          run_date=task.get("run_date"),
                                          jobstore=task.get('jobstore'),
                                          replace_existing=True)
        else:
            return self.SCHEDULER.add_job(func=task.get("func"), args=task.get("args"),
                                          trigger=task.get("trigger"),
                                          id=task.get("job_id"),
                                          jobstore=task.get('jobstore'),
                                          replace_existing=True)

    def print_jobs(self, jobstore=None):
        """
        根据不同的 jobstore 打印不同的任务
        """
        if not self.SCHEDULER:
            return

        if jobstore:
            self.SCHEDULER.print_jobs(jobstore=jobstore)
        else:
            self.SCHEDULER.print_jobs()

    def remove_all_jobs(self, jobstore=None):
        """
        根据不同的 jobstore 移除任务
        """
        if not self.SCHEDULER:
            return

        if jobstore:
            self.SCHEDULER.remove_all_jobs(jobstore=jobstore)
        else:
            self.SCHEDULER.remove_all_jobs()

    def get_jobs(self, jobstore=None):
        """
        根据不同的 jobstore 获取任务
        """
        if not self.SCHEDULER:
            return

        if jobstore:
            return self.SCHEDULER.get_jobs(jobstore=jobstore)
        else:
            return self.SCHEDULER.get_jobs()

    def get_job(self, job_id, jobstore=None):
        """
        根据 job_id 和jobstore 获取任务
        """
        if not self.SCHEDULER:
            return

        return self.SCHEDULER.get_job(job_id=job_id, jobstore=jobstore)

    def remove_job(self, job_id, jobstore=None):
        """
        根据 job_id 和jobstore 删除任务
        """
        if not self.SCHEDULER:
            return

        return self.SCHEDULER.remove_job(job_id=job_id, jobstore=jobstore)

    def start_service(self):
        """
        启动服务
        """
        try:
            scheduler_queue.clear()
            self.SCHEDULER = BackgroundScheduler(timezone=Config().get_timezone(),
                                                 jobstores=self._jobstores,
                                                 executors={
                                                     'default': ThreadPoolExecutor(50)},
                                                 job_defaults={
                                                     'coalesce': True, 'max_instances': 100, 'misfire_grace_time': None}
                                                 )
            self.SCHEDULER.start()
        except Exception as e:
            ExceptionUtils.exception_traceback(e)

    def stop_service(self):
        """
        停止定时服务
        """
        try:
            if self.SCHEDULER:
                self.SCHEDULER.remove_all_jobs()
                self.SCHEDULER.shutdown()
                self.SCHEDULER = None
        except Exception as e:
            ExceptionUtils.exception_traceback(e)
