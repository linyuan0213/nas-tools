import datetime
import os

import pytz

import log
from app.core.constants import (
    RSS_REFRESH_TMDB_INTERVAL,
)
from app.core.exceptions import RepositoryError, ServiceError
from app.core.settings import settings
from app.indexer.core.miss_collector import weekly_miss_review
from app.infrastructure.image_proxy import clean_old_cache
from app.infrastructure.temp import TempCleanup
from app.services.site_parse_health_service import SiteParseHealthService


def _refresh_site_data_now_threaded(thread_executor, site_userinfo):
    """站点数据刷新 — 在独立线程中执行，避免阻塞调度器"""
    thread_executor.submit(site_userinfo.refresh_site_data_now)


# load_default_jobs 注册的默认定时任务 ID（配置热重载时先移除再按新配置注册）
DEFAULT_JOB_IDS = (
    "SiteUserInfo.refresh_site_data_now",
    "SiteUserInfo.refresh_site_data_now_periodic",
    "SubscriptionMonitor.run",
    "MediaServer.sync_mediaserver",
    "Sync.transfer_mon_files",
    "Subscribe.refresh_rss_metainfo",
    "TempCleanup.do_cleanup",
    "IdentifyMiss.weekly_review",
    "ImageProxy.clean_old_cache",
    "AgentMaintenance.daily",
    "SiteParseHealth.daily_check",
)


def reload_default_jobs(scheduler, **deps) -> None:
    """配置热重载：移除默认定时任务后按新配置重新注册。"""
    if not scheduler:
        return
    for job_id in DEFAULT_JOB_IDS:
        try:
            scheduler.remove_job(job_id)
        except Exception as e:
            log.debug(f"[Scheduler]移除任务 {job_id} 失败: {e}")
        # 多时间点 cron 会注册为 {job_id}_t0/_t1... 后缀，一并清理
        try:
            for job in scheduler.get_jobs() or []:
                if job.id.startswith(f"{job_id}_t"):
                    scheduler.remove_job(job.id)
        except Exception as e:
            log.debug(f"[Scheduler]移除多时间任务 {job_id} 失败: {e}")
    load_default_jobs(scheduler, **deps)
    log.info("[Scheduler]默认定时任务已按新配置重新注册")


def _parse_interval(value, min_val=0, default=0):
    """解析配置中的间隔值（支持字符串/数字）."""
    if not value:
        return default
    if isinstance(value, str) and value.isdigit():
        return int(value)
    try:
        return round(float(value))
    except (ServiceError, RepositoryError):
        raise
    except Exception as e:
        log.error(f"配置格式错误：{str(e)}")
        return default


def _parse_health_daily_check(message=None):
    """站点解析健康自检定时任务：注入消息通道用于异常告警推送."""

    def _run():
        try:
            SiteParseHealthService(message=message).check_all()
        except Exception as e:  # noqa: BLE001
            log.error(f"[解析自检]每日任务异常: {e}")

    return _run


def load_default_jobs(
    scheduler,
    *,
    thread_executor,
    site_userinfo,
    subscription_monitor,
    media_server,
    sync_engine,
    subscribe_service,
    knowledge_ingestor=None,
    conversation_store=None,
    plugin_market_service=None,
    message=None,
):
    """
    加载系统默认定时任务
    :param scheduler: SchedulerCore 实例
    """
    if not scheduler:
        return

    _pt = settings.get("pt")
    _subscribe = settings.get("subscribe")
    _media = settings.get("media")
    _jobstore = "default"

    if _pt:
        # 数据统计：每日 00:05 抓取"日界快照"作为当天历史基准（对齐自然日），
        # 使前一天/当天增量精确（见 insert_site_statistics_history）
        ptrefresh_date_cron = _pt.get("ptrefresh_date_cron")
        if ptrefresh_date_cron:
            tz = pytz.timezone(os.environ.get("TZ") or "UTC")
            scheduler.register_smart_cron(
                job_id="SiteUserInfo.refresh_site_data_now",
                func=lambda: _refresh_site_data_now_threaded(thread_executor, site_userinfo),
                name="站点数据统计",
                func_desc="站点数据统计",
                cron=str(ptrefresh_date_cron),
                next_run_time=datetime.datetime.now(tz) + datetime.timedelta(minutes=1),
                jobstore=_jobstore,
            )
        # 实时数据周期刷新：保持当天实时值（SITE_USER_INFO_STATS）接近最新，
        # 不覆盖当天日界快照（insert_site_statistics_history 已跳过）
        scheduler.register_interval(
            job_id="SiteUserInfo.refresh_site_data_now_periodic",
            func=lambda: _refresh_site_data_now_threaded(thread_executor, site_userinfo),
            name="站点数据周期刷新",
            seconds=6 * 3600,
            jobstore=_jobstore,
        )

    # 订阅监控（统一调度器）— 聚合 RSS 轮询、主动搜索、队列搜索
    # 外部调度周期使用三者中最小的 queue_interval（秒），默认 300s
    # 内部 run() 按各自独立间隔控制：queue_interval / rss_interval / search_interval
    subscribe_interval = _parse_interval(_subscribe.get("queue_interval") if _subscribe else None, default=300)
    if subscribe_interval:
        if subscribe_interval < 60:
            subscribe_interval = 60

        scheduler.register_interval(
            job_id="SubscriptionMonitor.run",
            name="订阅监控",
            func=subscription_monitor.run,
            seconds=subscribe_interval,
            jobstore=_jobstore,
        )
        log.info("订阅监控服务启动")

    # 媒体库同步
    if _media:
        mediasync_interval = _media.get("mediasync_interval")
        if mediasync_interval:
            if isinstance(mediasync_interval, str):
                if mediasync_interval.isdigit():
                    mediasync_interval = int(mediasync_interval)
                else:
                    try:
                        mediasync_interval = round(float(mediasync_interval))
                    except (ServiceError, RepositoryError):
                        raise
                    except Exception as e:
                        log.info(f"豆瓣同步服务启动失败：{str(e)}")
                        mediasync_interval = 0
            if mediasync_interval:
                scheduler.register_interval(
                    job_id="MediaServer.sync_mediaserver",
                    name="媒体库同步",
                    func=media_server.sync_mediaserver,
                    hours=mediasync_interval,
                    jobstore=_jobstore,
                )
                log.info("媒体库同步服务启动")

    # 定时把队列中的监控文件转移走
    _sync_transfer_interval = (settings.get("media") or {}).get("sync_transfer_interval", 60)
    if isinstance(_sync_transfer_interval, str):
        try:
            _sync_transfer_interval = int(_sync_transfer_interval)
        except ValueError:
            _sync_transfer_interval = 60
    if _sync_transfer_interval < 10:
        _sync_transfer_interval = 10
    scheduler.register_interval(
        job_id="Sync.transfer_mon_files",
        name="目录同步监控",
        func=sync_engine.transfer_mon_files,
        seconds=_sync_transfer_interval,
        jobstore=_jobstore,
    )

    # 豆瓣RSS转TMDB，定时更新TMDB数据
    scheduler.register_interval(
        job_id="Subscribe.refresh_rss_metainfo",
        name="豆瓣RSS转TMDB",
        func=subscribe_service.refresh_rss_metainfo,
        hours=RSS_REFRESH_TMDB_INTERVAL,
        jobstore=_jobstore,
    )

    # 定时清理临时文件（每6小时执行一次）
    scheduler.register_interval(
        job_id="TempCleanup.do_cleanup",
        name="定时清理临时文件",
        func=TempCleanup.do_cleanup,
        seconds=6 * 3600,
        next_run_time=datetime.datetime.now(),
        jobstore=_jobstore,
    )

    # 识别失败样本周报（ADR-014 P4，每周一 03:30 聚合摘要并轮转）
    scheduler.register_cron(
        job_id="IdentifyMiss.weekly_review",
        name="识别失败样本周报",
        func=weekly_miss_review,
        cron="30 3 * * 1",
        jobstore=_jobstore,
    )

    # 定时清理过期图片缓存（每天执行一次）
    scheduler.register_interval(
        job_id="ImageProxy.clean_old_cache",
        name="清理过期图片缓存",
        func=clean_old_cache,
        hours=24,
        next_run_time=datetime.datetime.now(),
        jobstore=_jobstore,
    )
    log.info("图片缓存清理任务已注册")

    # 插件市场自动同步（auto_update 源；可更新检测在同步比对后由前端/通知驱动）
    if plugin_market_service is not None:
        scheduler.register_interval(
            job_id="PluginMarket.sync_auto",
            name="插件市场自动同步",
            func=plugin_market_service.sync_auto_sources,
            hours=6,
            next_run_time=datetime.datetime.now() + datetime.timedelta(minutes=5),
            jobstore=_jobstore,
        )
        log.info("插件市场自动同步任务已注册（每 6 小时）")

    # Agent 每日维护：RAG 知识库全量重建 + 短期记忆过期清理（agent 未启用时零开销）
    # 固定每日 03:00 执行，避免每次部署/重启都触发全量重建；
    # 全新部署的空库重建由 SystemLifecycleService 启动检查处理。
    if knowledge_ingestor is not None or conversation_store is not None:
        _agent_cfg = settings.get("agent") or {}
        memory_cfg = _agent_cfg.get("memory") or {}
        _ttl_days = _parse_interval(memory_cfg.get("short_term", {}).get("ttl_days"), default=30)

        def _agent_daily_maintenance() -> None:
            if knowledge_ingestor is not None:
                try:
                    stats = knowledge_ingestor.reindex()
                    log.info(f"[AgentMaintenance]知识库重建完成: {stats}")
                except Exception as e:
                    log.error(f"[AgentMaintenance]知识库重建失败: {e}")
            if conversation_store is not None and _ttl_days > 0:
                try:
                    deleted = conversation_store.cleanup_expired(_ttl_days)
                    if deleted:
                        log.info(f"[AgentMaintenance]短期记忆过期清理: {deleted} 个会话")
                except Exception as e:
                    log.error(f"[AgentMaintenance]记忆清理失败: {e}")

        scheduler.register_cron(
            job_id="AgentMaintenance.daily",
            name="Agent 每日维护（知识库重建+记忆清理）",
            func=_agent_daily_maintenance,
            cron="0 3 * * *",
            jobstore=_jobstore,
        )
        log.info("Agent 每日维护任务已注册（每日 03:00）")

    # 站点解析健康度自检（每日 03:20；页面改版导致选择器/字段静默失效时及早发现）
    # 消息注入：负载常时通过 message 推送（连续确认/限流间隔见服务内防抖逻辑）
    scheduler.register_cron(
        job_id="SiteParseHealth.daily_check",
        name="站点解析健康自检",
        func=_parse_health_daily_check(message),
        cron="20 3 * * *",
        jobstore=_jobstore,
    )
    log.info("站点解析健康自检任务已注册（每日 03:20）")
