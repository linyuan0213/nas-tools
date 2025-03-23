import glob
import os
import time
from datetime import datetime, timedelta

import pytz
from apscheduler.triggers.cron import CronTrigger

from threading import Event
from app.plugins.modules._base import _IPluginModule
from app.utils import SystemUtils
from config import Config
from web.action import WebAction

from app.scheduler_service import SchedulerService
from app.queue import scheduler_queue
from app.plugins.modules._autobackup.filestorage_client import FileClientFactory


class AutoBackup(_IPluginModule):
    # 插件名称
    module_name = "自动备份"
    # 插件描述
    module_desc = "自动备份NAStool数据和配置文件。"
    # 插件图标
    module_icon = "backup.png"
    # 主题色
    module_color = "bg-green"
    # 插件版本
    module_version = "2.0"
    # 插件作者
    module_author = "linyuan0213"
    # 作者主页
    author_url = "https://github.com/linyuan0213"
    # 插件配置项ID前缀
    module_config_prefix = "autobackup_"
    # 加载顺序
    module_order = 22
    # 可使用的用户级别
    auth_level = 1

    # 私有属性
    _scheduler = None
    _jobstore = 'plugin'
    _job_id = None

    # 设置开关
    _enabled = False
    # 任务执行间隔
    _cron = None
    _cnt = None
    _full = None
    _bk_path = None
    _onlyonce = False
    _notify = False
    # 退出事件
    _event = Event()

    @staticmethod
    def get_fields():
        return [
            {
                'type': 'div',
                'content': [
                    [
                        {
                            'title': '存储类型',
                            'required': "",
                            'tooltip': "支持本地、WebDAV和Samba",
                            'type': 'select',
                            'content': [
                                {
                                    'id': 'storage_type',
                                    'options': {
                                        'local': '本地',
                                        'webdav': 'WebDAV',
                                        'samba': 'Samba'
                                    },
                                    'default': 'local'
                                }
                            ]
                        },
                        {
                            'title': '开启定时备份',
                            'required': "",
                            'tooltip': '开启后会根据周期定时备份NAStool',
                            'type': 'switch',
                            'id': 'enabled',
                        },
                        {
                            'title': '是否完整版备份',
                            'required': "",
                            'tooltip': '开启后会备份完整数据库，保留有历史记录',
                            'type': 'switch',
                            'id': 'full',
                        },
                        {
                            'title': '运行时通知',
                            'required': "",
                            'tooltip': '运行任务后会发送通知（需要打开插件消息通知）',
                            'type': 'switch',
                            'id': 'notify',
                        },
                        {
                            'title': '立即运行一次',
                            'required': "",
                            'tooltip': '打开后立即运行一次',
                            'type': 'switch',
                            'id': 'onlyonce',
                        },
                    ]
                ]
            },
            {
                'type': 'div',
                'content': [
                    [
                        {
                            'title': '服务器地址',
                            'required': "",
                            'tooltip': 'WebDAV或Samba服务器地址，例如http://192.168.1.100:8080或smb://192.168.1.100:445',
                            'type': 'text',
                            'content': [
                                {
                                    'id': 'base_url',
                                    'placeholder': 'http://192.168.1.100:8080',
                                }
                            ]
                        },
                        {
                            'title': '用户名',
                            'required': "",
                            'tooltip': "WebDAV或Samba用户名",
                            'type': 'text',
                            'content': [
                                {
                                    'id': 'username',
                                    'placeholder': ''
                                }
                            ]
                        },
                        {
                            'title': '密码',
                            'required': "",
                            'tooltip': 'WebDAV或Samba密码',
                            'type': 'password',
                            'content': [
                                {
                                    'id': 'password',
                                    'placeholder': ''
                                }
                            ]
                        },
                        {
                            'title': '共享名称',
                            'required': "",
                            'tooltip': '共享文件夹名称（如 public）',
                            'type': 'text',
                            'content': [
                                {
                                    'id': 'share_name',
                                    'placeholder': 'public'
                                }
                            ]
                        },
                    ]
                ]
            },
            {
                'type': 'div',
                'content': [
                    [
                        {
                            'title': '备份周期',
                            'required': "",
                            'tooltip': '设置自动备份时间周期，支持5位cron表达式',
                            'type': 'text',
                            'content': [
                                {
                                    'id': 'cron',
                                    'placeholder': '0 0 0 ? *',
                                }
                            ]
                        },
                        {
                            'title': '最大保留备份数',
                            'required': "",
                            'tooltip': '最大保留备份数量，优先删除较早备份',
                            'type': 'text',
                            'content': [
                                {
                                    'id': 'cnt',
                                    'placeholder': '10',
                                }
                            ]
                        },
                        {
                            'title': '本地备份路径',
                            'required': "",
                            'tooltip': '本地备份路径（仅当存储类型为本地时有效）',
                            'type': 'text',
                            'content': [
                                {
                                    'id': 'bk_path',
                                    'placeholder': '/config/backup_file',
                                }
                            ]
                        } if not SystemUtils.is_docker() else {},
                        {
                            'title': '远程路径',
                            'required': "",
                            'tooltip': '备份文件在远程存储中的存放路径（相对于共享根目录），示例：填写 /backups 文件将存储在共享根目录的 backups 子文件夹中',
                            'type': 'text',
                            'content': [
                                {
                                    'id': 'remote_path',
                                    'placeholder': '/backups',
                                }
                            ]
                        },
                    ]
                ]
            }
        ]

    def init_config(self, config=None):
        # 读取配置
        if config:
            self._enabled = config.get("enabled")
            self._cron = config.get("cron")
            self._cnt = config.get("cnt")
            self._full = config.get("full")
            self._storage_type = config.get("storage_type", "local")
            self._base_url = config.get("base_url")
            self._username = config.get("username")
            self._password = config.get("password")
            self._share_name = config.get("share_name")
            self._remote_path = config.get("remote_path", "")
            self._bk_path = config.get("bk_path")
            self._notify = config.get("notify")
            self._onlyonce = config.get("onlyonce")

        self._scheduler = SchedulerService()
        self.stop_service()
        self.run_service()

    def run_service(self):
        # 启动服务
        if self._enabled or self._onlyonce:
            # 运行一次
            if self._onlyonce:
                self.info("备份服务启动，立即运行一次")
                scheduler_queue.put({
                        "func_str": "AutoBackup.backup",
                        "type": 'plugin',
                        "args": [],
                        "job_id": "AutoBackup.backup_once",
                        "trigger": "date",
                        "run_date": datetime.now(tz=pytz.timezone(Config().get_timezone())) + timedelta(
                                                                seconds=3),
                        "jobstore": self._jobstore
                    })
                # 关闭一次性开关
                self._onlyonce = False
                self.update_config({
                    "enabled": self._enabled,
                    "cron": self._cron,
                    "cnt": self._cnt,
                    "full": self._full,
                    "storage_type": self._storage_type,
                    "base_url": self._base_url,
                    "username": self._username,
                    "password": self._password,
                    "share_name": self._share_name,
                    "remote_path": self._remote_path,
                    "bk_path": self._bk_path,
                    "notify": self._notify,
                    "onlyonce": self._onlyonce,
                })

            # 周期运行
            if self._cron:
                self.info(f"定时备份服务启动，周期：{self._cron}")
                scheduler_queue.put({
                        "func_str": "AutoBackup.backup",
                        "type": 'plugin',
                        "args": [],
                        "job_id": "AutoBackup.backup_2",
                        "trigger": CronTrigger.from_crontab(self._cron),
                        "jobstore": self._jobstore
                    })

    def backup(self):
        """
        自动备份、删除备份
        """
        self.info(f"当前时间 {time.strftime('%Y-%m-%d %H:%M:%S', time.localtime(time.time()))} 开始备份")

        storage_type = self._storage_type

        # 生成备份文件到本地路径
        if storage_type == 'local':
            # 本地存储路径
            if SystemUtils.is_docker():
                bk_path = os.path.join(Config().get_config_path(), "backup_file")
            else:
                bk_path = self._bk_path or os.path.join(Config().get_config_path(), "backup_file")
        else:
            # 远程存储时使用临时目录
            bk_path = os.path.join(Config().get_temp_path(), "backup_temp")
            os.makedirs(bk_path, exist_ok=True)

        # 生成备份文件
        zip_file = WebAction().backup(bk_path=bk_path, full_backup=self._full)

        if not zip_file:
            self.error("创建备份失败")
            return
        del_count = 0
        bk_count = 0
        # 处理远程存储
        if storage_type in ['webdav', 'samba']:
            try:
                client = None
                if storage_type == 'webdav':
                    client = FileClientFactory.create_client(
                        client_type='webdav',
                        base_url=self._base_url,
                        username=self._username,
                        password=self._password,
                        share_name=self._share_name
                    )
                elif storage_type == 'samba':
                    client = FileClientFactory.create_client(
                        client_type='samba',
                        base_url=self._base_url,
                        username=self._username,
                        password=self._password,
                        share_name=self._share_name
                    )

                if not client:
                    raise Exception("无法创建客户端实例")

                # 上传文件
                remote_dir = self._remote_path.strip('/')
                remote_file = os.path.basename(zip_file)
                remote_path = f"{remote_dir}/{remote_file}" if remote_dir else remote_file

                self.info(f"上传备份文件到远程：{remote_path}")
                client.upload_file(zip_file, remote_path)

                # 删除本地临时文件
                os.remove(zip_file)
                self.info(f"已删除本地临时文件：{zip_file}")

                # 清理旧备份
                if self._cnt:
                    max_keep = int(self._cnt)
                    files = client.list_files(remote_dir)
                    backup_files = [f for f in files if 'bk_' in f and f.endswith('.zip')]
                    bk_count = len(backup_files)
                    sorted_files = sorted(backup_files)
                    if len(sorted_files) > max_keep:
                        del_count = len(sorted_files) - max_keep
                        for file in sorted_files[:del_count]:
                            file_path = file
                            client.delete_file(file_path)
                            self.info(f"已删除远程备份：{file_path}")

            except Exception as e:
                self.error(f"远程备份失败：{str(e)}")
                if os.path.exists(zip_file):
                    os.remove(zip_file)
                return
        else:
            # 本地存储清理旧备份
            if self._cnt:
                files = sorted(glob.glob(os.path.join(bk_path, "bk*")), key=os.path.getctime)
                bk_count = len(files)
                if len(files) > int(self._cnt):
                    del_count = len(files) - int(self._cnt)
                    for i in range(del_count):
                        os.remove(files[i])
                        self.info(f"已删除本地备份：{files[i]}")

        # 发送通知
        if self._notify:
            if self._scheduler and self._scheduler.SCHEDULER:
                for job in self._scheduler.get_jobs(self._jobstore):
                    if 'backup' in job.name:
                        next_run_time = job.next_run_time.strftime('%Y-%m-%d %H:%M:%S')
                        self.send_message(title="【自动备份任务完成】",
                                        text=f"创建备份{'成功' if zip_file else '失败'}\n"
                                            f"清理备份数量 {del_count}\n"
                                            f"剩余备份数量 {bk_count - del_count} \n"
                                            f"下次备份时间: {next_run_time}")

    def stop_service(self):
        """
        退出插件
        """
        try:
            if self._scheduler and self._scheduler.SCHEDULER:
                for job in self._scheduler.get_jobs(self._jobstore):
                    if 'backup' in job.name:
                        self._scheduler.remove_job(job.id, self._jobstore)
        except Exception as e:
            print(str(e))

    def get_state(self):
        return self._enabled and self._cron
