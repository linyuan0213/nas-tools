"""失败重试管理组件."""

import datetime

import log
from app.core.exceptions import RepositoryError, ServiceError
from app.infrastructure.cache_system import get_cache_manager


class RetryManager:
    """失败重试管理组件"""

    def __init__(self, core):
        self._core = core

    def _get_retry_cache(self):
        """获取重试计数缓存（内存/Redis自动降级）"""
        if self._core._retry_cache is None:
            self._core._retry_cache = get_cache_manager().get_or_create(
                "scheduler_retry", cache_type="tiered", maxsize=1000
            )
        return self._core._retry_cache

    def _get_retry_key(self, job_id: str) -> str:
        """获取重试计数的缓存 key"""
        return f"scheduler:retry:{self._core._instance_id}:{job_id}"

    def _get_retry_count(self, job_id: str) -> int:
        """获取任务重试次数"""
        try:
            cache = self._get_retry_cache()
            retry_key = self._get_retry_key(job_id)
            count = cache.get(retry_key)
            return int(count) if count is not None else 0
        except (ServiceError, RepositoryError):
            raise
        except Exception as e:
            log.error(f"获取重试次数失败 {job_id}: {e}")
            return 0

    def _set_retry_count(self, job_id: str, count: int) -> bool:
        """设置任务重试次数"""
        try:
            cache = self._get_retry_cache()
            retry_key = self._get_retry_key(job_id)
            cache.set(retry_key, count, ttl=3600)  # 1小时过期
            return True
        except (ServiceError, RepositoryError):
            raise
        except Exception as e:
            log.error(f"设置重试次数失败 {job_id}: {e}")
            return False

    def _clear_retry_count(self, job_id: str) -> bool:
        """清除任务重试次数"""
        try:
            cache = self._get_retry_cache()
            retry_key = self._get_retry_key(job_id)
            cache.delete(retry_key)
            return True
        except (ServiceError, RepositoryError):
            raise
        except Exception as e:
            log.error(f"清除重试次数失败 {job_id}: {e}")
            return False

    def _retry_failed_job(self, job_id: str) -> bool:
        """重试失败的任务

        使用延迟调度方式重新执行失败的任务，
        最多重试 MAX_RETRY_COUNT 次。

        Args:
            job_id: 任务 ID

        Returns:
            是否成功安排重试
        """
        job = self._core.get_job(job_id)
        if not job:
            log.warn(f"_retry_failed_job: 任务 {job_id} 不存在，无法重试")
            return False

        # 检查重试次数
        retry_count = self._get_retry_count(job_id)

        if retry_count >= self._core.MAX_RETRY_COUNT:
            log.error(f"任务 {job_id} 已达到最大重试次数 {self._core.MAX_RETRY_COUNT}")
            self._clear_retry_count(job_id)
            return False

        # 增加重试计数
        self._set_retry_count(job_id, retry_count + 1)

        # 更新统计
        stats = self._core._stats_collector._get_job_stats(job_id)
        stats.record_retry()

        # 计算重试延迟（指数退避）
        delay = self._core.RETRY_DELAY * (2**retry_count)
        next_run_time = datetime.datetime.now() + datetime.timedelta(seconds=delay)

        try:
            if not self._core._scheduler:
                return False
            # 使用 add_job 创建一次性重试任务
            retry_job_id = f"{job_id}_retry_{retry_count + 1}"
            jobstore = getattr(job, "_jobstore_alias", "default")
            self._core._scheduler.add_job(
                func=job.func,
                args=job.args,
                kwargs=job.kwargs,
                trigger="date",
                run_date=next_run_time,
                id=retry_job_id,
                jobstore=jobstore,
                replace_existing=True,
                misfire_grace_time=60,
            )

            log.info(
                f"任务 {job_id} 已安排重试 #{retry_count + 1}, "
                f"将在 {delay} 秒后执行 ({next_run_time.strftime('%Y-%m-%d %H:%M:%S')})"
            )
            return True

        except (ServiceError, RepositoryError):
            raise
        except Exception as e:
            log.error(f"安排任务 {job_id} 重试失败: {e}")
            return False
