import os
import time
import signal
import subprocess
from datetime import datetime, timedelta
from threading import Event

import pytz
from apscheduler.triggers.cron import CronTrigger

from app.plugins.modules._base import _IPluginModule
from app.utils import SystemUtils
from config import Config
from app.scheduler_service import SchedulerService
from app.queue import scheduler_queue


class AutoRestart(_IPluginModule):
    # 插件名称
    module_name = "自动重启"
    # 插件描述
    module_desc = "定时自动重启NAStool服务，保持系统稳定运行。"
    # 插件图标
    module_icon = "refresh.png"
    # 主题色
    module_color = "bg-orange"
    # 插件版本
    module_version = "1.0"
    # 插件作者
    module_author = "linyuan0213"
    # 作者主页
    author_url = "https://github.com/linyuan0213"
    # 插件配置项ID前缀
    module_config_prefix = "autorestart_"
    # 加载顺序
    module_order = 23
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
    _delay = 0
    _notify = False
    _onlyonce = False
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
                            'title': '开启定时重启',
                            'required': "",
                            'tooltip': '开启后会根据周期定时重启NAStool服务',
                            'type': 'switch',
                            'id': 'enabled',
                        },
                        {
                            'title': '重启前延迟（秒）',
                            'required': "",
                            'tooltip': '重启前的倒计时延迟，0表示立即重启',
                            'type': 'text',
                            'content': [
                                {
                                    'id': 'delay',
                                    'placeholder': '0',
                                }
                            ]
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
                            'title': '重启周期',
                            'required': "",
                            'tooltip': '设置自动重启时间周期，支持5位cron表达式',
                            'type': 'text',
                            'content': [
                                {
                                    'id': 'cron',
                                    'placeholder': '0 0 3 ? *',  # 默认每天凌晨3点
                                }
                            ]
                        }
                    ]
                ]
            }
        ]

    def init_config(self, config=None):
        # 读取配置
        if config:
            self._enabled = config.get("enabled")
            self._cron = config.get("cron")
            self._delay = config.get("delay", 0)
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
                self.info("重启服务启动，立即运行一次")
                scheduler_queue.put({
                        "func_str": "AutoRestart.restart",
                        "type": 'plugin',
                        "args": [],
                        "job_id": "AutoRestart.restart_once",
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
                    "delay": self._delay,
                    "notify": self._notify,
                    "onlyonce": self._onlyonce,
                })

            # 周期运行
            if self._cron:
                self.info(f"定时重启服务启动，周期：{self._cron}")
                scheduler_queue.put({
                        "func_str": "AutoRestart.restart",
                        "type": 'plugin',
                        "args": [],
                        "job_id": "AutoRestart.restart_2",
                        "trigger": CronTrigger.from_crontab(self._cron),
                        "jobstore": self._jobstore
                    })

    def restart(self):
        """
        执行重启操作
        """
        self.info(f"当前时间 {time.strftime('%Y-%m-%d %H:%M:%S', time.localtime(time.time()))} 开始重启流程")
        
        # 发送重启通知
        if self._notify:
            self.send_message(
                title="【系统重启通知】",
                text=f"NAStool将在 {self._delay} 秒后重启\n时间：{time.strftime('%Y-%m-%d %H:%M:%S', time.localtime(time.time()))}"
            )
        
        # 如果有延迟，等待
        if self._delay and int(self._delay) > 0:
            self.info(f"等待 {self._delay} 秒后重启...")
            time.sleep(int(self._delay))
        
        try:
            self._soft_restart()
        except Exception as e:
            self.error(f"重启失败：{str(e)}")
            if self._notify:
                self.send_message(
                    title="【系统重启失败】",
                    text=f"NAStool重启失败：{str(e)}\n时间：{time.strftime('%Y-%m-%d %H:%M:%S', time.localtime(time.time()))}"
                )

    def _soft_restart(self):
        """
        重启NAStool应用进程
        """
        self.info("执行重启...")
        
        # 获取当前进程ID
        pid = os.getpid()
        self.info(f"当前进程ID: {pid}")
        
        # 发送SIGTERM信号优雅终止进程
        # 这会让NAStool正常关闭，然后由外部进程管理器（如systemd、docker、supervisor）重新启动
        os.kill(pid, signal.SIGTERM)

    def stop_service(self):
        """
        退出插件
        """
        try:
            if self._scheduler and self._scheduler.SCHEDULER:
                for job in self._scheduler.get_jobs(self._jobstore):
                    if 'restart' in job.name:
                        self._scheduler.remove_job(job.id, self._jobstore)
        except Exception as e:
            print(str(e))

    def get_state(self):
        return self._enabled and self._cron