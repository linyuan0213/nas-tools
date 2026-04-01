import os
import re
from typing import List, Optional, Dict, Any

from app.entities.torrent import Torrent
from app.entities.torrentstatus import TorrentStatus
import log
from app.utils import ExceptionUtils, StringUtils
from app.utils.types import DownloaderType
from app.downloader.client._base import _IDownloadClient
from app.downloader.client._pythunder import PyThunder


class Thunder(_IDownloadClient):
    """迅雷下载器客户端"""
    
    schema = "thunder"
    # 下载器ID
    client_id = "thunder"
    client_type = DownloaderType.THUNDER
    client_name = DownloaderType.THUNDER.value
    _client_config = {}
    
    _client = None
    host = None
    port = None
    token = None
    download_dir = []
    
    def __init__(self, config=None):
        if config:
            self._client_config = config
        self.init_config()
        self.connect()
    
    def init_config(self):
        if self._client_config:
            self.host = self._client_config.get("host")
            self.port = self._client_config.get("port")
            self.token = self._client_config.get("token")
            self.download_dir = self._client_config.get('download_dir') or []
            if self.host and self.port:
                self._client = PyThunder(
                    host=self.host,
                    port=self.port,
                    token=self.token
                )
    
    @classmethod
    def match(cls, ctype):
        return True if ctype in [cls.client_id, cls.client_type, cls.client_name] else False
    
    def connect(self):
        pass
    
    def get_status(self):
        if not self._client:
            return False
        try:
            # 尝试获取设备信息来测试连接
            device_id = self._client.get_device_id()
            return True if device_id else False
        except Exception as e:
            log.error(f"【{self.client_name}】连接测试失败: {str(e)}")
            return False
    
    def get_torrents(self, ids=None, status=None, tag=None, **kwargs) -> List[Torrent]:
        if not self._client:
            return []
        
        try:
            if status == "downloading":
                tasks = self._client.get_downloading_tasks()
            elif status == "completed":
                tasks = self._client.get_complete_tasks()
            else:
                # 获取所有任务
                downloading_tasks = self._client.get_downloading_tasks()
                complete_tasks = self._client.get_complete_tasks()
                tasks = downloading_tasks + complete_tasks
            
            torrent_list = []
            for task in tasks:
                torrent = self._task_to_torrent(task)
                if torrent:
                    torrent_list.append(torrent)
            
            return torrent_list
        except Exception as e:
            log.error(f"【{self.client_name}】获取任务列表失败: {str(e)}")
            return []
    
    def get_downloading_torrents(self, ids=None, tag=None, **kwargs):
        return self.get_torrents(status="downloading")
    
    def get_completed_torrents(self, ids=None, tag=None, **kwargs):
        return self.get_torrents(status="completed")
    
    def get_files(self, tid):
        if not self._client:
            return None
        
        try:
            # 迅雷API可能需要先获取任务信息，然后获取文件列表
            # 这里简化处理，返回空列表
            return []
        except Exception as e:
            log.error(f"【{self.client_name}】获取文件列表失败: {str(e)}")
            return None
    
    def set_torrents_status(self, ids, tags=None, **kwargs):
        # 迅雷不支持设置种子状态
        pass
    
    def set_torrents_tag(self, ids, tags, **kwargs):
        # 迅雷不支持标签功能
        return True
    
    def get_transfer_task(self, tag=None, match_path=None, **kwargs):
        if not self._client:
            return []
        
        try:
            completed_tasks = self._client.get_complete_tasks()
            trans_tasks = []
            
            for task in completed_tasks:
                # 转换任务为Torrent对象
                torrent = self._task_to_torrent(task)
                if not torrent:
                    continue
                
                name = torrent.name
                if not name:
                    continue
                
                path = torrent.save_path
                if not path:
                    continue
                
                true_path, replace_flag = self.get_replace_path(path, self.download_dir)
                # 开启目录隔离，未进行目录替换的不处理
                if match_path and not replace_flag:
                    log.debug(f"【{self.client_name}】{name} 开启目录隔离，但未匹配下载目录范围")
                    continue
                
                trans_tasks.append({
                    'path': os.path.join(true_path, name).replace("\\", "/"),
                    'id': torrent.id
                })
            
            return trans_tasks
        except Exception as e:
            log.error(f"【{self.client_name}】获取转移任务失败: {str(e)}")
            return []
    
    def get_remove_torrents(self, config, **kwargs):
        # 迅雷暂不支持自动删种
        return []
    
    def add_torrent(self, content, download_dir=None, **kwargs):
        if not self._client:
            return None
        
        try:
            # content可以是磁力链接或种子文件路径
            if isinstance(content, str):
                if content.startswith('magnet:'):
                    # 磁力链接
                    download_url = content
                elif content.endswith('.torrent') or os.path.exists(content):
                    # 种子文件，需要转换为磁力链接
                    magnet_url = self._client.torrent_to_magnet(content)
                    if not magnet_url:
                        log.error(f"【{self.client_name}】种子文件转换磁力链接失败")
                        return None
                    download_url = magnet_url
                else:
                    # 可能是HTTP链接
                    download_url = content
            else:
                # 二进制种子内容，暂不支持
                log.error(f"【{self.client_name}】不支持二进制种子内容")
                return None
            
            # 调用迅雷下载
            task_info = self._client.download(
                download_urls=download_url,
                destination_path=download_dir or "/downloads/xunlei/"
            )
            
            return task_info.get('id') if task_info else None
        except Exception as e:
            log.error(f"【{self.client_name}】添加下载任务失败: {str(e)}")
            ExceptionUtils.exception_traceback(e)
            return None
    
    def start_torrents(self, ids, **kwargs):
        if not self._client:
            return False
        
        try:
            success = True
            # 如果ids不是列表，转换为列表
            if not isinstance(ids, list):
                ids = [ids]
            for task_id in ids:
                result = self._client.resume_task(task_id)
                if not result:
                    success = False
            return success
        except Exception as e:
            log.error(f"【{self.client_name}】启动任务失败: {str(e)}")
            return False
    
    def stop_torrents(self, ids, **kwargs):
        if not self._client:
            return False
        
        try:
            success = True
            # 如果ids不是列表，转换为列表
            if not isinstance(ids, list):
                ids = [ids]
            for task_id in ids:
                result = self._client.pause_task(task_id)
                if not result:
                    success = False
            return success
        except Exception as e:
            log.error(f"【{self.client_name}】暂停任务失败: {str(e)}")
            return False
    
    def delete_torrents(self, delete_file, ids, **kwargs):
        if not self._client:
            return False
        
        try:
            success = True
            # 如果ids不是列表，转换为列表
            if not isinstance(ids, list):
                ids = [ids]
            for task_id in ids:
                result = self._client.delete_task(task_id, delete_files=delete_file)
                if not result:
                    success = False
            return success
        except Exception as e:
            log.error(f"【{self.client_name}】删除任务失败: {str(e)}")
            return False
    
    def get_download_dirs(self, **kwargs):
        return self.download_dir
    
    def change_torrent(self, **kwargs):
        # 迅雷不支持修改种子
        return True
    
    def get_downloading_progress(self, **kwargs):
        if not self._client:
            return []
        
        try:
            tasks = self._client.get_downloading_tasks()
            progress_list = []
            
            for task in tasks:
                torrent = self._task_to_torrent(task)
                if not torrent:
                    continue
                
                # 进度计算
                try:
                    progress = round(torrent.progress * 100, 2)
                except ZeroDivisionError:
                    progress = 0.0
                
                if torrent.status in [TorrentStatus.Stopped]:
                    state = "Stopped"
                    speed = "已暂停"
                else:
                    state = "Downloading"
                    _dlspeed = StringUtils.str_filesize(torrent.download_speed)
                    _upspeed = StringUtils.str_filesize(torrent.upload_speed)
                    speed = f"{chr(8595)}{_dlspeed}B/s {chr(8593)}{_upspeed}B/s"
                
                progress_list.append({
                    'id': torrent.id,
                    'name': torrent.name,
                    'speed': speed,
                    'state': state,
                    'progress': progress
                })
            
            return progress_list
        except Exception as e:
            log.error(f"【{self.client_name}】获取下载进度失败: {str(e)}")
            return []
    
    def set_speed_limit(self, download_limit=None, upload_limit=None, **kwargs):
        # 迅雷暂不支持速度限制
        return True
    
    def get_type(self):
        return self.client_type
    
    def recheck_torrents(self, ids, **kwargs):
        # 迅雷不支持重新校验
        return True
    
    def get_free_space(self, path: str, **kwargs):
        # 迅雷暂不支持获取剩余空间
        return 0
    
    def _task_to_torrent(self, task: Dict[str, Any]) -> Optional[Torrent]:
        """将迅雷任务转换为Torrent对象"""
        try:
            torrent = Torrent()
            torrent.id = task.get('id', '')
            torrent.name = task.get('name', '')
            
            # 文件大小
            file_size = task.get('file_size', 0)
            if isinstance(file_size, str):
                try:
                    torrent.size = int(file_size)
                except ValueError:
                    torrent.size = 0
            else:
                torrent.size = file_size
            
            # 下载进度
            phase = task.get('phase', '')
            progress = task.get('progress', 0)
            if isinstance(progress, (int, float)):
                torrent.progress = round(progress / 100.0, 2)
            else:
                torrent.progress = 0.0
            
            # 状态映射
            if phase == 'PHASE_TYPE_COMPLETE':
                torrent.status = TorrentStatus.Uploading
                torrent.downloaded = torrent.size
                torrent.progress = round(1.0, 2)
            elif phase in ['PHASE_TYPE_RUNNING', 'PHASE_TYPE_PENDING']:
                torrent.status = TorrentStatus.Downloading
                torrent.downloaded = int(torrent.size * torrent.progress)
            elif phase == 'PHASE_TYPE_PAUSED':
                torrent.status = TorrentStatus.Stopped
            elif phase == 'PHASE_TYPE_ERROR':
                torrent.status = TorrentStatus.Error
            else:
                torrent.status = TorrentStatus.Unknown
            
            # 速度信息 - 从params中提取
            params = task.get('params', {})
            
            # 从params.speed字段获取下载速度（单位：B/s）
            speed_str = params.get('speed', '0')
            try:
                # 速度可能是字符串形式的数字
                download_speed = int(float(speed_str))
                torrent.download_speed = download_speed
            except (ValueError, TypeError):
                torrent.download_speed = 0
            
            # 上传速度通常为0，迅雷API可能不提供
            torrent.upload_speed = 0
            
            # 保存路径
            torrent.save_path = params.get('parent_folder_path', '')
            
            return torrent
        except Exception as e:
            log.error(f"【{self.client_name}】转换任务信息失败: {str(e)}")
            return None