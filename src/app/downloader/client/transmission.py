import time
from typing import Any

import transmission_rpc

import log
from app.core.exceptions import InfrastructureError, NetworkError
from app.downloader.client._base import _IDownloadClient
from app.downloader.schema import ConfigField, DownloaderConfigSchema
from app.downloader.strategy import RemoveStrategy
from app.schemas.download import Torrent, TorrentStatus
from app.utils import ExceptionUtils


class Transmission(_IDownloadClient):
    # 下载器ID
    client_id = "transmission"
    # 下载器类型
    client_type = "transmission"
    # 下载器名称
    client_name = "Transmission"

    config_schema = DownloaderConfigSchema(
        name="Transmission",
        fields=[
            ConfigField(
                id="host",
                required=True,
                title="地址",
                type="text",
                tooltip="配置IP地址或域名，如为https则需要增加https://前缀",
                placeholder="127.0.0.1",
            ),
            ConfigField(
                id="port",
                required=True,
                title="端口",
                type="text",
                placeholder="9091",
            ),
            ConfigField(
                id="username",
                required=True,
                title="用户名",
                type="text",
                placeholder="admin",
            ),
            ConfigField(
                id="password",
                required=False,
                title="密码",
                type="password",
                placeholder="password",
            ),
        ],
    )

    # 参考transmission web，仅查询需要的参数，加速种子搜索
    _trarg = [
        "id",
        "name",
        "status",
        "labels",
        "hashString",
        "totalSize",
        "percentDone",
        "addedDate",
        "trackerStats",
        "leftUntilDone",
        "rateDownload",
        "rateUpload",
        "recheckProgress",
        "rateDownload",
        "rateUpload",
        "peersGettingFromUs",
        "peersSendingToUs",
        "uploadRatio",
        "uploadedEver",
        "downloadedEver",
        "downloadDir",
        "error",
        "errorString",
        "doneDate",
        "queuePosition",
        "activityDate",
        "trackers",
        "secondsSeeding",
        "eta",
    ]

    # 私有属性
    _client_config = {}

    trc = None
    host = None
    port = None
    username = None
    password = None
    download_dir = []
    name = "测试"

    def __init__(self, config: dict):
        self._client_config = config
        self.init_config()
        self.connect()
        # 设置未完成种子添加!part后缀
        if self.trc:
            self.trc.set_session(rename_partial_files=True)

    def init_config(self) -> None:
        if self._client_config:
            self.host = self._client_config.get("host")
            _port = self._client_config.get("port")
            self.port = int(_port) if _port is not None and str(_port).isdigit() else 0
            self.username = self._client_config.get("username")
            self.password = self._client_config.get("password")
            self.download_dir = self._client_config.get("download_dir") or []
            self.name = self._client_config.get("name") or ""

    @classmethod
    def match(cls, ctype: str) -> Any:
        return ctype in [cls.client_id, cls.client_type, cls.client_name]

    def get_type(self) -> Any:
        return self.client_type

    def connect(self) -> Any:
        if self.host and self.port:
            self.trc = self.__login_transmission()

    def __login_transmission(self):
        """
        连接transmission
        :return: transmission对象
        """
        try:
            # 登录
            trt = transmission_rpc.Client(
                host=self.host or "", port=self.port or 0, username=self.username, password=self.password, timeout=60
            )
            return trt
        except (InfrastructureError, NetworkError):
            raise
        except Exception as err:
            ExceptionUtils.exception_traceback(err)
            log.error(f"[{self.client_name}]{self.name} 连接出错：{err!s}")
            return None

    def get_status(self) -> Any:
        return bool(self.trc)

    @staticmethod
    def __parse_ids(ids):
        """
        统一处理种子ID
        """
        if isinstance(ids, list) and any(str(x).isdigit() for x in ids):
            ids = [int(x) for x in ids if str(x).isdigit()]
        elif not isinstance(ids, list) and str(ids).isdigit():
            ids = int(ids)
        return ids

    def get_torrents(
        self, ids: list[str] | str | int | None = None, status: Any = None, tag: str | list[str] | None = None
    ) -> Any:
        """
        获取种子列表
        返回结果 种子列表, 是否有错误
        """
        if not self.trc:
            return [], True
        parsed_ids: Any = self.__parse_ids(ids)
        try:
            torrents = self.trc.get_torrents(ids=parsed_ids, arguments=self._trarg)
            torrent_list: list[Torrent] = []
            for torrent in torrents:
                torrent_list.append(self.torrent_properties(torrent=torrent))
        except (InfrastructureError, NetworkError):
            raise
        except Exception as err:
            ExceptionUtils.exception_traceback(err)
            return [], True
        if status:
            if not isinstance(status, list):
                # 如果是单个TorrentStatus枚举值，直接转为列表
                if isinstance(status, TorrentStatus):
                    status = [status]
                # 如果是字符串，需要转换为TorrentStatus枚举值
                elif isinstance(status, str):
                    status = [self._convert_status_string(status)]
            else:
                # 如果是列表，检查每个元素类型
                converted_status = []
                for s in status:
                    if isinstance(s, TorrentStatus):
                        converted_status.append(s)
                    elif isinstance(s, str):
                        converted_status.append(self._convert_status_string(s))
                    else:
                        converted_status.append(s)
                status = converted_status
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

    def get_completed_torrents(
        self, ids: list[str] | str | int | None = None, tag: str | list[str] | None = None
    ) -> Any:
        """
        获取已完成的种子列表
        return 种子列表, 发生错误时返回None
        """
        if not self.trc:
            return None
        try:
            torrents, error = self.get_torrents(status=[TorrentStatus.Uploading], ids=ids, tag=tag)
            return None if error else torrents or []
        except (InfrastructureError, NetworkError):
            raise
        except Exception as err:
            ExceptionUtils.exception_traceback(err)
            return None

    def get_downloading_torrents(
        self, ids: list[str] | str | int | None = None, tag: str | list[str] | None = None
    ) -> Any:
        """
        获取正在下载的种子列表
        return 种子列表, 发生错误时返回None
        """
        if not self.trc:
            return None
        try:
            torrents, error = self.get_torrents(
                ids=ids, status=[TorrentStatus.Downloading, TorrentStatus.Stopped], tag=tag
            )
            torrents = [t for t in torrents if t.progress * 100 < 100]
            return None if error else torrents or []
        except (InfrastructureError, NetworkError):
            raise
        except Exception as err:
            ExceptionUtils.exception_traceback(err)
            return None

    def set_torrents_status(self, ids: list[str] | str | int | None = None, tags: str | list[str] | None = None) -> Any:
        """
        设置种子为已整理状态
        """
        if not self.trc:
            return
        parsed_ids: Any = self.__parse_ids(ids)
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
            self.trc.change_torrent(labels=tags, ids=parsed_ids)
            log.info(f"[{self.client_name}]{self.name} 设置种子标签成功")
        except (InfrastructureError, NetworkError):
            raise
        except Exception as err:
            ExceptionUtils.exception_traceback(err)

    def set_torrents_tag(self, ids: list[str] | str | int | None = None, tags: str | list[str] | None = None) -> Any:
        """
        设置种子为已整理状态
        """
        if not self.trc:
            return
        parsed_ids: Any = self.__parse_ids(ids)
        # 打标签
        try:
            self.trc.change_torrent(labels=tags, ids=parsed_ids)
            log.info(f"[{self.client_name}]设置transmission种子标签成功")
        except (InfrastructureError, NetworkError):
            raise
        except Exception as err:
            ExceptionUtils.exception_traceback(err)

    def set_torrent_tag(self, tid: str | int | None, tag: str | None) -> None:
        """
        设置种子标签
        """
        if not tid or not tag:
            return
        if not self.trc:
            return
        parsed_ids: Any = self.__parse_ids(tid)
        try:
            self.trc.change_torrent(labels=tag, ids=parsed_ids)
        except (InfrastructureError, NetworkError):
            raise
        except Exception as err:
            ExceptionUtils.exception_traceback(err)

    def change_torrent(self, tid: str | None = None, **kwargs: Any) -> bool:
        """
        设置种子
        :param tid: ID
        :return: bool
        """
        if not tid:
            return False
        parsed_ids: Any = self.__parse_ids(tid)
        tag = kwargs.get("tag")
        upload_limit = kwargs.get("upload_limit")
        download_limit = kwargs.get("download_limit")
        ratio_limit = kwargs.get("ratio_limit")
        seeding_time_limit = kwargs.get("seeding_time_limit")
        if tag:
            if isinstance(tag, list):
                labels = tag
            else:
                labels = [tag]
        else:
            labels = []
        if upload_limit:
            upload_limited = True
            upload_limit_val = int(upload_limit)
        else:
            upload_limited = False
            upload_limit_val = 0
        if download_limit:
            download_limited = True
            download_limit_val = int(download_limit)
        else:
            download_limited = False
            download_limit_val = 0
        if ratio_limit:
            seed_ratio_mode = 1
            seed_ratio_limit = round(float(ratio_limit), 2)
        else:
            seed_ratio_mode = 2
            seed_ratio_limit = 0
        if seeding_time_limit:
            seed_idle_mode = 1
            seed_idle_limit = int(seeding_time_limit)
        else:
            seed_idle_mode = 2
            seed_idle_limit = 0
        if not self.trc:
            return False
        try:
            self.trc.change_torrent(
                ids=parsed_ids,
                labels=labels,
                uploadLimited=upload_limited,
                uploadLimit=upload_limit_val,
                downloadLimited=download_limited,
                downloadLimit=download_limit_val,
                seedRatioMode=seed_ratio_mode,
                seedRatioLimit=seed_ratio_limit,
                seedIdleMode=seed_idle_mode,
                seedIdleLimit=seed_idle_limit,
            )
            return True
        except (InfrastructureError, NetworkError):
            raise
        except Exception as err:
            ExceptionUtils.exception_traceback(err)
            return False

    def _check_extra_remove_conditions(self, torrent: Torrent, strategy: RemoveStrategy) -> bool:
        return True

    def add_torrent(
        self,
        content: str | bytes,
        is_paused: bool = False,
        download_dir: str | None = None,
        upload_limit: int | None = None,
        download_limit: int | None = None,
        cookie: str | None = None,
        **kwargs: Any,
    ) -> Any:
        if not self.trc:
            return False
        try:
            ret = self.trc.add_torrent(torrent=content, download_dir=download_dir, paused=is_paused, cookies=cookie)
            if ret and ret.hashString:
                if upload_limit:
                    self.set_uploadspeed_limit(ret.hashString, int(upload_limit))
                if download_limit:
                    self.set_downloadspeed_limit(ret.hashString, int(download_limit))
            return ret
        except (InfrastructureError, NetworkError):
            raise
        except Exception as err:
            ExceptionUtils.exception_traceback(err)
            return False

    def add_torrent_and_get_id(
        self,
        content: str | bytes,
        is_paused: bool = False,
        download_dir: str | None = None,
        tags: list[str] | None = None,
        category: str | None = None,
        upload_limit: int | None = None,
        download_limit: int | None = None,
        ratio_limit: float | None = None,
        seeding_time_limit: int | None = None,
        cookie: str | None = None,
        **kwargs: Any,
    ) -> str | None:
        ret = self.add_torrent(
            content,
            is_paused=is_paused,
            download_dir=download_dir,
            upload_limit=upload_limit,
            download_limit=download_limit,
            cookie=cookie,
        )
        if ret and ret.hashString:
            if tags:
                self.change_torrent(
                    tid=ret.hashString,
                    tag=tags,
                    ratio_limit=ratio_limit,
                    seeding_time_limit=seeding_time_limit,
                )
            return ret.hashString
        return None

    def start_torrents(self, ids: list[str] | str | int | None = None) -> Any:
        if not self.trc:
            return False
        parsed_ids: Any = self.__parse_ids(ids)
        try:
            return self.trc.start_torrent(ids=parsed_ids)
        except (InfrastructureError, NetworkError):
            raise
        except Exception as err:
            ExceptionUtils.exception_traceback(err)
            return False

    def stop_torrents(self, ids: list[str] | str | int | None = None) -> Any:
        if not self.trc:
            return False
        parsed_ids: Any = self.__parse_ids(ids)
        try:
            return self.trc.stop_torrent(ids=parsed_ids)
        except (InfrastructureError, NetworkError):
            raise
        except Exception as err:
            ExceptionUtils.exception_traceback(err)
            return False

    def delete_torrents(self, delete_file: bool | None = None, ids: list[str] | str | int | None = None) -> Any:
        if not self.trc:
            return False
        if not ids:
            return False
        parsed_ids: Any = self.__parse_ids(ids)
        try:
            return self.trc.remove_torrent(delete_data=bool(delete_file or False), ids=parsed_ids)
        except (InfrastructureError, NetworkError):
            raise
        except Exception as err:
            ExceptionUtils.exception_traceback(err)
            return False

    def get_files(self, tid: int | str | None = None) -> Any:
        """
        获取种子文件列表
        """
        if not tid:
            return None
        if not self.trc:
            return None
        try:
            torrent = self.trc.get_torrent(tid)
        except (InfrastructureError, NetworkError):
            raise
        except Exception as err:
            ExceptionUtils.exception_traceback(err)
            return None
        if torrent:
            return torrent.files()  # type: ignore[attr-defined]
        else:
            return None

    def _normalize_files(self, raw_files: Any) -> list[dict]:
        """将 transmission 文件列表转换为统一格式."""
        return [{"id": idx, "name": getattr(f, "name", "")} for idx, f in enumerate(raw_files)]

    def set_file_selection(self, tid: str | None, selected_map: dict[int, bool]) -> bool:
        """设置种子文件的选择状态."""
        if not tid or not selected_map or not self.trc:
            return False
        files_info = {
            tid: {fid: {"priority": "normal", "selected": selected} for fid, selected in selected_map.items()}
        }
        try:
            self.trc.set_files(files_info)  # type: ignore[attr-defined]
            return True
        except (InfrastructureError, NetworkError):
            raise
        except Exception as err:
            ExceptionUtils.exception_traceback(err)
            return False

    def set_files(self, **kwargs: Any) -> bool:
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
        if not self.trc:
            return False
        try:
            self.trc.set_files(kwargs.get("file_info"))  # type: ignore[attr-defined]
            return True
        except (InfrastructureError, NetworkError):
            raise
        except Exception as err:
            ExceptionUtils.exception_traceback(err)
            return False

    def get_download_dirs(self) -> Any:
        if not self.trc:
            return []
        try:
            return [self.trc.get_session(timeout=30).download_dir]
        except (InfrastructureError, NetworkError):
            raise
        except Exception as err:
            ExceptionUtils.exception_traceback(err)
            return []

    def set_uploadspeed_limit(self, ids: list[str] | str | int, limit: int) -> None:
        """
        设置上传限速，单位 KB/sec
        """
        if not self.trc:
            return
        if not ids or not limit:
            return
        parsed_ids: Any = self.__parse_ids(ids)
        self.trc.change_torrent(parsed_ids, uploadLimit=int(limit))

    def set_downloadspeed_limit(self, ids: list[str] | str | int, limit: int) -> None:
        """
        设置下载限速，单位 KB/sec
        """
        if not self.trc:
            return
        if not ids or not limit:
            return
        parsed_ids: Any = self.__parse_ids(ids)
        self.trc.change_torrent(parsed_ids, downloadLimit=int(limit))

    def set_speed_limit(self, download_limit: int | None = None, upload_limit: int | None = None, **kwargs: Any) -> Any:
        """
        设置速度限制
        :param download_limit: 下载速度限制，单位KB/s
        :param upload_limit: 上传速度限制，单位kB/s
        """
        if not self.trc:
            return
        try:
            session = self.trc.get_session()
            download_limit_enabled = bool(download_limit)
            upload_limit_enabled = bool(upload_limit)
            if (
                download_limit_enabled == session.speed_limit_down_enabled
                and upload_limit_enabled == session.speed_limit_up_enabled
                and download_limit == session.speed_limit_down
                and upload_limit == session.speed_limit_up
            ):
                return
            self.trc.set_session(
                speed_limit_down=download_limit
                if download_limit != session.speed_limit_down
                else session.speed_limit_down,
                speed_limit_up=upload_limit if upload_limit != session.speed_limit_up else session.speed_limit_up,
                speed_limit_down_enabled=download_limit_enabled,
                speed_limit_up_enabled=upload_limit_enabled,
            )
        except (InfrastructureError, NetworkError):
            raise
        except Exception as err:
            ExceptionUtils.exception_traceback(err)
            return False

    def get_transfer_statistics(self) -> dict | None:
        if not self.trc:
            return None
        try:
            session = self.trc.get_session()
            stats = self.trc.session_stats
        except (InfrastructureError, NetworkError):
            raise
        except Exception as err:
            ExceptionUtils.exception_traceback(err)
            return None
        if not session or not stats:
            return None
        return {
            "download_speed": int(getattr(stats, "download_speed", 0) or 0),
            "upload_speed": int(getattr(stats, "upload_speed", 0) or 0),
            "download_limit": int(session.speed_limit_down * 1024) if session.speed_limit_down_enabled else None,
            "upload_limit": int(session.speed_limit_up * 1024) if session.speed_limit_up_enabled else None,
        }

    def recheck_torrents(self, ids: list[str] | str | int | None = None) -> Any:
        if not self.trc:
            return False
        parsed_ids: Any = self.__parse_ids(ids)
        try:
            return self.trc.verify_torrent(ids=parsed_ids)
        except (InfrastructureError, NetworkError):
            raise
        except Exception as err:
            ExceptionUtils.exception_traceback(err)
            return False

    def get_free_space(self, path: str) -> Any:
        if not self.trc:
            return
        if not path:
            log.error(f"[{self.client_name}]{self.name} 未设置保存路径，获取磁盘剩余空间失败")
            return
        try:
            return self.trc.free_space(path)
        except (InfrastructureError, NetworkError):
            raise
        except Exception as err:
            ExceptionUtils.exception_traceback(err)
            return

    def torrent_properties(self, torrent: Any) -> Torrent:
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
        torrent_obj.avg_upload_speed = (
            torrent.uploaded_ever / torrent.seconds_seeding if torrent.seconds_seeding != 0 else 0
        )

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
        # tracker 错误：有一个正常工作即不为错误
        tracker_errors = []
        has_working = False
        tracker_stats = getattr(torrent, "tracker_stats", [])
        for ts in tracker_stats:
            succeeded = getattr(ts, "last_announce_succeeded", False)
            if succeeded:
                has_working = True
            result = getattr(ts, "last_announce_result", "")
            if result and result != "Success":
                tracker_errors.append(result)
        torrent_obj.tracker_error = "" if has_working else "|".join(tracker_errors)
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
    def _convert_status_string(status_str: str) -> TorrentStatus:
        """
        转换通用状态字符串为TorrentStatus枚举值
        """
        status_mapping = {
            "Uploading": TorrentStatus.Uploading,
            "Downloading": TorrentStatus.Downloading,
            "Pending": TorrentStatus.Pending,
            "Checking": TorrentStatus.Checking,
            "Queued": TorrentStatus.Queued,
            "Stopped": TorrentStatus.Stopped,
            "Unknown": TorrentStatus.Unknown,
            "Paused": TorrentStatus.Paused,
            "Error": TorrentStatus.Error,
        }
        # 直接匹配英文状态字符串
        return status_mapping.get(status_str, TorrentStatus.Unknown)

    def _map_status(self, raw_state: Any) -> TorrentStatus:
        if isinstance(raw_state, str):
            return self._judge_status(raw_state, 0)
        return TorrentStatus.Unknown

    @property
    def _supported_statuses(self) -> list[TorrentStatus]:
        return [
            TorrentStatus.Uploading,
            TorrentStatus.Downloading,
            TorrentStatus.Pending,
            TorrentStatus.Checking,
            TorrentStatus.Queued,
            TorrentStatus.Stopped,
            TorrentStatus.Unknown,
            TorrentStatus.Error,
        ]

    @staticmethod
    def _judge_status(state: str, errno: int) -> TorrentStatus:
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
                "UNKNOWN": TorrentStatus.Unknown,
            }
            return state_mapping.get(state, TorrentStatus.Unknown)

    def get_torrent_trackers(self, torrent_hash) -> list[str]:
        if not self.trc:
            return []
        try:
            torrent = self.trc.get_torrent(torrent_id=torrent_hash)
            if not torrent or not torrent.trackers:
                return []
            return [t.announce for t in torrent.trackers if t.announce]
        except (InfrastructureError, NetworkError):
            raise
        except Exception as err:
            ExceptionUtils.exception_traceback(err)
            return []

    def add_torrent_trackers(self, torrent_hash, urls):
        if not self.trc:
            return
        try:
            self.trc.change_torrent(ids=torrent_hash, trackerAdd=urls)
        except (InfrastructureError, NetworkError):
            raise
        except Exception as err:
            ExceptionUtils.exception_traceback(err)

    def remove_torrent_trackers(self, torrent_hash, urls):
        if not self.trc:
            return
        try:
            torrent = self.trc.get_torrent(torrent_id=torrent_hash)
            if not torrent or not torrent.trackers:
                return
            url_set = set(urls) if isinstance(urls, (list, tuple, set)) else {urls}
            tracker_ids = [t.id for t in torrent.trackers if t.announce in url_set]
            if tracker_ids:
                self.trc.change_torrent(ids=torrent_hash, trackerRemove=tracker_ids)
        except (InfrastructureError, NetworkError):
            raise
        except Exception as err:
            ExceptionUtils.exception_traceback(err)

    def edit_torrent_tracker(self, torrent_hash, old_url, new_url):
        if not self.trc:
            return
        try:
            torrent = self.trc.get_torrent(torrent_id=torrent_hash)
            if not torrent or not torrent.trackers:
                return
            for t in torrent.trackers:
                if t.announce == old_url:
                    self.trc.change_torrent(ids=torrent_hash, trackerReplace=[(t.id, new_url)])
        except (InfrastructureError, NetworkError):
            raise
        except Exception as err:
            ExceptionUtils.exception_traceback(err)
