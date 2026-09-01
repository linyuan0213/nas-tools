"""Brush task service - 刷流任务业务 Facade."""

from typing import Any

import log
from app.core.exceptions import DomainError, RepositoryError, ServiceError
from app.domain.entities.brush import BrushTaskState
from app.domain.enums import SwitchState
from app.media import MediaService
from app.message import Message
from app.services.brush.helpers import BrushTaskHelper
from app.services.brush.rss_checker import BrushRssChecker
from app.services.brush.scheduler import BrushTaskScheduler
from app.services.brush.torrent_lifecycle import BrushTorrentLifecycle
from app.services.downloader_core import DownloaderCore as Downloader
from app.services.rss_processor import RssHelper
from app.sites import SiteConf
from app.sites.engine import SiteEngine
from app.sites.site_cache import SiteCache
from app.utils import StringUtils


class BrushTaskService:
    """
    刷流任务核心业务服务 Facade
    职责：任务加载与内存缓存维护、调度编排，RSS/删种/停种委托给子组件。
    """

    def __init__(
        self,
        repository: Any,
        scheduler: BrushTaskScheduler,
        downloader: Downloader,
        message: Message,
        sites: SiteCache,
        siteconf: SiteConf,
        site_engine: SiteEngine,
        rsshelper: RssHelper,
        filter_service: Any,
        brush_rule_repo: Any,
        media_service: MediaService,
    ):
        self._repo: Any = repository
        self._scheduler = scheduler
        self._downloader: Any = downloader
        self._message: Message = message
        self._sites = sites
        self._siteconf = siteconf
        self._site_engine = site_engine
        self._rsshelper = rsshelper
        self._filter = filter_service
        self._brush_rule_repo = brush_rule_repo
        self._media_service = media_service
        self._brush_tasks: dict = {}
        self._torrents_cache: dict[str, float] = {}

        self._helper = BrushTaskHelper(
            repo=self._repo,
            downloader=self._downloader,
            sites=self._sites,
            siteconf=self._siteconf,
            message=self._message,
            site_engine=self._site_engine,
        )
        self._torrent_lifecycle = BrushTorrentLifecycle(
            helper=self._helper,
            repo=self._repo,
            downloader=self._downloader,
            sites=self._sites,
            message=self._message,
        )
        self._rss_checker = BrushRssChecker(
            helper=self._helper,
            media_service=self._media_service,
            sites=self._sites,
            rsshelper=self._rsshelper,
            siteconf=self._siteconf,
            torrents_cache=self._torrents_cache,
            torrent_lifecycle=self._torrent_lifecycle,
        )

    # ---------- 生命周期 ----------

    def start_service(self) -> None:
        """启动刷流服务：加载任务并启动调度。"""
        self.stop_service()
        self.load_brushtasks()
        self._torrents_cache.clear()
        if self._brush_tasks:
            running_task = 0
            for task in self._brush_tasks.values():
                if task.get("state") in {
                    BrushTaskState.RUNNING.value,
                    BrushTaskState.STOPPED.value,
                } and task.get("interval"):
                    cron = str(task.get("interval")).strip()
                    if cron.isdigit() or cron.count(" ") == 4:
                        running_task += self._start_task_jobs(task, cron)
                    else:
                        log.error(f"任务 {task.get('name')} 运行周期格式不正确")
            if running_task > 0:
                log.info(f"{running_task} 个刷流服务正常启动")

    def stop_service(self) -> None:
        """停止所有刷流调度任务。"""
        self._scheduler.remove_all_jobs()

    # ---------- 调度管理 ----------

    def _start_task_jobs(self, task: dict, cron: str) -> int:
        task_id = task.get("id")
        task_name = task.get("name")
        trigger_type = "interval" if cron.isdigit() else "cron"
        trigger_args = {"seconds": int(cron) * 60} if trigger_type == "interval" else {"cron": cron}
        running = 0

        phase_configs = [
            (self.check_task_rss, "刷流任务", "download_switch"),
            (self.stop_task_torrents, "停种任务", "stop_switch"),
            (self.remove_task_torrents, "删种任务", "remove_switch"),
        ]

        for func, label, switch_key in phase_configs:
            if task.get(switch_key, "Y") != "Y":
                continue
            try:
                self._scheduler.start_job(
                    func=func,
                    name=f"{label} {task_name} ",
                    args=(task_id,),
                    job_id=f"BrushTask.{func.__name__}_{task_id}",
                    trigger_type=trigger_type,
                    trigger_args=trigger_args,
                )
                if switch_key == "download_switch":
                    running = 1
            except (ServiceError, RepositoryError, DomainError):
                raise
            except Exception as err:
                log.error(f"任务 {task_name} {label} 运行周期格式不正确：{err!s}")

        return running

    def _stop_task_jobs(self, task_id):
        for suffix in ["check_task_rss", "stop_task_torrents", "remove_task_torrents"]:
            self._scheduler.remove_job(f"BrushTask.{suffix}_{task_id}")

    # ---------- 任务 CRUD ----------

    def load_brushtasks(self) -> None:
        self._brush_tasks = {}
        brushtasks = self._repo.get_brushtasks()
        if not brushtasks:
            return
        for task in brushtasks:
            try:
                self._brush_tasks[str(task.ID)] = self._build_task_dict(task)
            except Exception as e:
                # 单个任务构建失败不能中断整个加载，否则重启后只剩部分任务
                log.error(f"[Brush]任务 {task.ID} ({task.NAME}) 构建失败，已跳过: {e}")
        # 一次性数据迁移：把 SITE 为配置 id/名称的任务修正为 DB 主键 id
        self._migrate_site_ids(brushtasks)

    def _migrate_site_ids(self, tasks) -> None:
        """兼容历史数据：SITE 存了站点配置 id/名称（如 "ttg"）的任务统一修正为 DB 主键 id."""
        for task in tasks:
            site = str(task.SITE or "")
            if not site or site.isdigit():
                continue
            db_id = self._sites.resolve_site_db_id(site)
            if not db_id:
                continue
            try:
                self._repo.update_brushtask_site(task.ID, str(db_id))
                log.info(f"[Brush]任务 {task.NAME} 站点标识已从 {site} 修正为 DB id {db_id}")
            except Exception as e:
                log.warn(f"[Brush]任务 {task.NAME} 站点标识修正失败: {e}")

    def _reload_single_task(self, task_id):
        task_rows = self._repo.get_brushtasks(brush_id=task_id)
        if not task_rows:
            self._stop_task_jobs(task_id)
            self._brush_tasks.pop(str(task_id), None)
            return
        task = task_rows[0] if isinstance(task_rows, (list, tuple)) else task_rows
        try:
            task_dict = self._build_task_dict(task)
        except Exception as e:
            log.error(f"[Brush]任务 {task.ID} ({task.NAME}) 构建失败，已跳过: {e}")
            self._stop_task_jobs(task.ID)
            self._brush_tasks.pop(str(task.ID), None)
            return
        self._stop_task_jobs(task.ID)
        self._brush_tasks[str(task.ID)] = task_dict
        cron = str(task.INTEVAL).strip()
        if (
            task.STATE
            in {
                BrushTaskState.RUNNING.value,
                BrushTaskState.STOPPED.value,
            }
            and cron
            and (cron.isdigit() or cron.count(" ") == 4)
        ):
            self._start_task_jobs(task_dict, cron)

    def _load_rules_from_template(self, task) -> tuple[dict, dict, dict]:
        """加载任务规则：优先从规则模板读取，否则使用任务自身规则。"""
        rss_rule = self._helper.parse_json_rule(task.RSS_RULE, {})
        remove_rule = self._helper.parse_json_rule(task.REMOVE_RULE, {})
        stop_rule = self._helper.parse_json_rule(task.STOP_RULE, {"stopfree": "Y"})
        rss_rule_id = getattr(task, "RSS_RULE_ID", None)
        remove_rule_id = getattr(task, "REMOVE_RULE_ID", None)
        stop_rule_id = getattr(task, "STOP_RULE_ID", None)

        rss_rule = self._load_template_rule(rss_rule_id, "rss_rule", rss_rule)
        remove_rule = self._load_template_rule(remove_rule_id, "remove_rule", remove_rule)
        stop_rule = self._load_template_rule(stop_rule_id, "stop_rule", stop_rule)
        return rss_rule, remove_rule, stop_rule

    def _load_template_rule(self, rule_id, field_name, default):
        """加载单个规则模板的指定字段"""
        if not rule_id:
            return default
        try:
            entity = self._brush_rule_repo.get_by_id(int(rule_id))
            if entity:
                value = getattr(entity, field_name, None)
                return self._helper.parse_json_rule(value) if value else default
        except (ServiceError, RepositoryError, DomainError):
            raise
        except Exception as e:  # noqa: BLE001
            log.debug(f"[Brush]加载规则模板 {rule_id}/{field_name} 失败: {e}")
        return default

    def _build_task_dict(self, task) -> dict:
        site_info: Any = self._sites.get_sites(siteid=task.SITE)
        site_url = StringUtils.get_base_url(site_info.get("signurl") or site_info.get("rssurl")) if site_info else ""
        downloader_info = self._downloader.get_downloader_conf(task.DOWNLOADER)
        total_size = round(int(self._repo.get_brushtask_totalsize(task.ID)) / (1024**3), 1)
        seed_size_gb = round(int(task.SEED_SIZE) / (1024**3), 1) if task.SEED_SIZE else 0
        rss_rule, remove_rule, stop_rule = self._load_rules_from_template(task)
        return {
            "id": task.ID,
            "name": task.NAME,
            "site": site_info.get("name") if site_info else None,
            "site_id": task.SITE,
            "interval": task.INTEVAL,
            "label": task.LABEL,
            "savepath": task.SAVEPATH,
            "state": task.STATE,
            "downloader": task.DOWNLOADER,
            "downloader_name": downloader_info.get("name") if downloader_info else None,
            "transfer": task.TRANSFER == SwitchState.ON.value,
            "sendmessage": task.SENDMESSAGE == SwitchState.ON.value,
            "free": task.FREELEECH == SwitchState.ON.value,
            "rss_rule": rss_rule,
            "remove_rule": remove_rule,
            "stop_rule": stop_rule,
            "rss_rule_id": getattr(task, "RSS_RULE_ID", None),
            "remove_rule_id": getattr(task, "REMOVE_RULE_ID", None),
            "stop_rule_id": getattr(task, "STOP_RULE_ID", None),
            "seed_size": seed_size_gb,
            "time_range": task.TIME_RANGE,
            "active_weekdays": task.ACTIVE_WEEKDAYS,
            "download_switch": getattr(task, "DOWNLOAD_SWITCH", "Y") or "Y",
            "remove_switch": getattr(task, "REMOVE_SWITCH", "Y") or "Y",
            "stop_switch": getattr(task, "STOP_SWITCH", "Y") or "Y",
            "daily_delete_limit": getattr(task, "DAILY_DELETE_LIMIT", "") or "",
            "max_seeding": getattr(task, "MAX_SEEDING", "") or "",
            "hr_limit": getattr(task, "HR_LIMIT", "") or "",
            "total_size": total_size,
            "rss_url": task.RSSURL if task.RSSURL else (site_info.get("rssurl") if site_info else None),
            "rss_url_show": task.RSSURL,
            "cookie": site_info.get("cookie") if site_info else None,
            "api_key": site_info.get("api_key") if site_info else None,
            "bearer_token": site_info.get("bearer_token") if site_info else None,
            "ua": site_info.get("ua") if site_info else None,
            "headers": site_info.get("headers") if site_info else None,
            "download_count": task.DOWNLOAD_COUNT,
            "remove_count": task.REMOVE_COUNT,
            "download_size": StringUtils.str_filesize(task.DOWNLOAD_SIZE),
            "upload_size": StringUtils.str_filesize(task.UPLOAD_SIZE),
            "lst_mod_date": task.LST_MOD_DATE,
            "site_url": site_url,
        }

    def get_brushtask_info(self, taskid: int | str | None = None) -> Any:
        if not self._brush_tasks:
            self.load_brushtasks()
        if taskid:
            return self._brush_tasks.get(str(taskid)) or {}
        return list(self._brush_tasks.values())

    def update_brushtask(self, brushtask_id: int | None, item: dict) -> Any:
        ret = self._repo.update_brushtask(brushtask_id or 0, item)
        if brushtask_id:
            self._reload_single_task(brushtask_id)
        else:
            brushtasks = self._repo.get_brushtasks()
            new_task_name = item.get("name")
            for task in brushtasks or []:
                if task.NAME == new_task_name:
                    task_dict = self._build_task_dict(task)
                    self._brush_tasks[str(task.ID)] = task_dict
                    cron = str(task.INTEVAL).strip()
                    if (
                        task.STATE
                        in {
                            BrushTaskState.RUNNING.value,
                            BrushTaskState.STOPPED.value,
                        }
                        and cron
                        and (cron.isdigit() or cron.count(" ") == 4)
                    ):
                        self._start_task_jobs(task_dict, cron)
                    break
        return ret

    def delete_brushtask(self, brushtask_id: int | None) -> Any:
        self._stop_task_jobs(brushtask_id)
        task = self._brush_tasks.get(str(brushtask_id))
        if not task:
            task_rows = self._repo.get_brushtasks(brush_id=brushtask_id)
            if task_rows:
                row = task_rows[0] if isinstance(task_rows, (list, tuple)) else task_rows
                task = self._build_task_dict(row)
        downloader_id = task.get("downloader") if task else None
        if downloader_id:
            torrents = self._repo.get_brushtask_torrents(brushtask_id, active=False)
            delete_ids = [t.DOWNLOAD_ID for t in torrents if t.DOWNLOAD_ID and t.DOWNLOAD_ID != "0"]
            if delete_ids:
                try:
                    self._downloader.delete_torrents(downloader_id=downloader_id, ids=delete_ids, delete_file=True)
                except Exception as e:
                    log.warn(f"[BrushTask]删除任务 {brushtask_id} 的下载器种子失败: {e}")
        ret = self._repo.delete_brushtask(brushtask_id or 0)
        self._brush_tasks.pop(str(brushtask_id), None)
        return ret

    def update_brushtask_state(self, state: str | None, brushtask_id: int | None = None) -> Any:
        ret = self._repo.update_brushtask_state(state=state or "", tid=brushtask_id)
        if brushtask_id:
            task = self._brush_tasks.get(str(brushtask_id))
            if task:
                task["state"] = state
            self._reload_single_task(brushtask_id)
        else:
            for task in self._brush_tasks.values():
                task["state"] = state
            self.load_brushtasks()
            self.stop_service()
            if self._brush_tasks:
                for task in self._brush_tasks.values():
                    if task.get("state") in {
                        BrushTaskState.RUNNING.value,
                        BrushTaskState.STOPPED.value,
                    } and task.get("interval"):
                        cron = str(task.get("interval")).strip()
                        if cron.isdigit() or cron.count(" ") == 4:
                            self._start_task_jobs(task, cron)
        return ret

    def get_brushtask_torrents(self, brush_id: int | None, active: bool = True) -> Any:
        return self._repo.get_brushtask_torrents(brush_id or 0, active)

    def is_torrent_handled(self, enclosure: str | None) -> bool:
        return self._helper.is_torrent_handled(enclosure)

    # ---------- RSS 刷流（委托） ----------

    def check_task_rss(self, taskid: int | None) -> None:
        taskinfo = self.get_brushtask_info(taskid)
        self._rss_checker.check_task_rss(taskid, taskinfo)

    # ---------- 删种（委托） ----------

    def remove_task_torrents(self, taskid: int | None) -> None:
        taskinfo = self.get_brushtask_info(taskid)
        self._torrent_lifecycle.remove_task_torrents(taskid, taskinfo)

    # ---------- 停种（委托） ----------

    def stop_task_torrents(self, taskid: int | None) -> None:
        taskinfo = self.get_brushtask_info(taskid)
        self._torrent_lifecycle.stop_task_torrents(taskid, taskinfo)
