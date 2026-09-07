"""Brush torrent lifecycle - 删种与停种逻辑."""

import time
from datetime import date
from typing import Any

import log
from app.core.exceptions import DomainError, RepositoryError, ServiceError
from app.domain.engine.brush_rule_engine import BrushRuleEngine
from app.domain.entities.brush import BrushTaskState
from app.domain.enums import SwitchState
from app.message import Message
from app.schemas.download import TorrentStatus
from app.sites.site_cache import SiteCache
from app.utils import ExceptionUtils, StringUtils


class BrushTorrentLifecycle:
    """
    刷流种子生命周期管理器
    职责：删种、停种规则执行与消息通知。
    """

    def __init__(self, helper, repo, downloader, sites: SiteCache, message: Message):
        self._helper = helper
        self._repo: Any = repo
        self._downloader: Any = downloader
        self._sites = sites
        self._message = message
        self._daily_deletes: dict[int, dict] = {}  # task_id → {"date": date, "count": int}

    @staticmethod
    def _remove_rule_needs_torrent_attr(remove_rule: dict | None) -> bool:
        """删种规则是否依赖种子详情页属性（free/hr），避免对每颗种子做无谓详情请求消耗站点限流."""
        if not remove_rule:
            return False
        return any(remove_rule.get(key) not in ("#", "N", None, "") for key in ("freestatus", "hr", "hr_time"))

    def remove_task_torrents(self, taskid: int | None, taskinfo: dict) -> None:
        if taskinfo.get("state") != BrushTaskState.RUNNING.value:
            return
        try:
            total_uploaded = 0
            total_downloaded = 0
            delete_ids: list[str] = []
            update_torrents: list[tuple[str, int, str]] = []

            site_id = taskinfo.get("site_id")
            task_name = taskinfo.get("name")
            downloader_id = taskinfo.get("downloader")
            remove_rule = taskinfo.get("remove_rule")
            downloader_cfg = self._downloader.get_downloader_conf(downloader_id)
            site_info = self._sites.get_sites(siteid=site_id)

            if not downloader_cfg:
                log.warn(f"[Brush]任务 {task_name} 下载器不存在")
                return

            task_torrents = self._repo.get_brushtask_torrents(taskid)
            torrent_id_maps = {item.DOWNLOAD_ID: item.ENCLOSURE for item in task_torrents if item.DOWNLOAD_ID}
            torrent_page_url_maps = {
                item.DOWNLOAD_ID: getattr(item, "PAGE_URL", "") or "" for item in task_torrents if item.DOWNLOAD_ID
            }
            torrent_ids = list(torrent_id_maps.keys())
            if not torrent_ids:
                return

            # 一次查询全部状态的种子，不再分两次过滤
            all_torrents = self._downloader.get_torrents(downloader_id, torrent_ids)
            if all_torrents is None:
                log.warn(f"[Brush]任务 {task_name} 获取种子列表失败")
                return

            all_ids = {t.id for t in all_torrents}
            absent_ids = set(torrent_ids) - all_ids

            # 按完成状态分组：未完成（含暂停 pausedDL/stoppedDL）→ 下载中，已完成 → 做种
            downloading = [t for t in all_torrents if getattr(t, "progress", 0) < 1.0]
            completed = [t for t in all_torrents if getattr(t, "progress", 0) >= 1.0]

            # 对做种/暂停/已完成的种子评估删种规则
            total_uploaded, total_downloaded, delete_ids, update_torrents = self._process_torrents(
                completed,
                taskinfo,
                downloader_cfg,
                site_info,
                remove_rule,
                total_uploaded,
                total_downloaded,
                delete_ids,
                update_torrents,
                torrent_id_maps,
                torrent_page_url_maps,
            )
            # 对正在下载的种子评估删种规则（含 dltime/pending_time）
            total_uploaded, total_downloaded, delete_ids, update_torrents = self._process_torrents(
                downloading,
                taskinfo,
                downloader_cfg,
                site_info,
                remove_rule,
                total_uploaded,
                total_downloaded,
                delete_ids,
                update_torrents,
                torrent_id_maps,
                torrent_page_url_maps,
                is_downloading=True,
            )

            # 下载器中已不存在的种子，清理 DB 记录
            if absent_ids:
                log.info(f"[Brush]任务 {task_name} 删除不存在的下载任务：{absent_ids}")
                for rid in absent_ids:
                    self._repo.delete_brushtask_torrent(taskid or 0, rid)

            removed_count = 0
            if delete_ids:
                daily_limit = self._apply_daily_delete_limit(taskid or 0, taskinfo, delete_ids)
                if daily_limit and not delete_ids:
                    log.info(f"[Brush]任务 {task_name} 已达到今日删种上限，停止删种")
                    return
                self._downloader.delete_torrents(downloader_id, delete_ids, delete_file=True)
                time.sleep(5)
                torrents = self._downloader.get_torrents(downloader_id, delete_ids)
                if torrents is None:
                    # 下载器不可达无法确认结果，保守视为全部删除失败（避免误标失管）
                    failed = set(delete_ids)
                else:
                    # 删除后仍存在的为失败种子
                    failed = {t.id for t in torrents}
                # 成功删除数 = 待删数 - 失败数
                removed_count = len([tid for tid in delete_ids if tid not in failed])
                if update_torrents:
                    # 仅成功删除的种子落库（t[2]=download_id），失败的保留
                    update_torrents = [t for t in update_torrents if t[2] not in failed]
                if update_torrents:
                    self._repo.update_brushtask_torrent_state(update_torrents)
                else:
                    log.info(f"[Brush]任务 {task_name} 本次检查未删除下载任务")

            self._repo.add_brushtask_upload_count(
                taskid or 0, total_uploaded, total_downloaded, removed_count + len(absent_ids)
            )
        except (ServiceError, RepositoryError, DomainError):
            raise
        except Exception as e:
            ExceptionUtils.exception_traceback(e)

    def _process_torrents(
        self,
        torrents,
        taskinfo,
        downloader_cfg,
        site_info,
        remove_rule,
        total_uploaded,
        total_downloaded,
        delete_ids,
        update_torrents,
        torrent_id_maps,
        torrent_page_url_maps=None,
        is_downloading=False,
    ):
        if torrent_page_url_maps is None:
            torrent_page_url_maps = {}
        task_name = taskinfo.get("name")
        sendmessage = taskinfo.get("sendmessage")
        downloader_id = taskinfo.get("downloader")
        download_dir = taskinfo.get("savepath")

        need_attr = self._remove_rule_needs_torrent_attr(remove_rule)
        for torrent in torrents:
            torrent_id = torrent.id
            total_uploaded += torrent.uploaded
            total_downloaded += torrent.downloaded

            enclosure = torrent_id_maps.get(torrent_id)
            torrent_url, torrent_attr = (None, {})
            if enclosure and need_attr:
                # 详情属性优先用详情页 URL（M-Team 等 enclosure 为一次性签名链接，无法提取 TID）
                attr_url = torrent_page_url_maps.get(torrent_id) or enclosure
                torrent_url, torrent_attr = self._helper.get_torrent_attr(
                    site_info if isinstance(site_info, dict) else {}, attr_url, use_cache=False
                )
                if torrent_attr is None:
                    # 详情属性抓取失败（限流/网络等）：不能据此判定“免费到期”而误删，
                    # 本轮跳过该种子，下个周期再评估
                    log.warn(f"[Brush]任务 {task_name} 种子 {torrent.name} 属性未知（详情抓取失败），跳过本轮删种判断")
                    continue

            torrent_params = {
                "seeding_time": torrent.seeding_time,
                "ratio": round(torrent.ratio or 0, 2),
                "uploaded": torrent.uploaded,
                "iatime": torrent.iatime,
                "avg_upspeed": torrent.avg_upload_speed,
                "upspeed": torrent.upload_speed,
                "add_time": torrent.add_time,
                "tracker_error": getattr(torrent, "tracker_error", ""),
                "freespace": self._downloader.get_free_space(downloader_id, download_dir),
                "torrent_attr": torrent_attr,
            }
            if is_downloading:
                torrent_params.update(
                    {
                        "dltime": torrent.download_time,
                        # 等待时间 = 进种时长（download_time），覆盖 Pending/Queued 等待态；
                        # 不能用 iatime（未活动时间）：从未活动的等待种子 iatime 为 0，等待时间永远不会触发
                        "pending_time": (
                            torrent.download_time
                            if torrent.status in (TorrentStatus.Pending, TorrentStatus.Queued)
                            else None
                        ),
                    }
                )

            need_delete, delete_type = BrushRuleEngine.check_remove_rule(remove_rule, torrent_params)
            if need_delete:
                delete_type_str = (
                    ",".join([d.value for d in delete_type]) if isinstance(delete_type, list) else delete_type.value
                )
                log.info(f"[Brush]{torrent.name} 达到删种条件：{delete_type_str}，删除任务...")
                if sendmessage:
                    self._send_remove_message(task_name, delete_type_str, torrent, downloader_cfg, torrent_params)
                if torrent_id not in delete_ids:
                    delete_ids.append(torrent_id)
                    self._repo.insert_brush_event(
                        task_id=taskinfo.get("id") or 0,
                        task_name=task_name,
                        torrent_name=torrent.name or "",
                        download_id=torrent_id,
                        action="delete",
                        reason=delete_type_str,
                        downloader_name=downloader_cfg.get("name", ""),
                        site_name=site_info.get("name", "") if isinstance(site_info, dict) else "",
                        torrent_url=torrent_page_url_maps.get(torrent_id, ""),
                    )
                    update_torrents.append((f"{torrent.uploaded},{torrent.downloaded}", taskinfo.get("id"), torrent_id))

        return total_uploaded, total_downloaded, delete_ids, update_torrents

    def _send_remove_message(self, task_name, delete_type, torrent, downloader_cfg, torrent_params):
        _msg_title = f"[刷流任务 {task_name} 删除做种]"
        _msg_text = (
            f"下载器名：{downloader_cfg.get('name')}\n"
            f"种子名称：{torrent.name}\n"
            f"种子大小：{StringUtils.str_filesize(torrent.size)}\n"
            f"已下载量：{StringUtils.str_filesize(torrent.downloaded)}\n"
            f"已上传量：{StringUtils.str_filesize(torrent.uploaded)}\n"
            f"分享比率：{torrent_params['ratio']}\n"
            f"添加时间：{torrent.add_time}\n"
            f"删除时间：{time.strftime('%Y-%m-%d %H:%M:%S', time.localtime(time.time()))}\n"
            f"删除规则：{delete_type}"
        )
        self._message.send_brushtask_remove_message(title=_msg_title, text=_msg_text)

    def stop_task_torrents(self, taskid: int | None, taskinfo: dict) -> None:
        if taskinfo.get("state") != BrushTaskState.RUNNING.value:
            return
        task_name = taskinfo.get("name")
        stop_rule = taskinfo.get("stop_rule")
        downloader_id = taskinfo.get("downloader")
        sendmessage = taskinfo.get("sendmessage")
        site_id = taskinfo.get("site_id")

        site_info = self._sites.get_sites(siteid=site_id)
        if not site_info:
            log.error(f"[Brush]刷流任务 {task_name} 的站点已不存在，无法刷流！")
            return

        log.info(f"[Brush]开始非免费种子暂停任务：{task_name}...")
        task_torrents = self._repo.get_brushtask_torrents(taskid)
        torrent_id_maps = {item.DOWNLOAD_ID: item.ENCLOSURE for item in task_torrents if item.DOWNLOAD_ID}
        torrent_page_url_maps = {
            item.DOWNLOAD_ID: getattr(item, "PAGE_URL", "") or "" for item in task_torrents if item.DOWNLOAD_ID
        }
        torrent_ids = list(torrent_id_maps.keys())
        if not torrent_id_maps:
            return

        downloader_cfg = self._downloader.get_downloader_conf(downloader_id)
        if not downloader_cfg:
            log.warn(f"[Brush]任务 {task_name} 下载器不存在")
            return

        downlaod_name = downloader_cfg.get("name")
        torrents = self._downloader.get_downloading_torrents(downloader_id=downloader_id, ids=torrent_ids)
        if torrents is None:
            log.warn(f"[Brush]任务 {task_name} 获取正在下载种子失败")
            return

        stopfree_enabled = stop_rule and stop_rule.get("stopfree") == SwitchState.ON.value
        for torrent in torrents:
            try:
                torrent_id = torrent.id
                torrent_name = torrent.name
                add_time = torrent.add_time
                enclosure = torrent_id_maps.get(torrent_id)
                if not enclosure:
                    continue
                torrent_attr = {}
                if stopfree_enabled:
                    # 详情属性优先用详情页 URL（M-Team 等 enclosure 为一次性签名链接，无法提取 TID）
                    attr_url = torrent_page_url_maps.get(torrent_id) or enclosure
                    torrent_url, torrent_attr = self._helper.get_torrent_attr(
                        site_info if isinstance(site_info, dict) else {}, attr_url, use_cache=False
                    )
                    if torrent_attr is None:
                        # 属性未知（抓取失败）：不据此执行停种，等待下轮
                        log.warn(f"[Brush]{torrent_name} 属性未知（详情抓取失败），跳过本轮停种判断")
                        continue
                    log.debug(f"[Brush]{torrent_url} 解析详情 {torrent_attr}")

                need_stop, stop_type = BrushRuleEngine.check_stop_rule(
                    stop_rule,
                    params={
                        "ratio": round(torrent.ratio or 0, 2),
                        "uploaded": torrent.uploaded,
                        "seeding_time": torrent.seeding_time,
                        "avg_upspeed": torrent.avg_upload_speed,
                        **torrent_attr,
                    },
                )
                if need_stop:
                    if isinstance(stop_type, list):
                        stop_type_str = ", ".join(t.value for t in stop_type)
                    else:
                        stop_type_str = stop_type.value
                    log.info(f"[Brush]{torrent_name} 触发停种条件：{stop_type_str}，暂停任务...")
                    self._downloader.stop_torrents(downloader_id, [torrent_id])
                    self._repo.insert_brush_event(
                        task_id=taskid or 0,
                        task_name=task_name,
                        torrent_name=torrent_name or "",
                        download_id=torrent_id or "",
                        action="stop",
                        reason=stop_type_str,
                        downloader_name=downlaod_name,
                        site_name=site_info.get("name", "") if isinstance(site_info, dict) else "",
                        torrent_url=torrent_page_url_maps.get(torrent_id, ""),
                    )
                    if sendmessage:
                        self._send_stop_message(task_name, torrent_name, downlaod_name, add_time)
            except Exception as e:
                ExceptionUtils.exception_traceback(e)

        if stopfree_enabled:
            self._resume_free_torrents(
                taskid,
                taskinfo,
                task_name,
                downloader_id,
                torrent_id_maps,
                downlaod_name,
                sendmessage,
                site_info,
                torrent_page_url_maps,
            )

    def _resume_free_torrents(
        self,
        taskid,
        taskinfo,
        task_name,
        downloader_id,
        torrent_id_maps,
        downlaod_name,
        sendmessage,
        site_info,
        torrent_page_url_maps=None,
    ):
        all_torrents = self._downloader.get_torrents(downloader_id, list(torrent_id_maps.keys()))
        if not all_torrents:
            return
        for torrent in all_torrents:
            if torrent.status not in (TorrentStatus.Paused, TorrentStatus.Stopped):
                continue
            enclosure = torrent_id_maps.get(torrent.id)
            if not enclosure:
                continue
            # 详情属性优先用详情页 URL（M-Team 等 enclosure 为一次性签名链接，无法提取 TID）
            attr_url = (torrent_page_url_maps or {}).get(torrent.id) or enclosure
            torrent_url, torrent_attr = self._helper.get_torrent_attr(
                site_info if isinstance(site_info, dict) else {}, attr_url, use_cache=False
            )
            if torrent_attr is None:
                # 属性未知（抓取失败）：暂不启动，等待下轮确认
                log.warn(f"[Brush]{torrent.name} 属性未知（详情抓取失败），暂不自动启动")
                continue
            if torrent_attr.get("free"):
                self._downloader.start_torrents(downloader_id, [torrent.id])
                log.info(f"[Brush]{torrent.name} 已恢复免费，自动启动")

    def _apply_daily_delete_limit(self, taskid: int, taskinfo: dict, delete_ids: list) -> bool:
        limit_str = taskinfo.get("daily_delete_limit", "")
        if not limit_str or not limit_str.isdigit():
            return False
        limit = int(limit_str)
        if limit <= 0:
            return False
        today = date.today()
        state = self._daily_deletes.get(taskid)
        if not state or state.get("date") != today:
            state = {"date": today, "count": 0}
            self._daily_deletes[taskid] = state
        remaining = limit - state["count"]
        if remaining <= 0:
            delete_ids.clear()
            return True
        if len(delete_ids) > remaining:
            del delete_ids[remaining:]
        state["count"] += len(delete_ids)
        return False

    def _send_stop_message(self, task_name, torrent_name, download_name, add_time):
        _msg_title = f"[刷流任务 {task_name} 暂停做种]"
        _msg_text = (
            f"下载器名：{download_name}\n"
            f"种子名称：{torrent_name}\n"
            f"添加时间：{add_time}\n"
            f"暂停时间：{time.strftime('%Y-%m-%d %H:%M:%S', time.localtime(time.time()))}\n"
            "暂停原因: free 时间到期"
        )
        self._message.send_brushtask_pause_message(title=_msg_title, text=_msg_text)
