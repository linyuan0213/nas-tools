"""Cron 表达式解析组件."""

import datetime
import math
import random
from collections.abc import Callable
from typing import Any

from apscheduler.job import Job
from apscheduler.triggers.cron import CronTrigger
from apscheduler.util import undefined

import log
from app.core.exceptions import RepositoryError, ServiceError


class CronParser:
    """Cron 表达式解析组件"""

    def __init__(self, core):
        self._core = core

    def register_smart_cron(
        self,
        job_id: str,
        func: Callable,
        cron: str,
        func_desc: str = "",
        args: tuple | None = None,
        kwargs: dict[str, Any] | None = None,
        jobstore: str = "default",
        next_run_time: Any | None = None,
        max_instances: int = 1,
        misfire_grace_time: int = 300,
        coalesce: bool = True,
        name: str | None = None,
    ) -> Job | None:
        """
        智能注册定时任务，兼容多种 cron 写法：
          1、5位 cron 表达式
          2、时间范围，如08:00-09:00，表示在该时间范围内随机执行一次；
          3、固定时间，如08:00；
          4、间隔小时数，如23.5；
        """
        if not self._core._scheduler:
            log.error("register_smart_cron: 调度器未启动")
            return None

        if not next_run_time:
            next_run_time = undefined

        job = None
        cron = str(cron).strip() if cron else ""
        if not cron:
            return None

        if cron.count(" ") == 4:
            try:
                job = self._core._scheduler.add_job(
                    func=func,
                    args=args or (),
                    kwargs=kwargs or {},
                    id=job_id,
                    name=name,
                    trigger=CronTrigger.from_crontab(cron),
                    next_run_time=next_run_time,
                    replace_existing=True,
                    jobstore=jobstore,
                    max_instances=max_instances,
                    misfire_grace_time=misfire_grace_time,
                    coalesce=coalesce,
                )
            except (ServiceError, RepositoryError):
                raise
            except Exception as e:
                log.info(f"{func_desc}时间cron表达式配置格式错误：{cron} {str(e)}")
        elif "-" in cron:
            try:
                time_range = cron.split("-")
                start_time_range_str = time_range[0]
                end_time_range_str = time_range[1]
                start_time_range_array = start_time_range_str.split(":")
                end_time_range_array = end_time_range_str.split(":")
                start_hour = int(start_time_range_array[0])
                start_minute = int(start_time_range_array[1])
                end_hour = int(end_time_range_array[0])
                end_minute = int(end_time_range_array[1])

                def start_random_job():
                    task_time_count = random.randint(start_hour * 60 + start_minute, end_hour * 60 + end_minute)
                    self._register_range_job(
                        func=func,
                        func_desc=func_desc,
                        job_id=f"{job_id}_1",
                        hour=math.floor(task_time_count / 60),
                        minute=task_time_count % 60,
                        args=args,
                        kwargs=kwargs,
                        jobstore=jobstore,
                        next_run_time=next_run_time,
                        max_instances=max_instances,
                        misfire_grace_time=misfire_grace_time,
                        coalesce=coalesce,
                    )

                job = self._core._scheduler.add_job(
                    start_random_job,
                    "cron",
                    id=job_id,
                    name=name,
                    hour=start_hour,
                    minute=start_minute,
                    next_run_time=next_run_time,
                    replace_existing=True,
                    jobstore=jobstore,
                    max_instances=max_instances,
                    misfire_grace_time=misfire_grace_time,
                    coalesce=coalesce,
                )
                log.info(
                    "{}服务时间范围随机模式启动，起始时间于{}:{}".format(
                        func_desc, str(start_hour).rjust(2, "0"), str(start_minute).rjust(2, "0")
                    )
                )
            except (ServiceError, RepositoryError):
                raise
            except Exception as e:
                log.info(f"{func_desc}时间 时间范围随机模式 配置格式错误：{cron} {str(e)}")
        elif ":" in cron:
            # 支持多个固定时间，逗号分隔，如 00:05,12:00,18:00
            # APScheduler 的 hour/minute 逗号为集合匹配（笛卡尔积），
            # 因此为每个时间分别注册一个 cron job，避免多触发
            try:
                times = [t.strip() for t in cron.split(",") if t.strip()]
                parsed = []
                for t in times:
                    hour, minute = t.split(":")
                    parsed.append((int(hour), int(minute)))
            except (ServiceError, RepositoryError):
                raise
            except Exception as e:
                log.info(f"{func_desc}时间 配置格式错误：{str(e)}")
                parsed = [(0, 0)]
            for idx, (hour, minute) in enumerate(parsed):
                job = self._core._scheduler.add_job(
                    func,
                    "cron",
                    args=args or (),
                    kwargs=kwargs or {},
                    id=f"{job_id}_t{idx}" if len(parsed) > 1 else job_id,
                    name=name,
                    hour=hour,
                    minute=minute,
                    next_run_time=next_run_time,
                    replace_existing=True,
                    jobstore=jobstore,
                    max_instances=max_instances,
                    misfire_grace_time=misfire_grace_time,
                    coalesce=coalesce,
                )
            log.info(f"{func_desc}服务启动")
        else:
            try:
                hours = float(cron)
            except (ServiceError, RepositoryError):
                raise
            except Exception as e:
                log.info(f"{func_desc}时间 配置格式错误：{str(e)}")
                hours = 0
            if hours:
                job = self._core._scheduler.add_job(
                    func,
                    "interval",
                    args=args or (),
                    kwargs=kwargs or {},
                    id=job_id,
                    name=name,
                    hours=hours,
                    next_run_time=next_run_time,
                    replace_existing=True,
                    jobstore=jobstore,
                    max_instances=max_instances,
                    misfire_grace_time=misfire_grace_time,
                    coalesce=coalesce,
                )
                log.info(f"{func_desc}服务启动")
        return job

    def _register_range_job(
        self,
        func,
        func_desc,
        hour,
        minute,
        job_id=None,
        args=None,
        kwargs=None,
        jobstore="default",
        next_run_time=None,
        max_instances=1,
        misfire_grace_time=300,
        coalesce=True,
    ):
        year = datetime.datetime.now().year
        month = datetime.datetime.now().month
        day = datetime.datetime.now().day
        second = random.randint(1, 59)
        log.info(
            f"{func_desc}到时间 即将在{str(year)}-{str(month)}-{str(day)},{str(hour)}:{str(minute)}:{str(second)}执行"
        )
        if hour < 0 or hour > 24:
            hour = -1
        if minute < 0 or minute > 60:
            minute = -1
        if hour < 0 or minute < 0:
            log.warn(f"{func_desc}时间 配置格式错误：不启动任务")
            return
        if not self._core._scheduler:
            return
        self._core._scheduler.add_job(
            func,
            "date",
            id=job_id,
            args=args or (),
            kwargs=kwargs or {},
            run_date=datetime.datetime(year, month, day, hour, minute, second),
            next_run_time=next_run_time,
            replace_existing=True,
            jobstore=jobstore,
            max_instances=max_instances,
            misfire_grace_time=misfire_grace_time,
            coalesce=coalesce,
        )
