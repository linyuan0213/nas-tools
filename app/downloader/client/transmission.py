import os.path
import re
import time
from datetime import datetime
from typing import Tuple

import transmission_rpc

from app.entities.torrentstatus import TorrentStatus
from app.entities.torrent import Torrent
import log
from app.utils import ExceptionUtils, StringUtils
from app.utils.types import DownloaderType
from app.downloader.client._base import _IDownloadClient


class Transmission(_IDownloadClient):
    # 下载器ID
    client_id = "transmission"
    # 下载器类型
    client_type = DownloaderType.TR
    # 下载器名称
    client_name = DownloaderType.TR.value

    # 参考transmission web，仅查询需要的参数，加速种子搜索
    _trarg = ["id", "name", "status", "labels", "hashString", "totalSize", "percentDone", "addedDate", "trackerStats",
              "leftUntilDone", "rateDownload", "rateUpload", "recheckProgress", "rateDownload", "rateUpload",
              "peersGettingFromUs", "peersSendingToUs", "uploadRatio", "uploadedEver", "downloadedEver", "downloadDir",
              "error", "errorString", "doneDate", "queuePosition", "activityDate", "trackers", "secondsSeeding", "eta"]

    # 私有属性
    _client_config = {}

    trc = None
    host = None
    port = None
    username = None
    password = None
    download_dir = []
    name = "测试"

    def __init__(self, config):
        self._client_config = config
        self.init_config()
        self.connect()
        # 设置未完成种子添加!part后缀
        self.trc.set_session(rename_partial_files=True)

    def init_config(self):
        if self._client_config:
            self.host = self._client_config.get('host')
            self.port = int(self._client_config.get('port')) if str(self._client_config.get('port')).isdigit() else 0
            self.username = self._client_config.get('username')
            self.password = self._client_config.get('password')
            self.download_dir = self._client_config.get('download_dir') or []
            self.name = self._client_config.get('name') or ""

    @classmethod
    def match(cls, ctype):
        return True if ctype in [cls.client_id, cls.client_type, cls.client_name] else False

    def get_type(self):
        return self.client_type

    def connect(self):
        if self.host and self.port:
            self.trc = self.__login_transmission()

    def __login_transmission(self):
        """
        连接transmission
        :return: transmission对象
        """
        try:
            # 登录
            trt = transmission_rpc.Client(host=self.host,
                                          port=self.port,
                                          username=self.username,
                                          password=self.password,
                                          timeout=60)
            return trt
        except Exception as err:
            ExceptionUtils.exception_traceback(err)
            log.error(f"【{self.client_name}】{self.name} 连接出错：{str(err)}")
            return None

    def get_status(self):
        return True if self.trc else False

    @staticmethod
    def __parse_ids(ids):
        """
        统一处理种子ID
        """
        if isinstance(ids, list) and any([str(x).isdigit() for x in ids]):
            ids = [int(x) for x in ids if str(x).isdigit()]
        elif not isinstance(ids, list) and str(ids).isdigit():
            ids = int(ids)
        return ids

    def get_torrents(self, ids=None, status=None, tag=None) -> Tuple[list[Torrent], bool]:
        """
        获取种子列表
        返回结果 种子列表, 是否有错误
        """
        if not self.trc:
            return [], True
        ids = self.__parse_ids(ids)
        try:
            torrents = self.trc.get_torrents(ids=ids, arguments=self._trarg)
            torrent_list: list[Torrent] = []
            for torrent in torrents:
                torrent_list.append(self.torrent_properties(torrent=torrent))
        except Exception as err:
            ExceptionUtils.exception_traceback(err)
            return [], True
        if status and not isinstance(status, list):
            status = [status]
        if tag and not isinstance(tag, list):
            tag = [tag]
        ret_torrents = []
        for torrent in torrent_list:
            if status and torrent.status not in status:
                continue
            labels = torrent.labels if hasattr(torrent, "labels") else []
            include_flag = True
            if tag:
                for t in tag:
                    if t and t not in labels:
                        include_flag = False
                        break
            if include_flag:
                ret_torrents.append(torrent)
        return ret_torrents, False

    def get_completed_torrents(self, ids=None, tag=None) -> list[Torrent]:
        """
        获取已完成的种子列表
        return 种子列表, 发生错误时返回None
        """
        if not self.trc:
            return None
        try:
            torrents, error = self.get_torrents(status=[TorrentStatus.Uploading], ids=ids, tag=tag)
            return None if error else torrents or []
        except Exception as err:
            ExceptionUtils.exception_traceback(err)
            return None

    def get_downloading_torrents(self, ids=None, tag=None) -> list[Torrent]:
        """
        获取正在下载的种子列表
        return 种子列表, 发生错误时返回None
        """
        if not self.trc:
            return None
        try:
            torrents, error = self.get_torrents(ids=ids,
                                                status=[TorrentStatus.Downloading],
                                                tag=tag)
            return None if error else torrents or []
        except Exception as err:
            ExceptionUtils.exception_traceback(err)
            return None

    def set_torrents_status(self, ids, tags=None):
        """
        设置种子为已整理状态
        """
        if not self.trc:
            return
        ids = self.__parse_ids(ids)
        # 合成标签
        if tags:
            if not isinstance(tags, list):
                tags = [tags, "已整理"]
            else:
                tags.append("已整理")
        else:
            tags = ["已整理"]
        # 打标签
        try:
            self.trc.change_torrent(labels=tags, ids=ids)
            log.info(f"【{self.client_name}】{self.name} 设置种子标签成功")
        except Exception as err:
            ExceptionUtils.exception_traceback(err)

    def set_torrents_tag(self, ids, tags):
        """
        设置种子为已整理状态
        """
        if not self.trc:
            return
        ids = self.__parse_ids(ids)
        # 打标签
        try:
            self.trc.change_torrent(labels=tags, ids=ids)
            log.info(f"【{self.client_name}】设置transmission种子标签成功")
        except Exception as err:
            ExceptionUtils.exception_traceback(err)

    def set_torrent_tag(self, tid, tag):
        """
        设置种子标签
        """
        if not tid or not tag:
            return
        ids = self.__parse_ids(tid)
        try:
            self.trc.change_torrent(labels=tag, ids=ids)
        except Exception as err:
            ExceptionUtils.exception_traceback(err)

    def change_torrent(self,
                       tid,
                       tag=None,
                       upload_limit=None,
                       download_limit=None,
                       ratio_limit=None,
                       seeding_time_limit=None):
        """
        设置种子
        :param tid: ID
        :param tag: 标签
        :param upload_limit: 上传限速 Kb/s
        :param download_limit: 下载限速 Kb/s
        :param ratio_limit: 分享率限制
        :param seeding_time_limit: 做种时间限制
        :return: bool
        """
        if not tid:
            return
        else:
            ids = self.__parse_ids(tid)
        if tag:
            if isinstance(tag, list):
                labels = tag
            else:
                labels = [tag]
        else:
            labels = []
        if upload_limit:
            uploadLimited = True
            uploadLimit = int(upload_limit)
        else:
            uploadLimited = False
            uploadLimit = 0
        if download_limit:
            downloadLimited = True
            downloadLimit = int(download_limit)
        else:
            downloadLimited = False
            downloadLimit = 0
        if ratio_limit:
            seedRatioMode = 1
            seedRatioLimit = round(float(ratio_limit), 2)
        else:
            seedRatioMode = 2
            seedRatioLimit = 0
        if seeding_time_limit:
            seedIdleMode = 1
            seedIdleLimit = int(seeding_time_limit)
        else:
            seedIdleMode = 2
            seedIdleLimit = 0
        try:
            self.trc.change_torrent(ids=ids,
                                    labels=labels,
                                    uploadLimited=uploadLimited,
                                    uploadLimit=uploadLimit,
                                    downloadLimited=downloadLimited,
                                    downloadLimit=downloadLimit,
                                    seedRatioMode=seedRatioMode,
                                    seedRatioLimit=seedRatioLimit,
                                    seedIdleMode=seedIdleMode,
                                    seedIdleLimit=seedIdleLimit)
        except Exception as err:
            ExceptionUtils.exception_traceback(err)

    def get_transfer_task(self, tag=None, match_path=None):
        """
        获取下载文件转移任务种子
        """
        # 处理下载完成的任务
        torrents = self.get_completed_torrents() or []
        trans_tasks = []
        for torrent in torrents:
            torrent_tags = torrent.labels or ""
            # 含"已整理"tag的不处理
            if "已整理" in torrent_tags:
                continue
            # 开启标签隔离，未包含指定标签的不处理
            if tag and tag not in torrent_tags:
                log.debug(f"【{self.client_name}】{self.name} 开启标签隔离， {torrent.name} 未包含指定标签：{tag}")
                continue
            path = torrent.save_path
            # 无法获取下载路径的不处理
            if not path:
                log.debug(f"【{self.client_name}】{self.name} 未获取到 {torrent.name} 下载保存路径")
                continue
            true_path, replace_flag = self.get_replace_path(path, self.download_dir)
            # 开启目录隔离，未进行目录替换的不处理
            if match_path and not replace_flag:
                log.debug(f"【{self.client_name}】{self.name} 开启目录隔离，但 {torrent.name} 未匹配下载目录范围")
                continue
            trans_tasks.append({
                'path': os.path.join(true_path, torrent.name).replace("\\", "/"),
                'id': torrent.id,
                'tags': torrent.labels
            })
        return trans_tasks

    def get_remove_torrents(self, config=None):
        """
        获取自动删种任务
        """
        if not config:
            return []
        remove_torrents = []
        remove_torrents_ids = []
        torrents, error_flag = self.get_torrents(tag=config.get("filter_tags"),
                                                 status=config.get("tr_state"))
        if error_flag:
            return []
        ratio = config.get("ratio")
        # 做种时间 单位：小时
        seeding_time = config.get("seeding_time")
        # 大小 单位：GB
        size = config.get("size")
        minsize = size[0] * 1024 * 1024 * 1024 if size else 0
        maxsize = size[-1] * 1024 * 1024 * 1024 if size else 0
        # 平均上传速度 单位 KB/s
        upload_avs = config.get("upload_avs")
        savepath_key = config.get("savepath_key")
        tracker_key = config.get("tracker_key")
        for torrent in torrents:
            torrent_seeding_time = torrent.seeding_time
            torrent_upload_avs = torrent.avg_upload_speed
            if ratio and torrent.ratio <= ratio:
                continue
            if seeding_time and torrent_seeding_time <= seeding_time * 3600:
                continue
            if size and (torrent.size >= maxsize or torrent.size <= minsize):
                continue
            if upload_avs and torrent_upload_avs >= upload_avs * 1024:
                continue
            if savepath_key and not re.findall(savepath_key, torrent.save_path, re.I):
                continue
            if tracker_key:
                if not torrent.trackers:
                    continue
                else:
                    tacker_key_flag = False
                    for tracker in torrent.trackers:
                        if re.findall(tracker_key, tracker, re.I):
                            tacker_key_flag = True
                            break
                    if not tacker_key_flag:
                        continue
            remove_torrents.append({
                "id": torrent.id,
                "name": torrent.name,
                "site": StringUtils.get_url_sld(torrent.trackers[0]) if torrent.trackers else "",
                "size": torrent.size
            })
            remove_torrents_ids.append(torrent.id)
        if config.get("samedata") and remove_torrents:
            remove_torrents_plus = []
            for remove_torrent in remove_torrents:
                name = remove_torrent.get("name")
                size = remove_torrent.get("size")
                for torrent in torrents:
                    if torrent.name == name and torrent.size == size and torrent.id not in remove_torrents_ids:
                        remove_torrents_plus.append({
                            "id": torrent.id,
                            "name": torrent.name,
                            "site": StringUtils.get_url_sld(torrent.trackers[0]) if torrent.trackers else "",
                            "size": torrent.size
                        })
            remove_torrents_plus += remove_torrents
            return remove_torrents_plus
        return remove_torrents

    def add_torrent(self, content,
                    is_paused=False,
                    download_dir=None,
                    upload_limit=None,
                    download_limit=None,
                    cookie=None,
                    **kwargs):
        try:
            ret = self.trc.add_torrent(torrent=content,
                                       download_dir=download_dir,
                                       paused=is_paused,
                                       cookies=cookie)
            if ret and ret.hashString:
                if upload_limit:
                    self.set_uploadspeed_limit(ret.hashString, int(upload_limit))
                if download_limit:
                    self.set_downloadspeed_limit(ret.hashString, int(download_limit))
            return ret
        except Exception as err:
            ExceptionUtils.exception_traceback(err)
            return False

    def start_torrents(self, ids):
        if not self.trc:
            return False
        ids = self.__parse_ids(ids)
        try:
            return self.trc.start_torrent(ids=ids)
        except Exception as err:
            ExceptionUtils.exception_traceback(err)
            return False

    def stop_torrents(self, ids):
        if not self.trc:
            return False
        ids = self.__parse_ids(ids)
        try:
            return self.trc.stop_torrent(ids=ids)
        except Exception as err:
            ExceptionUtils.exception_traceback(err)
            return False

    def delete_torrents(self, delete_file, ids):
        if not self.trc:
            return False
        if not ids:
            return False
        ids = self.__parse_ids(ids)
        try:
            return self.trc.remove_torrent(delete_data=delete_file, ids=ids)
        except Exception as err:
            ExceptionUtils.exception_traceback(err)
            return False

    def get_files(self, tid):
        """
        获取种子文件列表
        """
        if not tid:
            return None
        try:
            torrent = self.trc.get_torrent(tid)
        except Exception as err:
            ExceptionUtils.exception_traceback(err)
            return None
        if torrent:
            return torrent.files()
        else:
            return None

    def set_files(self, **kwargs):
        """
        设置下载文件的状态
        {
            <torrent id>: {
                <file id>: {
                    'priority': <priority ('high'|'normal'|'low')>,
                    'selected': <selected for download (True|False)>
                },
                ...
            },
            ...
        }
        """
        if not kwargs.get("file_info"):
            return False
        try:
            self.trc.set_files(kwargs.get("file_info"))
            return True
        except Exception as err:
            ExceptionUtils.exception_traceback(err)
            return False

    def get_download_dirs(self):
        if not self.trc:
            return []
        try:
            return [self.trc.get_session(timeout=30).download_dir]
        except Exception as err:
            ExceptionUtils.exception_traceback(err)
            return []

    def set_uploadspeed_limit(self, ids, limit):
        """
        设置上传限速，单位 KB/sec
        """
        if not self.trc:
            return
        if not ids or not limit:
            return
        ids = self.__parse_ids(ids)
        self.trc.change_torrent(ids, uploadLimit=int(limit))

    def set_downloadspeed_limit(self, ids, limit):
        """
        设置下载限速，单位 KB/sec
        """
        if not self.trc:
            return
        if not ids or not limit:
            return
        ids = self.__parse_ids(ids)
        self.trc.change_torrent(ids, downloadLimit=int(limit))

    def get_downloading_progress(self, tag=None, ids=None):
        """
        获取正在下载的种子进度
        """
        Torrents = self.get_downloading_torrents(tag=tag, ids=ids) or []
        DispTorrents = []
        for torrent in Torrents:
            if torrent.status in [TorrentStatus.Stopped]:
                state = "Stoped"
                speed = "已暂停"
            else:
                state = "Downloading"

                _dlspeed = StringUtils.str_filesize(torrent.download_speed)
                _upspeed = StringUtils.str_filesize(torrent.upload_speed)
                speed = "%s%sB/s %s%sB/s" % (chr(8595), _dlspeed, chr(8593), _upspeed)
            # 进度
            progress = round(torrent.progress) * 100
            DispTorrents.append({
                'id': torrent.id,
                'name': torrent.name,
                'speed': speed,
                'state': state,
                'progress': progress
            })
        return DispTorrents

    def set_speed_limit(self, download_limit=None, upload_limit=None):
        """
        设置速度限制
        :param download_limit: 下载速度限制，单位KB/s
        :param upload_limit: 上传速度限制，单位kB/s
        """
        if not self.trc:
            return
        try:
            session = self.trc.get_session()
            download_limit_enabled = True if download_limit else False
            upload_limit_enabled = True if upload_limit else False
            if download_limit_enabled == session.speed_limit_down_enabled and \
                    upload_limit_enabled == session.speed_limit_up_enabled and \
                    download_limit == session.speed_limit_down and \
                    upload_limit == session.speed_limit_up:
                return
            self.trc.set_session(
                speed_limit_down=download_limit if download_limit != session.speed_limit_down
                else session.speed_limit_down,
                speed_limit_up=upload_limit if upload_limit != session.speed_limit_up
                else session.speed_limit_up,
                speed_limit_down_enabled=download_limit_enabled,
                speed_limit_up_enabled=upload_limit_enabled
            )
        except Exception as err:
            ExceptionUtils.exception_traceback(err)
            return False

    def recheck_torrents(self, ids):
        if not self.trc:
            return False
        ids = self.__parse_ids(ids)
        try:
            return self.trc.verify_torrent(ids=ids)
        except Exception as err:
            ExceptionUtils.exception_traceback(err)
            return False

    def get_free_space(self, path: str):
        if not self.trc:
            return
        if not path:
            log.error(f"【{self.client_name}】{self.name} 未设置保存路径，获取磁盘剩余空间失败")
            return
        try:
            return self.trc.free_space(path)
        except Exception as err:
            ExceptionUtils.exception_traceback(err)
            return

    def torrent_properties(self, torrent):
        # 当前时间戳
        date_now = int(time.time())

        torrent_obj = Torrent()
        torrent_obj.id = torrent.hashString
        torrent_obj.name = torrent.name
        # 做种时间
        if not torrent.done_date or torrent.done_date.timestamp() < 1:
            torrent_obj.seeding_time = 0
        else:
            torrent_obj.seeding_time = date_now - int(torrent.done_date.timestamp())
        # 下载耗时
        if not torrent.added_date or torrent.added_date.timestamp() < 1:
            torrent_obj.download_time = 0
        else:
            torrent_obj.download_time = date_now - int(torrent.added_date.timestamp())
        # 下载量
        torrent_obj.downloaded = int(torrent.total_size * torrent.progress / 100)

        # 分享率
        torrent_obj.ratio = torrent.ratio or 0
        
        # 上传量
        torrent_obj.uploaded = int(torrent_obj.downloaded * torrent.ratio)

        # 平均上传速度
        torrent_obj.avg_upload_speed = torrent.uploaded_ever / torrent.seconds_seeding if torrent.seconds_seeding != 0 else 0
        
        # 未活动时间
        if not torrent.activity_date or torrent.activity_date.timestamp() < 1:
            torrent_obj.iatime = 0
        else:
            torrent_obj.iatime = date_now - int(torrent.activity_date.timestamp())

        # 种子大小
        torrent_obj.size = torrent.total_size

        # 状态
        torrent_obj.status = Transmission._judge_status(torrent.status.name, torrent.error)
        # 标签
        torrent_obj.labels = torrent.labels if hasattr(torrent, "labels") else []
        # tracker
        torrent_obj.trackers = [tracker.announce for tracker in torrent.trackers]
        # 下载速度
        torrent_obj.download_speed = torrent.rate_download
        # 上传速度
        torrent_obj.upload_speed = torrent.rate_upload
        # eta
        torrent_obj.eta = torrent.eta
        # 下载进度
        torrent_obj.progress = torrent.percent_done
        # 保存路径
        torrent_obj.save_path = torrent.download_dir
        
        return torrent_obj

    @staticmethod
    def _judge_status(state, errno):
        if errno != 0:
            return TorrentStatus.Error
        else:
            state_mapping = {
                "STOPPED": TorrentStatus.Stopped,
                "CHECK_PENDING": TorrentStatus.Queued,
                "CHECKING": TorrentStatus.Checking,
                "DOWNLOAD_PENDING": TorrentStatus.Pending,
                "DOWNLOADING": TorrentStatus.Downloading,
                "SEED_PENDING": TorrentStatus.Queued,
                "SEEDING": TorrentStatus.Uploading,
                "UNKNOWN": TorrentStatus.Unknown
            }
            return state_mapping.get(state, TorrentStatus.Unknown)
