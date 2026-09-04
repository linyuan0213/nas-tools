"""
DownloaderCore - 下载器 Facade（兼容旧 Downloader 接口）

职责：
- 聚合 DownloadClientFactory、DownloadCore、TransferCoordinator
- 保留 Downloader 类名作为 Facade，兼容旧调用
- 内部委托给新服务，所有调用方无需修改

参考：app/services/search_service.py 中 Searcher 的做法
"""

from threading import Lock
from typing import TYPE_CHECKING, Any

import log
from app.core.constants import PT_TAG
from app.domain.entities.transfer_task import SourceType, TransferTask
from app.downloader.client_factory import DownloadClientFactory
from app.services.download_core import DownloadCore
from app.services.transfer_coordinator import TransferCoordinator
from app.services.transfer_pipeline import TransferPipeline

if TYPE_CHECKING:
    from app.services.download_monitor import DownloadMonitor

_downloader_locks: dict[str, Lock] = {}
_lock_guard = Lock()


def _get_downloader_lock(downloader_id: str) -> Lock:
    if downloader_id not in _downloader_locks:
        with _lock_guard:
            if downloader_id not in _downloader_locks:
                _downloader_locks[downloader_id] = Lock()
    return _downloader_locks[downloader_id]


class DownloaderCore:
    """
    下载器核心 Facade

    聚合工厂、核心下载逻辑、转移协调三个子服务，
    对外暴露与原始 Downloader 完全一致的公共方法签名。
    """

    def __init__(
        self,
        client_factory: DownloadClientFactory,
        transfer_coordinator: TransferCoordinator,
        transfer_pipeline: TransferPipeline,
        download_core: DownloadCore,
        download_history_repo=None,
        download_monitor: "DownloadMonitor | None" = None,
    ):
        self._client_factory = client_factory
        self._pipeline = transfer_pipeline
        self._transfer_coordinator = transfer_coordinator
        self._download_core = download_core
        self._download_history_repo = download_history_repo
        self._download_monitor = download_monitor

    # ---------- 生命周期（由外部 SystemLifecycleService 控制） ----------

    def refresh_downloaders(self) -> None:
        """刷新下载器配置缓存（插件注册/注销下载器客户端后调用）"""
        try:
            self._client_factory._refresh()
        except Exception as e:  # noqa: BLE001
            log.error(f"[Downloader]刷新下载器缓存失败: {e}")

    def start_service(self):
        """启动转移任务调度"""
        self._transfer_coordinator.start_service(self.transfer)

    def stop_service(self):
        """停止转移任务调度"""
        self._transfer_coordinator.stop_service()

    # ---------- 属性代理 ----------

    @property
    def default_downloader_id(self):
        return self._client_factory.default_downloader_id

    def set_default_downloader_id(self, did: str) -> bool:
        return self._client_factory.set_default_downloader(did)

    @property
    def default_download_setting_id(self):
        return self._client_factory.default_download_setting_id

    def set_default_download_setting_id(self, sid: str) -> bool:
        return self._client_factory.set_default_download_setting(sid)

    @property
    def default_client(self):
        return self._client_factory.default_client

    @property
    def monitor_downloader_ids(self):
        return self._client_factory.monitor_downloader_ids

    # ---------- 核心下载 ----------

    def download(
        self,
        media_info,
        is_paused=None,
        tag=None,
        download_dir=None,
        download_setting=None,
        downloader_id=None,
        upload_limit=None,
        download_limit=None,
        torrent_file=None,
        in_from=None,
        user_name=None,
        proxy=None,
        file_indices=None,
        file_names=None,
    ):
        return self._download_core.download(
            media_info=media_info,
            is_paused=is_paused,
            tag=tag,
            download_dir=download_dir,
            download_setting=download_setting,
            downloader_id=downloader_id,
            upload_limit=upload_limit,
            download_limit=download_limit,
            torrent_file=torrent_file,
            in_from=in_from,
            user_name=user_name,
            proxy=proxy,
            file_indices=file_indices,
            file_names=file_names,
        )

    def batch_download(self, in_from, media_list, need_tvs=None, user_name=None) -> Any:
        return self._download_core.batch_download(
            in_from=in_from, media_list=media_list, need_tvs=need_tvs, user_name=user_name
        )

    # ---------- 转移 ----------

    def transfer(self, downloader_id: str | None = None):
        """转移下载完成的文件，通过 TransferPipeline 统一处理。"""
        downloader_ids = [downloader_id] if downloader_id else self._client_factory.monitor_downloader_ids
        for did in downloader_ids:
            with _get_downloader_lock(did):
                downloader_conf = self._client_factory.get_downloader_conf(did)
                if not downloader_conf:
                    continue
                name = downloader_conf.get("name")
                only_nexus_media = downloader_conf.get("only_nexus_media")
                match_path = downloader_conf.get("match_path")
                operation = str(downloader_conf.get("rmt_mode") or "")
                _client = self._client_factory.get_client(did)
                if not _client:
                    continue
                trans_tasks = _client.get_transfer_task(tag=PT_TAG if only_nexus_media else None, match_path=match_path)
                if trans_tasks:
                    log.info(f"[Downloader]下载器 {name} 开始转移下载文件...")
                else:
                    continue
                for task in trans_tasks:
                    task_id = task.get("id")
                    task_path = task.get("path") or ""
                    if not task_id or not task_path:
                        continue

                    def _post_process(
                        t: TransferTask,
                        success: bool,
                        msg: str,
                        client=_client,
                        tid=str(task_id),
                        op=operation,
                        tags=task.get("tags"),
                    ):
                        if not success:
                            log.warn(f"[Downloader]任务 {tid} 转移失败：{msg}")
                            client.set_torrents_status(ids=tid, tags=tags)
                            return
                        if op == "move":
                            log.warn(f"[Downloader]移动模式下删除种子文件：{tid}")
                            client.delete_torrents(delete_file=True, ids=tid)
                        else:
                            client.set_torrents_status(ids=tid, tags=tags)

                    pipeline_task = TransferTask(
                        source_type=SourceType.DOWNLOADER,
                        source_id=name or "",
                        file_paths=[task_path],
                        operation=operation,
                        post_process=_post_process,
                    )
                    self._pipeline.process(pipeline_task)
                log.info(f"[Downloader]下载器 {name} 下载文件转移结束")

    # ---------- 种子查询/操作 ----------

    def get_torrents(self, downloader_id=None, ids=None, tag=None):
        return self._download_core.get_torrents(downloader_id=downloader_id, ids=ids, tag=tag)

    def get_remove_torrents(self, downloader_id=None, config=None):
        return self._download_core.get_remove_torrents(downloader_id=downloader_id, config=config)

    def get_downloading_torrents(self, downloader_id=None, ids=None, tag=None):
        return self._download_core.get_downloading_torrents(downloader_id=downloader_id, ids=ids, tag=tag)

    def get_downloading_progress(self, downloader_id=None, ids=None):
        return self._download_core.get_downloading_progress(downloader_id=downloader_id, ids=ids)

    def get_completed_torrents(self, downloader_id=None, ids=None, tag=None):
        return self._download_core.get_completed_torrents(downloader_id=downloader_id, ids=ids, tag=tag)

    def set_torrents_tag(self, downloader_id=None, ids=None, tags=None):
        return self._download_core.set_torrents_tag(downloader_id=downloader_id, ids=ids, tags=tags)

    def _resolve_downloader_id(self, download_id: str | None) -> str | None:
        """根据任务 ID 从下载历史记录中解析对应的下载器 ID"""
        if not download_id or not self._download_history_repo:
            return None
        try:
            history = self._download_history_repo.get_by_id(download_id)
            if history:
                return history.DOWNLOADER
        except Exception as e:
            log.debug(f"[DownloaderCore]解析任务 {download_id} 的下载器失败: {e}")
        return None

    def start_torrents(self, downloader_id=None, ids=None):
        if not downloader_id and ids:
            downloader_id = self._resolve_downloader_id(
                ids if isinstance(ids, str) else ids[0] if isinstance(ids, list) else None
            )
        return self._download_core.start_torrents(downloader_id=downloader_id, ids=ids)

    def stop_torrents(self, downloader_id=None, ids=None):
        if not downloader_id and ids:
            downloader_id = self._resolve_downloader_id(
                ids if isinstance(ids, str) else ids[0] if isinstance(ids, list) else None
            )
        return self._download_core.stop_torrents(downloader_id=downloader_id, ids=ids)

    def delete_torrents(self, downloader_id=None, ids=None, delete_file=False):
        if not downloader_id and ids:
            downloader_id = self._resolve_downloader_id(
                ids if isinstance(ids, str) else ids[0] if isinstance(ids, list) else None
            )
        return self._download_core.delete_torrents(downloader_id=downloader_id, ids=ids, delete_file=delete_file)

    def get_files(self, tid, downloader_id=None):
        return self._download_core.get_files(tid=tid, downloader_id=downloader_id)

    def set_files_status(self, tid, need_episodes, downloader_id=None):
        return self._download_core.set_files_status(tid=tid, need_episodes=need_episodes, downloader_id=downloader_id)

    def recheck_torrents(self, downloader_id=None, ids=None):
        return self._download_core.recheck_torrents(downloader_id=downloader_id, ids=ids)

    def set_speed_limit(self, downloader_id=None, download_limit=None, upload_limit=None):
        return self._download_core.set_speed_limit(
            downloader_id=downloader_id, download_limit=download_limit, upload_limit=upload_limit
        )

    def get_torrent_trackers(self, tid, downloader_id=None):
        return self._download_core.get_torrent_trackers(tid=tid, downloader_id=downloader_id)

    def add_torrent_trackers(self, tid, urls, downloader_id=None):
        return self._download_core.add_torrent_trackers(ids=tid, urls=urls, downloader_id=downloader_id)

    def edit_torrent_tracker(self, tid, old_url, new_url, downloader_id=None):
        return self._download_core.edit_torrent_tracker(
            ids=tid, old_url=old_url, new_url=new_url, downloader_id=downloader_id
        )

    def remove_torrent_trackers(self, tid, urls, downloader_id=None):
        return self._download_core.remove_torrent_trackers(ids=tid, urls=urls, downloader_id=downloader_id)

    # ---------- 存在性检查 ----------

    def check_exists_medias(self, meta_info, no_exists=None, total_ep=None) -> tuple[bool, dict, Any]:
        return self._download_core.check_exists_medias(meta_info=meta_info, no_exists=no_exists, total_ep=total_ep)  # type: ignore[attr-defined]

    # ---------- 目录/设置查询 ----------

    def get_download_dirs(self, setting=None):
        return self._client_factory.get_download_dirs(setting=setting)

    def get_download_visit_dirs(self):
        return self._client_factory.get_download_visit_dirs()

    def get_download_visit_dir(self, download_dir, downloader_id=None):
        return self._client_factory.get_download_visit_dir(download_dir=download_dir, downloader_id=downloader_id)

    def get_download_setting(self, sid=None):
        return self._client_factory.get_download_setting(sid=sid)

    def get_downloader_conf(self, did=None):
        return self._client_factory.get_downloader_conf(did=did)

    def get_downloader_conf_simple(self, brush: bool = False):
        return self._client_factory.get_downloader_conf_simple(brush=brush)

    def get_downloader(self, downloader_id=None):
        return self._client_factory.get_client(did=downloader_id)

    def get_downloader_type(self, downloader_id=None):
        return self._client_factory.get_client_type(downloader_id=downloader_id)

    def get_status(self, dtype=None, config=None):
        return self._client_factory.get_status(dtype=dtype, config=config)

    def get_remote_dirs(self, dtype=None, config=None) -> list[str]:
        return self._client_factory.get_remote_dirs(dtype=dtype, config=config)

    def get_free_space(self, downloader_id, path: str):
        return self._client_factory.get_free_space(downloader_id=downloader_id, path=path)

    # ---------- 种子解析 ----------

    def get_torrent_episodes(self, url, page_url=None):
        return self._download_core.get_torrent_episodes(url=url, page_url=page_url)

    def get_download_url(self, page_url):
        return self._download_core.get_download_url(page_url)

    # ---------- 历史记录 ----------

    def get_download_history(self, date=None, hid=None, num=30, page=1):
        return self._download_core.get_download_history(date=date, hid=hid, num=num, page=page)

    def get_download_history_by_title(self, title):
        return self._download_core.get_download_history_by_title(title=title)

    def get_download_history_by_downloader(self, downloader, download_id):
        return self._download_core.get_download_history_by_downloader(downloader=downloader, download_id=download_id)

    # ---------- 下载器 CRUD ----------

    def _refresh_all_factories(self) -> None:
        """刷新所有工厂实例缓存"""
        self._client_factory._refresh()
        if self._download_monitor:
            self._download_monitor.refresh_factory()

    def update_downloader(
        self, did, name, enabled, dtype, transfer, only_nexus_media, match_path, rmt_mode, config, download_dir
    ):
        ret = self._download_core.update_downloader(
            did=did,
            name=name,
            enabled=enabled,
            dtype=dtype,
            transfer=transfer,
            only_nexus_media=only_nexus_media,
            match_path=match_path,
            rmt_mode=rmt_mode,
            config=config,
            download_dir=download_dir,
        )
        self._refresh_all_factories()
        return ret

    def upsert_downloader(
        self,
        did: int | None = None,
        name: str = "",
        dtype: str = "",
        config_overlay: dict | None = None,
        enabled: bool | None = None,
        is_default: bool = False,
    ) -> tuple[str, str, bool]:
        """统一下载器新增/更新入口：合并现有配置并保留管理字段，供 Agent 工具与 manifest 复用.

        did 有值→更新（name/type 缺省保留现状，enabled=None 保留现状）；
        did 为空→新增（需 name 与 dtype）。is_default 时同步设为默认下载器。
        返回 (显示名, 类型, 是否新增)；失败抛 ValueError（含“下载器不存在”等提示）。
        """
        did = int(did or 0) or None
        if did:
            current = self.get_downloader_conf(did=did) or {}
            if not current:
                raise ValueError(f"下载器不存在: {did}")
            merged = dict(current.get("config") or {})
            merged.update({k: v for k, v in (config_overlay or {}).items() if v is not None})
            target_name = name or current.get("name") or ""
            target_type = current.get("type") or ""
            enabled_val = current.get("enabled") if enabled is None else (1 if enabled else 0)
            self.update_downloader(
                did=did,
                name=target_name,
                enabled=enabled_val,
                dtype=target_type,
                transfer=current.get("transfer", 0),
                only_nexus_media=current.get("only_nexus_media", 0),
                match_path=current.get("match_path", 0),
                rmt_mode=current.get("rmt_mode", ""),
                config=merged,
                download_dir=current.get("download_dir") or [],
            )
            if is_default:
                self.set_default_downloader_id(str(did))
            return target_name, target_type, False

        if not name or not dtype:
            raise ValueError("新增下载器需提供 name 与 dtype（类型如 qbittorrent/transmission）")
        merged = dict(config_overlay or {})
        enabled_val = 1 if (enabled is None or enabled) else 0
        self.update_downloader(
            did=None,
            name=name,
            enabled=enabled_val,
            dtype=dtype,
            transfer=0,
            only_nexus_media=0,
            match_path=0,
            rmt_mode="",
            config=merged,
            download_dir=[],
        )
        if is_default:
            fresh = self.get_downloader_conf() or {}
            for k, v in fresh.items():
                if v.get("name") == name:
                    self.set_default_downloader_id(str(k))
                    break
        return name, dtype, True

    def delete_downloader(self, did):
        ret = self._download_core.delete_downloader(did=did)
        self._refresh_all_factories()
        return ret

    def check_downloader(self, did=None, transfer=None, only_nexus_media=None, enabled=None, match_path=None):
        ret = self._download_core.check_downloader(
            did=did, transfer=transfer, only_nexus_media=only_nexus_media, enabled=enabled, match_path=match_path
        )
        self._refresh_all_factories()
        return ret

    def delete_download_setting(self, sid):
        ret = self._download_core.delete_download_setting(sid=sid)
        self._refresh_all_factories()
        return ret

    def update_download_setting(
        self,
        sid,
        name,
        category,
        tags,
        is_paused,
        upload_limit,
        download_limit,
        ratio_limit,
        seeding_time_limit,
        downloader,
    ):
        ret = self._download_core.update_download_setting(
            sid=sid,
            name=name,
            category=category,
            tags=tags,
            is_paused=is_paused,
            upload_limit=upload_limit,
            download_limit=download_limit,
            ratio_limit=ratio_limit,
            seeding_time_limit=seeding_time_limit,
            downloader=downloader,
        )
        self._refresh_all_factories()
        return ret
