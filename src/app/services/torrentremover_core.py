"""
TorrentRemover 重构核心
拆分为 Repository + ActionEngine + Service，移除 SingletonMeta。
"""

import log
from app.core.exceptions import ResourceNotFoundError, ValidationError
from app.db.repositories.config_repo_adapter import TorrentRemoveTaskRepositoryAdapter
from app.domain.entities.config import TorrentRemoveTaskEntity
from app.infrastructure.distributed_lock.lock_manager import get_lock_manager
from app.message import Message
from app.schemas.download import TorrentStatus
from app.services.downloader_core import DownloaderCore
from app.services.scheduler.core import SchedulerCore
from app.utils import ExceptionUtils, StringUtils
from app.utils.json_utils import JsonUtils


class TorrentRemoverRepository:
    """删种任务数据仓库"""

    def __init__(self, config_repo: TorrentRemoveTaskRepositoryAdapter):
        self._config_repo = config_repo

    def get_tasks(self):
        return self._config_repo.get_torrent_remove_tasks()

    def delete_task(self, tid):
        self._config_repo.delete_torrent_remove_task(tid=tid)

    def update_task(self, tid, **kwargs) -> bool:
        return self._config_repo.update_torrent_remove_task(tid, **kwargs)

    def insert_task(self, **kwargs):
        self._config_repo.insert_torrent_remove_task(**kwargs)


class TorrentRemoverActionEngine:
    """删种动作执行引擎：暂停 / 删除种子 / 删除种子及文件"""

    @staticmethod
    def execute(task: dict, downloader) -> tuple[int, str]:
        """
        执行单个删种任务
        :return: (处理数量, 处理文本)
        """
        downloader_id = task.get("downloader")
        config = task.get("config") or {}
        config["samedata"] = task.get("samedata")
        config["only_nexus_media"] = task.get("only_nexus_media")
        torrents = downloader.get_remove_torrents(downloader_id=downloader_id, config=config)
        count = len(torrents)
        log.info(f"[TorrentRemover]自动删种任务：{task.get('name')} 获取符合处理条件种子数 {count}")

        action = int(task.get("action") or 0)
        action_label = {1: "暂停", 2: "删除", 3: "删除种子及文件"}.get(action, "处理")
        if not count:
            return 0, ""

        text = TorrentRemoverActionEngine._build_message_text(action_label, torrents)
        if action == 1:
            for torrent in torrents:
                log.info(f"[TorrentRemover]暂停种子：{torrent.get('name')}")
                downloader.stop_torrents(downloader_id=downloader_id, ids=[torrent.get("id")])
        elif action == 2:
            for torrent in torrents:
                log.info(f"[TorrentRemover]删除种子：{torrent.get('name')}")
                downloader.delete_torrents(downloader_id=downloader_id, delete_file=False, ids=[torrent.get("id")])
        elif action == 3:
            for torrent in torrents:
                log.info(f"[TorrentRemover]删除种子及文件：{torrent.get('name')}")
                downloader.delete_torrents(downloader_id=downloader_id, delete_file=True, ids=[torrent.get("id")])
        return count, text

    @staticmethod
    def _build_message_text(action_label: str, torrents: list[dict]) -> str:
        """构建删种结果通知文本，控制长度便于推送."""
        max_items = 10
        name_limit = 42
        count = len(torrents)
        total = sum(torrent.get("size") or 0 for torrent in torrents)
        lines = [f"共{action_label} {count} 个种子，总大小 {StringUtils.str_filesize(total)}"]
        for idx, torrent in enumerate(torrents[:max_items], 1):
            name = torrent.get("name") or "未知种子"
            if len(name) > name_limit:
                name = f"{name[:name_limit]}…"
            size = StringUtils.str_filesize(torrent.get("size") or 0)
            site = torrent.get("site")
            suffix = f"（{site}）" if site else ""
            lines.append(f"{idx}. {name}{suffix} {size}")
        if count > max_items:
            lines.append(f"…… 共 {count} 个，仅显示前 {max_items} 个")
        return "\n".join(lines)


class TorrentRemoverService:
    """删种业务服务（替代原 TorrentRemover）"""

    _jobstore = "torrent_remove"

    def __init__(
        self,
        repository: TorrentRemoverRepository,
        downloader: DownloaderCore,
        message: Message,
        scheduler: SchedulerCore,
    ):
        self._repo = repository
        self._downloader = downloader
        self._message = message
        self._scheduler = scheduler
        self._tasks: dict[str, dict] = {}

    def start_service(self):
        """加载任务并启动调度任务"""
        self._load_tasks()
        self._start_scheduler_jobs()

    # ---------- 内部任务加载与调度 ----------

    def _load_tasks(self) -> None:
        self._tasks = {}
        for task in self._repo.get_tasks():
            config = task.CONFIG
            downloader_id = task.DOWNLOADER
            download_conf = self._downloader.get_downloader_conf(str(downloader_id))
            if download_conf:
                downloader_name = download_conf.get("name", "")
                downloader_type = download_conf.get("type", "")
            else:
                downloader_name = ""
                downloader_type = ""
                downloader_id = ""
            self._tasks[str(task.ID)] = {
                "id": task.ID,
                "name": task.NAME,
                "downloader": downloader_id,
                "downloader_name": downloader_name,
                "downloader_type": downloader_type,
                "only_nexus_media": task.ONLY_NEXUS_MEDIA,
                "samedata": task.SAMEDATA,
                "action": task.ACTION,
                "config": JsonUtils.loads(str(config)) if str(config) else {},
                "interval": task.INTERVAL,
                "enabled": task.ENABLED,
            }

    def _start_scheduler_jobs(self) -> None:
        self.stop_service()
        if not self._tasks:
            return
        remove_flag = False
        for task in self._tasks.values():
            if task.get("enabled") and task.get("interval") and task.get("config"):
                remove_flag = True
                job_id = f"TorrentRemover.auto_remove_torrents_{task.get('id')}"
                self._scheduler.start_job(
                    {
                        "func": self.auto_remove_torrents,
                        "name": f"自动删种任务 {task.get('name')}",
                        "args": (task.get("id"),),
                        "job_id": job_id,
                        "trigger": "interval",
                        "seconds": int(task.get("interval") or 0) * 60,
                        "jobstore": self._jobstore,
                    }
                )
        if remove_flag:
            log.info("自动删种服务启动")

    # ---------- 公共 API ----------

    def get_torrent_remove_tasks(self, taskid=None):
        if taskid:
            task = self._tasks.get(str(taskid))
            return task if task else {}
        return self._tasks

    def auto_remove_torrents(self, taskids=None):
        taskid_str = ",".join(str(t) for t in taskids) if isinstance(taskids, list) else (taskids or "all")
        lock_key = f"torrentremover:execute:{taskid_str}"
        lock = get_lock_manager().create_lock(lock_key, ttl_seconds=600)
        acquired = lock.acquire()
        if not acquired:
            log.info("[TorrentRemover]删种任务正在执行，跳过")
            return
        try:
            tasks = []
            if not taskids:
                for task in self._tasks.values():
                    if task.get("enabled") and task.get("interval") and task.get("config"):
                        tasks.append(task)
            elif isinstance(taskids, list):
                for tid in taskids:
                    task = self._tasks.get(str(tid))
                    if task:
                        tasks.append(task)
            else:
                task = self._tasks.get(str(taskids))
                tasks = [task] if task else []
            if not tasks:
                return
            for task in tasks:
                try:
                    count, text = TorrentRemoverActionEngine.execute(task, self._downloader)
                    if count and text:
                        self._message.send_auto_remove_torrents_message(
                            title=f"自动删种任务：{task.get('name')}", text=text
                        )
                except Exception as e:
                    ExceptionUtils.exception_traceback(e)
                    log.error(f"[TorrentRemover]自动删种任务：{task.get('name')}异常：{str(e)}")
        finally:
            lock.release()

    def _validate_task_params(self, data: dict) -> None:
        errors = TorrentRemoveTaskEntity.validate_params(data)
        if errors:
            raise ValidationError(errors[0])

    def update_torrent_remove_task(self, data: dict) -> None:
        self._validate_task_params(data)

        tid = data.get("tid")
        name = data.get("name")
        action = int(data.get("action") or 0)
        interval = int(data.get("interval") or 0)
        enabled = int(data.get("enabled") or 0)
        samedata = int(data.get("samedata") or 0)
        only_nexus_media = int(data.get("only_nexus_media") or 0)
        ratio = round(float(data.get("ratio") or 0), 2)
        seeding_time = int(data.get("seeding_time") or 0)
        upload_avs = int(data.get("upload_avs") or 0)
        size = str(data.get("size")).split("-") if data.get("size") else []
        size = [int(size[0]), int(size[-1])] if size else []
        tags = data.get("tags")
        tags = [tag for tag in str(tags).split(";") if tag] if tags else []
        savepath_key = data.get("savepath_key")
        tracker_key = data.get("tracker_key")
        downloader_id = data.get("downloader")
        valid_states = {s.name for s in TorrentStatus}

        filter_status = []
        if data.get("filter_status"):
            filter_status = [s for s in str(data.get("filter_status", "")).split(";") if s]
            if filter_status:
                for item in filter_status:
                    if item not in valid_states:
                        raise ValidationError("种子状态参数不合法")

        config = {
            "ratio": ratio,
            "seeding_time": seeding_time,
            "upload_avs": upload_avs,
            "size": size,
            "tags": tags,
            "savepath_key": savepath_key,
            "tracker_key": tracker_key,
            "filter_status": filter_status,
        }
        updated = False
        if tid:
            updated = self._repo.update_task(
                tid,
                name=name,
                action=action,
                interval=interval,
                enabled=enabled,
                samedata=samedata,
                only_nexus_media=only_nexus_media,
                downloader=downloader_id,
                config=config,
            )
        if not updated:
            self._repo.insert_task(
                name=name,
                action=action,
                interval=interval,
                enabled=enabled,
                samedata=samedata,
                only_nexus_media=only_nexus_media,
                downloader=downloader_id,
                config=config,
            )
        self._load_tasks()
        self._start_scheduler_jobs()

    def delete_torrent_remove_task(self, taskid=None) -> None:
        if not taskid:
            raise ValidationError("任务ID不能为空")
        self._repo.delete_task(tid=taskid)
        self._load_tasks()
        self._start_scheduler_jobs()

    def get_remove_torrents(self, taskid) -> list:
        task = self._tasks.get(str(taskid))
        if not task:
            raise ResourceNotFoundError("任务不存在")
        config = task.get("config") or {}
        config["samedata"] = task.get("samedata")
        config["only_nexus_media"] = task.get("only_nexus_media")
        return self._downloader.get_remove_torrents(downloader_id=task.get("downloader"), config=config)

    def stop_service(self):
        try:
            self._scheduler.remove_all_jobs(jobstore=self._jobstore)
        except Exception as e:
            log.error(f"[TorrentRemover]停止服务异常: {str(e)}")
