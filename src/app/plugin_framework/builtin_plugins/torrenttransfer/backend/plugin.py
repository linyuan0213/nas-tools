"""
TorrentTransfer Plugin v2
定期转移下载器中的做种任务到另一个下载器
"""

import os.path
from copy import deepcopy
from threading import Event
from typing import Any

from bencode import bdecode, bencode

import log
from app.media import meta_info
from app.plugin_framework.context import PluginContext
from app.schemas.download import TorrentStatus
from app.sites.torrent import Torrent
from app.utils.json_utils import JsonUtils
from app.utils.path_utils import get_temp_path


class TorrentTransferPlugin:
    """自动转移做种插件"""

    def __init__(self, ctx: PluginContext, downloader: Any):
        self.ctx = ctx
        self._downloader = downloader
        self._event = Event()
        self._recheck_torrents = {}
        self._is_recheck_running = False
        self._torrent_tags = ["已整理", "转移做种"]

    def _get_config(self):
        return self.ctx.get_config() or {}

    def on_enable(self):
        self.ctx.info("自动转移做种插件已启用")
        self._start_service()

    def on_disable(self):
        self.ctx.info("自动转移做种插件已禁用")
        self._stop_service()

    def on_hook(self, event, data):
        if event == "plugin.config_changed":
            if data.get("plugin_id") == self.ctx.plugin_id:
                self.ctx.info("配置已变更，重载服务")
                self._stop_service()
                self._start_service()

    def run(self):
        """立即运行转移"""
        self.ctx.info("手动触发转移做种")
        self._do_transfer(manual=True)

    def _start_service(self):
        config = self._get_config()
        if not self._get_state():
            return

        cron = config.get("cron")
        if cron:
            self.ctx.info(f"转移做种服务启动，周期：{cron}")
            self.ctx.schedule_cron("transfer", self._do_transfer, cron=str(cron))

        autostart = config.get("autostart", False)
        if autostart:
            self.ctx.schedule_interval("check_recheck", self._check_recheck, minutes=3)

    def _stop_service(self):
        self._event.set()
        try:
            self.ctx.remove_schedule("transfer")
            self.ctx.remove_schedule("transfer_once")
            self.ctx.remove_schedule("check_recheck")
        except Exception as e:  # noqa: BLE001
            log.debug(f"[Plugin]忽略异常: {e}")
        self._event.clear()

    def _get_state(self):
        config = self._get_config()
        return bool(
            config.get("enable", False)
            and config.get("cron")
            and config.get("fromdownloader")
            and config.get("todownloader")
            and config.get("fromtorrentpath")
        )

    def _get_downloader_id(self, val):
        """兼容字符串或列表配置"""
        if isinstance(val, list):
            return val[0] if val else None
        return val

    def _do_transfer(self, manual=False):
        config = self._get_config()
        if not config.get("enable", False) and not manual:
            return

        from_downloader = self._get_downloader_id(config.get("fromdownloader"))
        to_downloader = self._get_downloader_id(config.get("todownloader"))
        from_path = config.get("frompath")
        to_path = config.get("topath")
        nolabels = config.get("nolabels")
        nopaths = config.get("nopaths")
        deletesource = config.get("deletesource", False)
        autostart = config.get("autostart", False)
        notify = config.get("notify", False)
        from_torrent_path = config.get("fromtorrentpath")

        if not from_downloader or not to_downloader or not from_torrent_path:
            self.ctx.warn("移转做种服务未配置完整")
            return

        if not os.path.exists(from_torrent_path):
            self.ctx.error(f"源下载器种子文件保存路径不存在：{from_torrent_path}")
            return

        if from_downloader == to_downloader:
            self.ctx.error("源下载器和目的下载器不能相同")
            return

        downloader_type = self._downloader.get_downloader_type(downloader_id=from_downloader)
        to_downloader_type = self._downloader.get_downloader_type(downloader_id=to_downloader)

        torrents = self._downloader.get_completed_torrents(downloader_id=from_downloader)
        if not torrents:
            self.ctx.info("源下载器没有已完成种子")
            return

        self.ctx.info(f"下载器 {from_downloader} 已完成种子数：{len(torrents)}")

        hash_strs = []
        for torrent in torrents:
            if self._event.is_set():
                self.ctx.info("移转服务停止")
                return

            hash_str = torrent.id
            save_path = torrent.save_path

            if nopaths and save_path:
                skip = False
                for nopath in nopaths.split("\n"):
                    if nopath and os.path.normpath(save_path).startswith(os.path.normpath(nopath)):
                        self.ctx.info(f"种子 {hash_str} 保存路径 {save_path} 不需要移转，跳过")
                        skip = True
                        break
                if skip:
                    continue

            torrent_labels = torrent.labels
            if torrent_labels and nolabels:
                skip = False
                for label in nolabels.split(","):
                    if label in torrent_labels:
                        self.ctx.info(f"种子 {hash_str} 含有不转移标签 {label}，跳过")
                        skip = True
                        break
                if skip:
                    continue

            hash_strs.append({"hash": hash_str, "save_path": save_path})

        if not hash_strs:
            self.ctx.info("没有需要移转的种子")
            return

        self.ctx.info(f"需要移转的种子数：{len(hash_strs)}")
        total = len(hash_strs)
        success = 0
        fail = 0

        for hash_item in hash_strs:
            torrent_file = os.path.join(from_torrent_path, f"{hash_item.get('hash')}.torrent")
            if not os.path.exists(torrent_file):
                self.ctx.error(f"种子文件不存在：{torrent_file}")
                fail += 1
                continue

            # 查询hash值是否已经在目的下载器中
            torrent_info = self._downloader.get_torrents(downloader_id=to_downloader, ids=[hash_item.get("hash")])
            if torrent_info:
                self.ctx.debug(f"{hash_item.get('hash')} 已在目的下载器中，跳过")
                continue

            # 转换保存路径
            download_dir = self._convert_save_path(hash_item.get("save_path"), from_path, to_path)
            if not download_dir:
                self.ctx.error(f"转换保存路径失败：{hash_item.get('save_path')}")
                fail += 1
                continue

            # 如果是QB检查是否有Tracker，没有的话补充解析
            if downloader_type == "qbittorrent":
                content, _, _, retmsg = Torrent(site_engine=self.ctx.site_engine).read_torrent_content(torrent_file)
                if not content:
                    self.ctx.error(f"读取种子文件失败：{retmsg}")
                    fail += 1
                    continue
                try:
                    torrent_main = bdecode(content)
                    main_announce = torrent_main.get("announce")
                except Exception as err:
                    self.ctx.error(f"解析种子文件 {torrent_file} 失败：{err}")
                    fail += 1
                    continue

                if not main_announce:
                    self.ctx.info(f"{hash_item.get('hash')} 未发现tracker信息，尝试补充tracker信息...")
                    fastresume_file = os.path.join(from_torrent_path, f"{hash_item.get('hash')}.fastresume")
                    if not os.path.exists(fastresume_file):
                        self.ctx.error(f"fastresume文件不存在：{fastresume_file}")
                        fail += 1
                        continue
                    try:
                        with open(fastresume_file, "rb") as f:
                            fastresume = f.read()
                        torrent_fastresume = bdecode(fastresume)
                        fastresume_trackers = torrent_fastresume.get("trackers")
                        if (
                            isinstance(fastresume_trackers, list)
                            and len(fastresume_trackers) > 0
                            and fastresume_trackers[0]
                        ):
                            torrent_main["announce"] = fastresume_trackers[0][0]
                            torrent_file = os.path.join(get_temp_path(), f"{hash_item.get('hash')}.torrent")
                            with open(torrent_file, "wb") as f:
                                f.write(bencode(torrent_main))
                    except Exception as err:
                        self.ctx.error(f"解析fastresume文件 {fastresume_file} 失败：{err}")
                        fail += 1
                        continue

            # 发送到另一个下载器中下载
            _, download_id, retmsg = self._downloader.download(
                media_info=meta_info("自动转移做种"),
                torrent_file=torrent_file,
                is_paused=True,
                tag=deepcopy(self._torrent_tags),
                downloader_id=to_downloader,
                download_dir=download_dir,
                download_setting="-2",
            )
            if not download_id:
                self.ctx.warn(f"添加转移任务出错，错误原因：{retmsg or '下载器添加任务失败'}，种子文件：{torrent_file}")
                fail += 1
                continue

            self.ctx.info(f"成功添加转移做种任务，种子文件：{torrent_file}")

            if to_downloader_type == "qbittorrent":
                self._downloader.recheck_torrents(downloader_id=to_downloader, ids=[download_id])

            if deletesource:
                self._downloader.delete_torrents(
                    downloader_id=from_downloader, ids=[hash_item.get("hash")], delete_file=False
                )

            if autostart:
                if to_downloader not in self._recheck_torrents:
                    self._recheck_torrents[to_downloader] = []
                self._recheck_torrents[to_downloader].append(download_id)

            # 插入转种记录
            history_key = f"{int(from_downloader)}-{hash_item.get('hash')}"
            self._save_history(
                history_key,
                {
                    "to_download": int(to_downloader),
                    "to_download_id": download_id,
                    "delete_source": deletesource,
                },
            )
            success += 1

        if success > 0 and autostart:
            self._check_recheck()

        if notify:
            self.ctx.notify(title="[移转做种任务执行完成]", text=f"总数：{total}，成功：{success}，失败：{fail}")

        self.ctx.info("移转做种任务执行完成")

    def _check_recheck(self):
        if not self._recheck_torrents:
            return
        if self._is_recheck_running:
            return

        self._is_recheck_running = True
        try:
            for downloader_id, torrent_ids in list(self._recheck_torrents.items()):
                if not torrent_ids:
                    continue
                torrents = self._downloader.get_torrents(downloader_id=downloader_id, ids=torrent_ids)
                if torrents:
                    can_seeding = []
                    for torrent in torrents:
                        if (
                            torrent.status in [TorrentStatus.Paused, TorrentStatus.Stopped]
                            and torrent.progress >= 0.999
                        ):
                            can_seeding.append(torrent.id)
                    if can_seeding:
                        self.ctx.info(f"共 {len(can_seeding)} 个任务校验完成，开始辅种")
                        self._downloader.start_torrents(downloader_id=downloader_id, ids=can_seeding)
                        self._recheck_torrents[downloader_id] = list(set(torrent_ids) - set(can_seeding))
                else:
                    self._recheck_torrents[downloader_id] = []
        finally:
            self._is_recheck_running = False

    @staticmethod
    def _convert_save_path(save_path, from_root, to_root):
        if not save_path:
            return to_root
        if not to_root or not from_root:
            return save_path
        try:
            save_path = os.path.normpath(save_path).replace("\\", "/")
            from_root = os.path.normpath(from_root).replace("\\", "/")
            to_root = os.path.normpath(to_root).replace("\\", "/")
            if save_path.startswith(from_root):
                return save_path.replace(from_root, to_root, 1)
        except Exception as e:
            log.debug(f"[Plugin]路径转换异常: {e}")
        return save_path

    def _load_history(self):
        content = self.ctx.read_data("history.json")
        if content:
            try:
                return JsonUtils.loads(content)
            except Exception as e:  # noqa: BLE001
                log.debug(f"[Plugin]忽略异常: {e}")
        return {}

    def _save_history(self, key, value):

        data = self._load_history()
        data[key] = value
        self.ctx.write_data("history.json", JsonUtils.dumps(data, ensure_ascii=False, indent=2))
