"""FileTransferService - 文件转移业务 Facade.

保留与原 FileTransfer 兼容的公共 API，核心转移流程保留在 Facade 中，
路径解析、存在性检查、历史管理、清理逻辑委托给独立组件.
"""

import hashlib
import os
import re
import shutil
from collections import defaultdict
from collections.abc import Callable
from concurrent.futures import Future, wait
from typing import Any

import log
from app.core.constants import RMT_MEDIAEXT, RMT_MIN_FILESIZE
from app.core.exceptions import DomainError, RepositoryError, ServiceError
from app.core.settings import settings
from app.db.repositories.sync_repo_adapter import SyncPathRepositoryAdapter
from app.domain.enums import ProgressKey, SyncType
from app.domain.mediatypes import MediaType
from app.events import Event
from app.events.bus import EventBus
from app.events.constants import MEDIA_EPISODE_TRANSFERRED, MEDIA_TRANSFER_FINISHED, SUBTITLE_DOWNLOAD, TRANSFER_FAIL
from app.events.payloads import (
    MediaEpisodeTransferredPayload,
    MediaTransferFinishedPayload,
    SubtitleDownloadPayload,
    TransferFailPayload,
)
from app.infrastructure.distributed_lock.lock_manager import get_lock_manager
from app.infrastructure.progress import ProgressTracker
from app.infrastructure.thread import ThreadExecutor
from app.media import MediaService, Scraper
from app.media import meta_info as meta_info_fn
from app.media.parser import RegexParser
from app.message import Message
from app.schemas.media import TransferMediaDTO
from app.services.transfer.cleanup_service import TransferCleanupService
from app.services.transfer.existence_checker import MediaExistenceChecker
from app.services.transfer.history_manager import TransferHistoryManager
from app.services.transfer.path_resolver import TransferPathResolver
from app.services.transfer_engine import TransferEngine
from app.utils import ExceptionUtils, PathUtils, StringUtils


class FileTransferService:
    """文件转移业务 Facade."""

    def __init__(
        self,
        media_service: MediaService,
        message: Message,
        scraper: Scraper,
        thread_executor: ThreadExecutor,
        history_manager: TransferHistoryManager,
        progress: ProgressTracker,
        event_bus: EventBus,
        engine: TransferEngine,
        sync_path_repo: SyncPathRepositoryAdapter,
        path_resolver: TransferPathResolver,
        existence_checker: MediaExistenceChecker,
        cleanup_service: TransferCleanupService,
    ):
        self.media = media_service
        self.message = message
        self.scraper = scraper
        self._thread_executor = thread_executor
        self.progress = progress
        self._event_bus = event_bus
        self._engine = engine
        self._default_operation: str = "copy"
        self._min_filesize = RMT_MIN_FILESIZE
        self._filesize_cover = False
        self._ignored_paths: re.Pattern[str] | None = None
        self._ignored_files: re.Pattern[str] | None = None
        self._sync_repo = sync_path_repo

        self._path_resolver = path_resolver
        self._existence = existence_checker
        self._history = history_manager
        self._cleanup = cleanup_service

        # 从配置读取媒体处理参数
        media = settings.get("media")
        if media:
            min_filesize = media.get("min_filesize")
            if isinstance(min_filesize, int):
                self._min_filesize = min_filesize * 1024 * 1024
            elif isinstance(min_filesize, str) and min_filesize.isdigit():
                self._min_filesize = int(min_filesize) * 1024 * 1024
            ignored_paths = media.get("ignored_paths")
            if ignored_paths:
                ignored_paths = ignored_paths.removesuffix(";")
                self._ignored_paths = re.compile(r"{}".format(re.sub(r";", r"|", ignored_paths)))
            ignored_files = media.get("ignored_files")
            if ignored_files:
                ignored_files = ignored_files.removesuffix(";")
                self._ignored_files = re.compile(r"{}".format(re.sub(r";", r"|", ignored_files)))
            self._filesize_cover = media.get("filesize_cover")

        self._default_operation = (settings.get("pt") or {}).get("rmt_mode", "copy") or "copy"

    # ---------- 路径相关委托方法（公共 API 兼容） ----------

    def is_target_dir_path(self, path):
        return self._path_resolver.is_target_dir_path(path)

    def get_dest_path_by_info(self, dest, meta_info):
        return self._path_resolver.get_dest_path_by_info(dest, meta_info, self.media)

    def get_no_exists_medias(self, meta_info, season=None, total_num=None):
        # 先查转移历史 DB：已转移过的剧集视为已存在
        if meta_info.type != MediaType.MOVIE and meta_info.tmdb_id and season and total_num:
            try:
                season_str = f"S{season:02d}" if isinstance(season, int) else str(season)
                history = self._history.get_transfer_info_by(tmdbid=meta_info.tmdb_id, season=season_str)
                transferred: set[int] = set()
                if history:
                    for h in history:
                        se = h.season_episode or ""
                        parts = se.replace("S", "").split("E")
                        if len(parts) >= 2 and parts[0].isdigit() and int(parts[0]) == int(season):
                            ep = parts[1]
                            if "-" in ep:
                                a, b = ep.split("-")
                                transferred.update(range(int(a), int(b) + 1))
                            elif ep.isdigit():
                                transferred.add(int(ep))
                if transferred:
                    all_episodes = set(range(1, total_num + 1))
                    return list(all_episodes - transferred)
            except Exception:
                log.debug("[FileTransfer]历史查询失败，回退文件扫码")

        # 回退：文件系统扫码
        return self._existence.get_no_exists_medias(meta_info, meta_info_fn, season, total_num)

    def get_best_target_path(self, mtype, in_path=None, size=0):
        return self._path_resolver.get_best_target_path(mtype, in_path, size)

    def get_moive_dest_path(self, media_info):
        return self._path_resolver.get_movie_dest_path(media_info, self.media)

    def get_tv_dest_path(self, media_info):
        return self._path_resolver.get_tv_dest_path(media_info, self.media)

    # ---------- 历史记录委托方法（公共 API 兼容） ----------

    def get_transfer_info_by(self, tmdbid, season=None, season_episode=None):
        return self._history.get_transfer_info_by(tmdbid, season, season_episode)

    def get_transfer_info_by_id(self, logid):
        return self._history.get_transfer_info_by_id(logid)

    def get_transfer_history(self, search, page, rownum):
        return self._history.get_transfer_history(search, page, rownum)

    def delete_transfer_log_by_id(self, logid):
        return self._history.delete_transfer_log_by_id(logid)

    def delete_transfer_logs(self, logids: list[int]) -> None:
        return self._history.delete_transfer_logs(logids)

    def delete_transfer(self):
        return self._history.delete_transfer()

    def delete_transfer_unknown(self, tid):
        return self._history.delete_transfer_unknown(tid)

    def delete_transfer_unknowns(self, tids: list[int]) -> None:
        return self._history.delete_transfer_unknowns(tids)

    def get_unknown_info_by_id(self, tid):
        return self._history.get_unknown_info_by_id(tid)

    def update_transfer_unknown_state(self, path):
        return self._history.update_transfer_unknown_state(path)

    def delete_transfer_blacklist(self, path):
        return self._history.delete_transfer_blacklist(path)

    def truncate_transfer_blacklist(self):
        return self._history.truncate_transfer_blacklist()

    def get_transfer_statistics(self, days=30):
        return self._history.get_transfer_statistics(days)

    def get_transfer_unknown_paths(self):
        return self._history.get_transfer_unknown_paths()

    def get_transfer_unknown_paths_by_page(self, search, page, rownum):
        return self._history.get_transfer_unknown_paths_by_page(search, page, rownum)

    # ---------- 清理服务委托方法 ----------

    def delete_history(self, logids, flag=None):
        lock_key = f"transfer:delete:{hashlib.md5(str(logids).encode(), usedforsecurity=False).hexdigest()}"
        lock = get_lock_manager().create_lock(lock_key, ttl_seconds=300)
        acquired = lock.acquire()
        if not acquired:
            log.info("[Rmt]删除历史任务正在执行，跳过")
            return None
        try:
            return self._cleanup.delete_history(logids, flag)
        finally:
            lock.release()

    def delete_media_file(self, filedir, filename, backend_id="local"):
        return self._cleanup.delete_media_file(filedir, filename, backend_id)

    # ---------- 过滤与工具方法 ----------

    def check_ignore(self, file_list):
        """检查过滤文件列表中忽略项目."""
        if not file_list:
            return [], ""
        ignored_paths = self._ignored_paths
        if ignored_paths:
            try:
                file_list = [f for f in file_list if not re.findall(ignored_paths, os.path.dirname(f))]
                if not file_list:
                    return [], "排除文件路径转移忽略词后，没有新文件需要处理"
            except Exception as err:
                ExceptionUtils.exception_traceback(err)
                log.error(f"[Rmt]文件路径转移忽略词设置有误：{err!s}")

        ignored_files = self._ignored_files
        if ignored_files:
            try:
                file_list = [f for f in file_list if not re.findall(ignored_files, os.path.basename(f))]
                if not file_list:
                    return [], "排除文件名转移忽略词后，没有新文件需要处理"
            except Exception as err:
                ExceptionUtils.exception_traceback(err)
                log.error(f"[Rmt]文件名转移忽略词设置有误：{err!s}")

        return file_list, ""

    def link_sync_file(self, src_path, in_file, target_dir, operation):
        """对文件做纯链接处理，不做识别重命名（监控模块调用）."""
        new_file = in_file.replace(src_path, target_dir)
        new_file_list, msg = self.check_ignore(file_list=[new_file])
        if not new_file_list:
            return 0, msg
        else:
            new_file = new_file_list[0]
        new_dir = os.path.dirname(new_file)
        if not os.path.exists(new_dir):
            os.makedirs(new_dir)
        try:
            self._engine._execute(in_file, new_file, operation)
            return 0, ""
        except (ServiceError, RepositoryError, DomainError):
            raise
        except Exception as e:
            log.error(f"[Rmt]link_sync_file 失败：{e}")
            return 1, str(e)

    # ---------- 核心转移流程（保留在 Facade） ----------

    def transfer_media(
        self,
        in_from,
        in_path,
        operation=None,
        files=None,
        target_dir=None,
        unknown_dir=None,
        tmdb_info=None,
        media_type=None,
        season=None,
        episode=None,
        min_filesize=None,
        udf_flag=False,
        root_path=False,
        dst_backend=None,
        fallback_episode=None,
    ) -> tuple[bool, str]:
        """识别并转移一个文件、多个文件或者目录."""
        if not in_path or not os.path.exists(in_path):
            return self._finish_transfer(False, f"文件转移失败，目录或文件不存在：{in_path}")

        # 分布式锁：多实例同时处理同一文件/目录时互斥
        lock_key = f"filetransfer:media:{hashlib.md5(in_path.encode(), usedforsecurity=False).hexdigest()}"
        lock = get_lock_manager().create_lock(lock_key, ttl_seconds=3600)
        acquired = lock.acquire()
        if not acquired:
            log.info(f"[Rmt]{in_path} 正在其他实例转移中，跳过")
            return self._finish_transfer(False, f"文件正在转移中：{in_path}")

        with lock:
            if not operation:
                operation = self._default_operation

            self.progress.start(ProgressKey.FileTransfer)
            assert operation is not None
            log.info(f"[Rmt]开始处理：{in_path}，转移方式：{operation}")

            # 刷新路径解析配置（媒体库路径变更后无需重启即可生效）
            self._path_resolver.refresh()

            episode = episode if episode else (None, False)

            # ---------- 阶段 1：发现文件 ----------
            bluray_disk_dir, file_list = self._discover_files(in_path, files, episode, min_filesize)
            if file_list is None:
                return self._finish_transfer(False, "输入路径错误")
            if not file_list:
                return self._finish_transfer(
                    bluray_disk_dir is not None, "目录下未找到媒体文件" if bluray_disk_dir is None else ""
                )

            # ---------- 阶段 2：过滤 ----------
            file_list, msg = self.check_ignore(file_list=file_list)
            if not file_list:
                return self._finish_transfer(True, msg)

            if in_from == SyncType.MON:
                file_list = list(filter(self._history.is_transfer_notin_blacklist, file_list))
                if not file_list:
                    log.info("[Rmt]所有文件均已成功转移过")
                    return self._finish_transfer(True, "没有新文件需要处理")

            # ---------- 阶段 3：查下载记录 + 批量识别 ----------
            dl_season = None
            dl_episode = None
            if not tmdb_info:
                tmdb_info, media_type, dl_season, dl_episode = self._lookup_download_record(in_path)

            medias = self.media.get_media_info_on_files(file_list, tmdb_info, media_type, season, episode[0])
            if not medias:
                return self._finish_transfer(False, "搜索媒体信息出错")

            # 订阅/下载历史已知季集时兜底：文件名解析失败的动漫单集用订阅记录的集号补齐，
            # 避免"无法从文件名中识别出集数"导致订阅下载的剧集无法入库
            fallback_season = season if season is not None else dl_season
            fallback_ep = fallback_episode if fallback_episode is not None else dl_episode
            if fallback_season is not None or fallback_ep is not None:
                for _path, _info in medias.items():
                    if fallback_season is not None and _info.begin_season is None and _info.type != MediaType.MOVIE:
                        _info.begin_season = fallback_season
                    if fallback_ep is not None and _info.begin_episode is None:
                        _info.begin_episode = fallback_ep
                log.info(f"[Rmt]按订阅/下载记录补齐季集: S{fallback_season or '-'}E{fallback_ep or '-'}")

            self.progress.update(ptype=ProgressKey.FileTransfer, text=f"共 {len(medias)} 个文件需要处理...")

            # ---------- 阶段 4：逐个文件转移 ----------
            result = self._transfer_files_loop(
                medias,
                in_from,
                in_path,
                operation,
                target_dir,
                unknown_dir,
                bluray_disk_dir,
                episode,
                udf_flag,
                dst_backend,
            )

            # ---------- 阶段 5：后处理 ----------
            return self._transfer_post_process(result, in_from, in_path, operation, root_path)

    # ---------- 转移流水线私有方法 ----------

    def _finish_transfer(self, status, message):
        self.progress.update(
            ptype=ProgressKey.FileTransfer, value=100, text=f"转移{'成功' if status else '失败'}：{message}！"
        )
        self.progress.end(ProgressKey.FileTransfer)
        return status, message

    def _discover_files(self, in_path, files, episode, min_filesize):
        """发现待处理文件列表，返回 (bluray_disk_dir, file_list)."""
        bluray_disk_dir = None
        if not files:
            if os.path.isdir(in_path):
                if PathUtils.is_invalid_path(in_path):
                    return None, None
                bluray_disk_dir = PathUtils.get_bluray_dir(in_path)
                if bluray_disk_dir:
                    file_list = [bluray_disk_dir]
                    log.info(f"[Rmt]当前为蓝光原盘文件夹：{in_path!s}")
                else:
                    now_filesize = self._min_filesize
                    if str(min_filesize or "0") != "0":
                        ms_str = str(min_filesize)
                        if ms_str.isdigit():
                            now_filesize = int(ms_str) * 1024 * 1024
                    file_list = PathUtils.get_dir_files(
                        in_path=in_path, episode_format=episode[0], exts=RMT_MEDIAEXT, filesize=now_filesize
                    )
                    if not file_list:
                        log.warn(
                            f"[Rmt]{in_path} 目录下未找到媒体文件，"
                            f"最小文件大小限制为 {StringUtils.str_filesize(now_filesize)}"
                        )
            else:
                if os.path.splitext(in_path)[-1].lower() not in RMT_MEDIAEXT:
                    log.warn(f"[Rmt]不支持的媒体文件格式，不处理：{in_path}")
                    return None, []
                bluray_disk_dir = PathUtils.get_bluray_dir(in_path)
                if bluray_disk_dir:
                    file_list = [bluray_disk_dir]
                else:
                    file_list = [in_path]
        else:
            file_list = files
        return bluray_disk_dir, file_list

    def _lookup_download_record(self, in_path):
        download_info = self._history.download_repo.get_download_history_by_path(in_path)
        if download_info and os.path.isdir(in_path):
            # 目录路径命中多条下载记录（聚合目录）：若都指向同一部剧则用其 tmdb 提示，
            # 否则不可靠，跳过避免错误套用
            count = self._history.download_repo.count_download_history_by_path(in_path)
            if count and count > 1:
                records = self._history.download_repo.get_download_history_list_by_path(in_path) or []
                tmdb_ids = {str(r.TMDBID) for r in records if getattr(r, "TMDBID", None)}
                if records and len(tmdb_ids) == 1:
                    download_info = records[0]
                else:
                    log.debug(f"[Rmt]{in_path} 命中 {count} 条下载记录，聚合目录多部剧，跳过")
                    return None, None, None, None
        if not download_info and os.path.isfile(in_path):
            parent = os.path.dirname(in_path)
            # 文件回退父目录时，父目录若是聚合目录（多条下载记录）同样不可靠，跳过
            parent_count = self._history.download_repo.count_download_history_by_path(parent)
            if parent_count and parent_count > 1:
                log.debug(f"[Rmt]{in_path} 父目录 {parent} 命中 {parent_count} 条下载记录，聚合，跳过")
                return None, None, None, None
            download_info = self._history.download_repo.get_download_history_by_path(parent)
        if download_info and str(download_info.TMDBID or ""):
            log.info(f"[Rmt]{in_path} 找到下载记录，TMDBID：{download_info.TMDBID}")
            parsed_type = MediaType.from_string(download_info.TYPE)
            media_type = parsed_type
            dl_season, dl_episode = None, None
            se = getattr(download_info, "SE", "") or ""
            if se:
                se_parsed = RegexParser().parse(str(se))
                if se_parsed:
                    dl_season = se_parsed.season
                    dl_episode = se_parsed.episode
            return (
                self.media.get_tmdb_info(mtype=media_type, tmdbid=download_info.TMDBID),
                media_type,
                dl_season,
                dl_episode,
            )
        return None, None, None, None

    def _transfer_files(
        self,
        medias,
        in_from,
        in_path,
        operation,
        target_dir,
        unknown_dir,
        bluray_disk_dir,
        episode,
        udf_flag,
        dst_backend,
    ):
        """按目标目录分组并发转移，同一目录内串行避免重命名冲突."""
        if bluray_disk_dir or len(medias) <= 1 or self._thread_executor is None:
            return self._transfer_files_loop(
                medias,
                in_from,
                in_path,
                operation,
                target_dir,
                unknown_dir,
                bluray_disk_dir,
                episode,
                udf_flag,
                dst_backend,
            )

        groups = defaultdict(dict)
        for file_item, media in medias.items():
            dist_path = target_dir or self._path_resolver.get_best_target_path(
                mtype=media.type, in_path=in_path, size=getattr(media, "size", 0)
            )
            if not dist_path:
                dist_path = ""
            groups[dist_path][file_item] = media

        def _transfer_group(group_medias: dict) -> dict:
            return self._transfer_files_loop(
                group_medias,
                in_from,
                in_path,
                operation,
                target_dir,
                unknown_dir,
                bluray_disk_dir,
                episode,
                udf_flag,
                dst_backend,
            )

        results = self._run_parallel(list(groups.values()), _transfer_group)
        return self._merge_transfer_results([r for r in results if r is not None])

    def _merge_transfer_results(self, results: list[dict]) -> dict:
        """合并多组文件转移结果."""
        merged = {
            "total_count": 0,
            "failed_count": 0,
            "alert_count": 0,
            "alert_messages": [],
            "message_medias": {},
            "success_flag": True,
            "error_message": "",
            "exist_filenum": 0,
        }
        seen_messages = set()
        for result in results:
            merged["total_count"] += result.get("total_count", 0)
            merged["failed_count"] += result.get("failed_count", 0)
            merged["alert_count"] += result.get("alert_count", 0)
            for msg in result.get("alert_messages", []):
                if msg not in seen_messages:
                    seen_messages.add(msg)
                    merged["alert_messages"].append(msg)
            merged["message_medias"].update(result.get("message_medias", {}))
            merged["exist_filenum"] += result.get("exist_filenum", 0)
            if not result.get("success_flag", True):
                merged["success_flag"] = False
            if not merged["error_message"] and result.get("error_message"):
                merged["error_message"] = result.get("error_message")
        return merged

    def _run_parallel(self, items: list, func: Callable[[Any], Any]) -> list[Any]:
        """对无依赖任务使用线程池并发执行；失败隔离，返回结果列表."""
        if not items or self._thread_executor is None:
            return [func(item) for item in items]

        def _wrapper(item):
            try:
                return func(item)
            except Exception as err:
                ExceptionUtils.exception_traceback(err)
                return None

        futures: list[Future] = [self._thread_executor.submit(_wrapper, item) for item in items]
        wait(futures)
        return [f.result() for f in futures]

    def _transfer_files_loop(
        self,
        medias,
        in_from,
        in_path,
        operation,
        target_dir,
        unknown_dir,
        bluray_disk_dir,
        episode,
        udf_flag,
        dst_backend,
    ):
        failed_count = 0
        alert_count = 0
        alert_messages = []
        total_count = 0
        total_exist_filenum = 0
        message_medias = {}
        success_flag = True
        error_message = ""

        for file_item, media in medias.items():
            try:
                total_count += 1
                if not udf_flag and re.search(r"[./\s\[]+Sample[/\.\s\]]+", file_item, re.IGNORECASE):
                    log.warn(f"[Rmt]{file_item} 可能是预告片，跳过...")
                    continue

                file_name = os.path.basename(file_item)
                self.progress.update(
                    ptype=ProgressKey.FileTransfer,
                    value=round(total_count / len(medias) * 100) - (0.5 / len(medias) * 100),
                    text=f"正在处理：{file_name} ...",
                )

                reg_path = bluray_disk_dir if bluray_disk_dir else file_item

                if (
                    not media
                    or not media.tmdb_info
                    or not media.get_title_string()
                    or media.get_title_string().strip().isdigit()
                    or len(media.get_title_string().strip()) < 2
                    or not int(media.tmdb_id or 0)
                ):
                    fc, ac, am = self._handle_unrecognized_file(
                        file_item, reg_path, in_path, unknown_dir, operation, target_dir, udf_flag, alert_messages
                    )
                    failed_count += fc
                    alert_count += ac
                    alert_messages = am
                    if fc > 0:
                        success_flag = False
                    if udf_flag:
                        return {
                            "total_count": total_count,
                            "failed_count": failed_count,
                            "alert_count": alert_count,
                            "alert_messages": alert_messages,
                            "message_medias": message_medias,
                            "success_flag": False,
                            "error_message": "无法识别媒体信息",
                        }
                    continue

                media.size = os.path.getsize(file_item)
                dist_path = target_dir or self._path_resolver.get_best_target_path(
                    mtype=media.type, in_path=in_path, size=media.size
                )
                if not dist_path:
                    log.error("[Rmt]文件转移失败，目的路径不存在！")
                    failed_count += 1
                    alert_count += 1
                    alert_messages.append("目的路径不存在")
                    continue
                resolved_backend = dst_backend or self._path_resolver.resolve_dst_backend(dist_path, media.type)
                if not os.path.exists(dist_path) and not resolved_backend:
                    return {
                        "total_count": total_count,
                        "failed_count": failed_count,
                        "alert_count": alert_count,
                        "alert_messages": alert_messages,
                        "message_medias": message_medias,
                        "success_flag": False,
                        "error_message": f"目录不存在：{dist_path}",
                    }

                fc, ac, am, exist_filenum, new_file, ret_file_path, ret_dir_path = self._do_transfer_file(
                    file_item,
                    media,
                    dist_path,
                    bluray_disk_dir,
                    operation,
                    reg_path,
                    target_dir,
                    udf_flag,
                    alert_messages,
                    resolved_backend,
                )
                failed_count += fc
                alert_count += ac
                alert_messages = am
                total_exist_filenum += exist_filenum
                # 失败或已存在（转移历史/目标文件已存在）都不进入成功处理与消息聚合
                if fc > 0:
                    success_flag = False
                if fc > 0 or exist_filenum > 0:
                    continue

                file_ext = os.path.splitext(file_item)[-1]
                media.set_tmdb_info(
                    self.media.get_tmdb_info(mtype=media.type, tmdbid=media.tmdb_id, append_to_response="all")
                )
                out_path = new_file if not bluray_disk_dir else ret_dir_path
                season_episode = media.get_season_episode_string() if out_path else media.get_season_string()
                media_dto = TransferMediaDTO(
                    title=media.title or "",
                    type_value=media.type.value if media.type else "",
                    category=media.category or "",
                    tmdb_id=int(media.tmdb_id) if media.tmdb_id else 0,
                    year=media.year or "",
                    season_episode=season_episode,
                )

                self._history.insert_transfer_history(
                    in_from=in_from,
                    rmt_mode=operation,
                    in_path=reg_path,
                    out_path=out_path or "",
                    dest=dist_path,
                    media_info=media_dto,
                    dst_backend=dst_backend.id if hasattr(dst_backend, "id") else (dst_backend or "local"),
                )

                # 转移成功：若该文件曾进入未识别列表，标记为已识别（不再依赖手动指定季集标志）
                self._history.update_transfer_unknown_state(reg_path)

                if media.type == MediaType.MOVIE:
                    self.message.send_transfer_movie_message(
                        in_from, media, exist_filenum, self._path_resolver.movie_category_flag or False
                    )
                else:
                    message_key = f"{media.get_title_string()}-{media.get_season_string()}"
                    if not message_medias.get(message_key):
                        message_medias[message_key] = media
                    if not message_medias[message_key].is_in_episode(media.get_episode_list()):
                        message_medias[message_key].total_episodes += media.total_episodes
                        message_medias[message_key].size += media.size

                self.scraper.gen_scraper_files(
                    media=media,
                    dir_path=ret_dir_path,
                    file_name=os.path.basename(ret_file_path or ret_dir_path or ""),
                    file_ext=file_ext,
                    dst_backend=dst_backend,
                )

                self._publish_subtitle_download(media, ret_file_path, file_ext, bool(bluray_disk_dir))
                self._publish_transfer_finished(in_path, file_item, out_path, dist_path, media)
                # TV/动漫单集转移完成事件（驱动订阅进度更新）
                if media.type in (MediaType.TV, MediaType.ANIME) and media.get_episode_list():
                    self._publish_episode_transferred(media)

                self.progress.update(
                    ptype=ProgressKey.FileTransfer,
                    value=round(total_count / len(medias) * 100),
                    text=f"{file_name} 转移完成",
                )

            except (ServiceError, RepositoryError, DomainError):
                raise
            except Exception as err:
                ExceptionUtils.exception_traceback(err)
                log.error(f"[Rmt]文件转移时发生错误：{err!s}")
                failed_count += 1
                success_flag = False
                if not error_message:
                    error_message = str(err)

        return {
            "total_count": total_count,
            "failed_count": failed_count,
            "alert_count": alert_count,
            "alert_messages": alert_messages,
            "message_medias": message_medias,
            "success_flag": success_flag,
            "error_message": error_message,
            "exist_filenum": total_exist_filenum,
        }

    def _publish_subtitle_download(self, media, ret_file_path, file_ext, bluray):
        self._thread_executor.submit(
            self._event_bus.publish,
            Event(
                event_type=SUBTITLE_DOWNLOAD,
                payload=SubtitleDownloadPayload(
                    media_info=media.to_dict(),
                    file=ret_file_path,
                    file_ext=file_ext,
                    bluray=bluray,
                ),
            ),
        )

    def _publish_transfer_finished(self, in_path, file_item, out_path, dist_path, media):
        self._thread_executor.submit(
            self._event_bus.publish,
            Event(
                event_type=MEDIA_TRANSFER_FINISHED,
                payload=MediaTransferFinishedPayload(
                    in_path=in_path,
                    file=file_item,
                    target_path=out_path,
                    dest=dist_path,
                    media_info=media.to_dict(),
                ),
            ),
        )

    def _publish_episode_transferred(self, media):
        self._thread_executor.submit(
            self._event_bus.publish,
            Event(
                event_type=MEDIA_EPISODE_TRANSFERRED,
                payload=MediaEpisodeTransferredPayload(
                    tmdb_id=media.tmdb_id,
                    title=media.title,
                    season=media.get_season_seq(),
                    episodes=media.get_episode_list(),
                    total_episodes=media.total_episodes,
                ),
            ),
        )

    def _handle_unrecognized_file(
        self, file_item, reg_path, in_path, unknown_dir, operation, target_dir, udf_flag, alert_messages
    ):
        file_name = os.path.basename(file_item)
        error = "无法识别媒体信息"
        # 已在未识别列表：跳过（无论 STATE），避免每周期重复识别报错/重复通知
        if self._history.is_transfer_unknown_exists(reg_path):
            return 1, 0, alert_messages
        insert = self._history.is_need_insert_transfer_unknown(reg_path)
        if not insert:
            return 1, 0, alert_messages
        log.warn(f"[Rmt]{file_name} {error}！")
        self.progress.update(ptype=ProgressKey.FileTransfer, text=error)
        self._history.insert_transfer_unknown(reg_path, target_dir, operation)
        if error not in alert_messages:
            alert_messages = alert_messages + [error]
        if unknown_dir:
            log.warn(f"[Rmt]{file_name} 按原文件名转移到未识别目录：{unknown_dir}")
            new_file = os.path.join(unknown_dir, os.path.basename(file_item))
            self._engine.transfer(file_item, new_file, operation)
        elif self._path_resolver.unknown_path:
            p = self._path_resolver._get_best_unknown_path(in_path)
            if p:
                log.warn(f"[Rmt]{file_name} 按原文件名转移到未识别目录：{p}")
                new_file = os.path.join(p, os.path.basename(file_item))
                self._engine.transfer(file_item, new_file, operation)
        else:
            log.error(f"[Rmt]{file_name} {error}！")
        return 1, 1, alert_messages

    @staticmethod
    def _episode_in_history(history, episode) -> bool:
        """判断某集是否已存在于转移历史（支持 S01E01 与 S01E01-E05 格式）."""
        for h in history or []:
            se = getattr(h, "season_episode", None) or ""
            try:
                ep_part = str(se).split("E")[-1].strip()
                if "-" in ep_part:
                    a, b = ep_part.split("-")
                    if int(a) <= int(episode) <= int(b):
                        return True
                elif ep_part.isdigit() and int(ep_part) == int(episode):
                    return True
            except Exception:
                continue
        return False

    def _do_transfer_file(
        self,
        file_item,
        media,
        dist_path,
        bluray_disk_dir,
        operation,
        reg_path,
        target_dir,
        udf_flag,
        alert_messages,
        dst_backend=None,
    ):
        dir_exist_flag, ret_dir_path, file_exist_flag, ret_file_path = self._existence.is_media_exists(
            dist_path, media, dst_backend
        )
        file_ext = os.path.splitext(file_item)[-1]
        new_file = ret_file_path
        exist_filenum = 0

        # 结合转移历史去重：该 tmdb+季+集已转移过则跳过，
        # 避免目标路径规则变化（如分类子目录调整）导致重复入库
        if media.type != MediaType.MOVIE and media.tmdb_id and media.begin_season and media.begin_episode is not None:
            try:
                season_str = f"S{media.begin_season:02d}"
                history = self._history.get_transfer_info_by(tmdbid=media.tmdb_id, season=season_str) or []
                if history and self._episode_in_history(history, media.begin_episode):
                    log.warn(
                        f"[Rmt]剧集已在转移历史中（{media.get_season_episode_string()}），跳过："
                        f"{ret_file_path or file_item}"
                    )
                    # 已转移过则写入黑名单，避免目录同步每周期重复识别
                    self._history.insert_transfer_blacklist(file_item)
                    return 0, 0, alert_messages, 1, new_file, ret_file_path, ret_dir_path
            except Exception as e:  # noqa: BLE001
                log.debug(f"[Rmt]转移历史去重查询失败: {e}")

        if dir_exist_flag:
            if bluray_disk_dir:
                log.warn(f"[Rmt]蓝光原盘目录已存在：{ret_dir_path}")
                return 1, 0, alert_messages, 0, new_file, ret_file_path, ret_dir_path
            if file_exist_flag and ret_file_path:
                exist_filenum = 1
                if udf_flag:
                    # 仅手动转移允许覆盖已存在文件；自动同步（监控/目录同步）跳过
                    old = ret_file_path
                    base, _ = os.path.splitext(ret_file_path)
                    new_file = f"{base}{file_ext}"
                    log.info(f"[Rmt]文件 {old} 已存在，覆盖为 {new_file} ...")
                    self._engine.transfer(
                        file_item, new_file, operation, over_flag=True, old_file=old, dst_backend=dst_backend
                    )
                    return 0, 0, alert_messages, exist_filenum, new_file, ret_file_path, ret_dir_path
                else:
                    log.warn(f"[Rmt]文件 {ret_file_path} 已存在，跳过")
                    return 0, 0, alert_messages, exist_filenum, new_file, ret_file_path, ret_dir_path
        else:
            if not ret_dir_path:
                return self._record_fail(
                    file_item,
                    reg_path,
                    target_dir,
                    operation,
                    udf_flag,
                    alert_messages,
                    "识别失败，无法从文件名中识别出季集信息",
                )
            elif not dst_backend:
                os.makedirs(ret_dir_path)

        if bluray_disk_dir:
            if not ret_dir_path:
                return self._record_fail(
                    file_item,
                    reg_path,
                    target_dir,
                    operation,
                    udf_flag,
                    alert_messages,
                    "识别失败，无法获取蓝光目录路径",
                )
            self._engine.transfer_bluray_dir(file_item, ret_dir_path, operation)
        elif not ret_file_path:
            return self._record_fail(
                file_item,
                reg_path,
                target_dir,
                operation,
                udf_flag,
                alert_messages,
                "识别失败，无法从文件名中识别出集数",
            )
        else:
            ret_file_path = f"{ret_file_path}{file_ext}"
            new_file = ret_file_path
            self._engine.transfer(file_item, ret_file_path, operation, over_flag=False, dst_backend=dst_backend)
        return 0, 0, alert_messages, exist_filenum, new_file, ret_file_path, ret_dir_path

    def _record_fail(self, file_item, reg_path, target_dir, operation, udf_flag, alert_messages, msg):
        self.progress.update(ptype=ProgressKey.FileTransfer, text=msg)
        insert = self._history.is_need_insert_transfer_unknown(reg_path)
        if insert:
            self._history.insert_transfer_unknown(reg_path, target_dir, operation)
        if msg not in alert_messages and insert:
            alert_messages = alert_messages + [msg]
        return 1, 1 if insert else 0, alert_messages, 0, None, None, None

    def _transfer_post_process(self, result, in_from, in_path, operation, root_path) -> tuple[bool, str]:
        if result["message_medias"]:
            self.message.send_transfer_tv_message(
                result["message_medias"],
                in_from,
                result.get("exist_filenum", 0),
                self._path_resolver.tv_category_flag or False,
            )

        total_count = result["total_count"]
        failed_count = result["failed_count"]
        alert_count = result["alert_count"]
        alert_messages = result["alert_messages"]
        success_flag = result["success_flag"]
        error_message = result["error_message"]

        log.info(f"[Rmt]{in_path} 处理完成，总数：{total_count}，失败：{failed_count}")
        if alert_count > 0:
            reason = "、".join(alert_messages)
            self._event_bus.publish(
                Event(
                    event_type=TRANSFER_FAIL,
                    payload=TransferFailPayload(path=in_path, count=alert_count, reason=reason),
                )
            )
            self.message.send_transfer_fail_message(in_path, alert_count, reason)
        elif failed_count == 0:
            if (
                operation == "move"
                and os.path.exists(in_path)
                and os.path.isdir(in_path)
                and not root_path
                and not PathUtils.get_dir_files(in_path=in_path, exts=RMT_MEDIAEXT)
                and not PathUtils.get_dir_files(in_path=in_path, exts=[".!qb", ".part"])
            ):
                log.info(f"[Rmt]目录下已无媒体文件，移动模式下删除目录：{in_path}")
                shutil.rmtree(in_path)
        return self._finish_transfer(success_flag, error_message)

    def transfer_manually(self, s_path, t_path, operation):
        """全量转移，用于使用命令调用."""
        if not s_path:
            return
        if not os.path.exists(s_path):
            log.warn(f"[Rmt]源目录不存在：{s_path}")
            return

        lock_key = f"filetransfer:manual:{hashlib.md5(s_path.encode(), usedforsecurity=False).hexdigest()}"
        lock = get_lock_manager().create_lock(lock_key, ttl_seconds=3600)
        acquired = lock.acquire()
        if not acquired:
            log.warn(f"[Rmt]源目录正在转移中：{s_path}")
            return

        try:
            if t_path and not os.path.exists(t_path):
                log.warn(f"[Rmt]目的目录不存在：{t_path}")
                return
            log.info(f"[Rmt]转移模式为：{operation}")
            log.info(f"[Rmt]正在转移以下目录中的全量文件：{s_path}")
            paths = [
                path
                for path in PathUtils.get_dir_level1_medias(s_path, RMT_MEDIAEXT)
                if not PathUtils.is_invalid_path(path)
            ]

            def _transfer_one(path: str) -> None:
                ret, ret_msg = self.transfer_media(
                    in_from=SyncType.MAN, in_path=path, target_dir=t_path, operation=operation
                )
                if not ret:
                    log.error(f"[Rmt]{path} 处理失败：{ret_msg}")

            self._run_parallel(paths, _transfer_one)
        finally:
            lock.release()

    def get_sync_backend_by_dest(self, dest: str) -> str:
        """根据目的目录查找对应同步配置的目标后端."""
        if not dest:
            return "local"
        try:
            for entity in self._sync_repo.get_all():
                if str(entity.dest or "") == dest:
                    return str(entity.dst_backend or "local") or "local"
        except (ServiceError, RepositoryError, DomainError):
            raise
        except Exception:
            log.error("[Rmt]获取同步配置失败，无法根据目的目录识别目标后端，默认使用 local")
        return "local"
