import os
import re

from app.entities.torrent import Torrent
from app.entities.torrentstatus import TorrentStatus
import log
from app.utils import RequestUtils, ExceptionUtils, StringUtils
from app.utils.types import DownloaderType
from config import Config
from app.downloader.client._base import _IDownloadClient
from app.downloader.client._pyaria2 import PyAria2


class Aria2(_IDownloadClient):

    schema = "aria2"
    # 下载器ID
    client_id = "aria2"
    client_type = DownloaderType.ARIA2
    client_name = DownloaderType.ARIA2.value
    _client_config = {}

    _client = None
    host = None
    port = None
    secret = None
    download_dir = []
    def __init__(self, config=None):
        if config:
            self._client_config = config
        self.init_config()
        self.connect()

    def init_config(self):
        if self._client_config:
            self.host = self._client_config.get("host")
            if self.host:
                if not self.host.startswith('http'):
                    self.host = "http://" + self.host
                if self.host.endswith('/'):
                    self.host = self.host[:-1]
            self.port = self._client_config.get("port")
            self.secret = self._client_config.get("secret")
            self.download_dir = self._client_config.get('download_dir') or []
            if self.host and self.port:
                self._client = PyAria2(secret=self.secret, host=self.host, port=self.port)

    @classmethod
    def match(cls, ctype):
        return True if ctype in [cls.client_id, cls.client_type, cls.client_name] else False

    def connect(self):
        pass

    def get_status(self):
        if not self._client:
            return False
        ver = self._client.getVersion()
        return True if ver else False

    def get_torrents(self, ids=None, status=None, **kwargs) -> list[Torrent]:
        if not self._client:
            return []
        ret_torrents = []
        torrent_list: list[Torrent] = []
        if ids:
            if isinstance(ids, list):
                for gid in ids:
                    ret_torrents.append(self._client.tellStatus(gid=gid))
            else:
                ret_torrents = [self._client.tellStatus(gid=ids)]
        elif status:
            if status == "downloading":
                ret_torrents = self._client.tellActive() or [] + self._client.tellWaiting(offset=-1, num=100) or []
            else:
                ret_torrents = self._client.tellStopped(offset=-1, num=1000)
        for torrent in ret_torrents:
            torrent_list.append(self.torrent_properties(torrent=torrent))
        return torrent_list

    def get_downloading_torrents(self, **kwargs):
        return self.get_torrents(status="downloading")

    def get_completed_torrents(self, **kwargs):
        return self.get_torrents(status="completed")

    def set_torrents_status(self, ids, **kwargs):
        return self.delete_torrents(ids=ids, delete_file=False)

    def get_transfer_task(self, tag=None, match_path=False):
        if not self._client:
            return []
        torrents = self.get_completed_torrents()
        trans_tasks = []
        for torrent in torrents:
            name = torrent.name
            if not name:
                continue
            path = torrent.save_path
            if not path:
                continue
            true_path, replace_flag = self.get_replace_path(path, self.download_dir)
            # 开启目录隔离，未进行目录替换的不处理
            if match_path and not replace_flag:
                log.debug(f"【{self.client_name}】{self.name} 开启目录隔离，但 {torrent.name} 未匹配下载目录范围")
                continue
            trans_tasks.append({'path': os.path.join(true_path, name).replace("\\", "/"), 'id': torrent.id})
        return trans_tasks

    def get_remove_torrents(self, **kwargs):
        return []

    def add_torrent(self, content, download_dir=None, **kwargs):
        if not self._client:
            return None
        if isinstance(content, str):
            # 转换为磁力链
            if re.match("^https*://", content):
                try:
                    p = RequestUtils().get_res(url=content, allow_redirects=False)
                    if p and p.headers.get("Location"):
                        content = p.headers.get("Location")
                except Exception as result:
                    ExceptionUtils.exception_traceback(result)
            return self._client.addUri(uris=[content], options=dict(dir=download_dir))
        else:
            return self._client.addTorrent(torrent=content, uris=[], options=dict(dir=download_dir))

    def start_torrents(self, ids):
        if not self._client:
            return False
        return self._client.unpause(gid=ids)

    def stop_torrents(self, ids):
        if not self._client:
            return False
        return self._client.pause(gid=ids)

    def delete_torrents(self, delete_file, ids):
        if not self._client:
            return False
        return self._client.forceRemove(gid=ids)

    def get_download_dirs(self):
        return []

    def change_torrent(self, **kwargs):
        pass

    def get_downloading_progress(self, **kwargs):
        """
        获取正在下载的种子进度
        """
        Torrents = self.get_downloading_torrents()
        DispTorrents = []
        for torrent in Torrents:
            # 进度
            try:
                progress = torrent.progress * 100
            except ZeroDivisionError:
                progress = 0.0
            if torrent.status in [TorrentStatus.Stopped]:
                state = "Stoped"
                speed = "已暂停"
            else:
                state = "Downloading"
                _dlspeed = StringUtils.str_filesize(torrent.download_speed)
                _upspeed = StringUtils.str_filesize(torrent.upload_speed)
                speed = "%s%sB/s %s%sB/s" % (chr(8595), _dlspeed, chr(8593), _upspeed)

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
        if not self._client:
            return
        download_limit = download_limit * 1024
        upload_limit = upload_limit * 1024
        try:
            speed_opt = self._client.getGlobalOption()
            if speed_opt['max-overall-upload-limit'] != upload_limit:
                speed_opt['max-overall-upload-limit'] = upload_limit
            if speed_opt['max-overall-download-limit'] != download_limit:
                speed_opt['max-overall-download-limit'] = download_limit
            return self._client.changeGlobalOption(speed_opt)
        except Exception as err:
            ExceptionUtils.exception_traceback(err)
            return False

    def get_type(self):
        return self.client_type

    def get_files(self, tid):
        try:
            return self._client.getFiles(gid=tid)
        except Exception as err:
            ExceptionUtils.exception_traceback(err)
            return None

    def recheck_torrents(self, ids):
        pass

    def set_torrents_tag(self, ids, tags):
        pass

    def get_free_space(self, path: str):
        pass

    def torrent_properties(self, torrent):

        torrent_obj = Torrent()
        torrent_obj.id = torrent.get('gid')
        torrent_obj.name = torrent.get('bittorrent', {}).get('info', {}).get("name")
        # 种子大小
        torrent_obj.size = int(torrent.get("totalLength"))
        # 下载量
        torrent_obj.downloaded = int(torrent.get('completedLength'))
        # 状态
        torrent_obj.status = Aria2._judge_status(torrent.get('status'))
        # 下载速度
        torrent_obj.download_speed = torrent.get('downloadSpeed')
        # 上传速度
        torrent_obj.upload_speed = torrent.get('uploadSpeed')
        # 下载进度
        torrent_obj.progress = round(int(torrent.get('completedLength')) / int(torrent.get("totalLength")), 1)
        # 保存路径
        torrent_obj.save_path = torrent.get("dir")
        
        return torrent_obj

    @staticmethod
    def _judge_status(state):
        state_mapping = {
            "paused": TorrentStatus.Stopped,
            "downloading": TorrentStatus.Downloading,
            "completed": TorrentStatus.Uploading,
            "UNKNOWN": TorrentStatus.Unknown
        }
        return state_mapping.get(state, TorrentStatus.Unknown)
