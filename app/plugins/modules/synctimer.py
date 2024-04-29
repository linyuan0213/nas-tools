from apscheduler.triggers.cron import CronTrigger

from app.plugins.modules._base import _IPluginModule
from app.sync import Sync

from app.scheduler_service import SchedulerService
from app.queue import scheduler_queue


class SyncTimer(_IPluginModule):
    # 插件名称
    module_name = "定时目录同步"
    # 插件描述
    module_desc = "定时对同步目录进行整理。"
    # 插件图标
    module_icon = "synctimer.png"
    # 主题色
    module_color = "#53BA48"
    # 插件版本
    module_version = "1.0"
    # 插件作者
    module_author = "jxxghp"
    # 作者主页
    author_url = "https://github.com/jxxghp"
    # 插件配置项ID前缀
    module_config_prefix = "synctimer_"
    # 加载顺序
    module_order = 5
    # 可使用的用户级别
    user_level = 1

    # 私有属性
    _sync = None
    _scheduler = None
    _jobstore = "plugin"
    # 限速开关
    _cron = None

    @staticmethod
    def get_fields():
        return [
            # 同一板块
            {
                'type': 'div',
                'content': [
                    # 同一行
                    [
                        {
                            'title': '同步周期',
                            'required': "required",
                            'tooltip': '支持5位cron表达式；仅适用于挂载网盘或网络共享等目录同步监控无法正常工作的场景下使用，正常挂载本地目录无法同步的，应优先查看日志解决问题，留空则不启动',
                            'type': 'text',
                            'content': [
                                {
                                    'id': 'cron',
                                    'placeholder': '0 0 */2 * *',
                                }
                            ]
                        }
                    ]
                ]
            }
        ]

    def init_config(self, config=None):
        self._sync = Sync()

        # 读取配置
        if config:
            self._cron = config.get("cron")

        self._scheduler = SchedulerService()
        # 停止现有任务
        self.stop_service()
        self.run_service()

    def run_service(self):
        # 启动定时任务
        if self._cron:
            scheduler_queue.put({
                        "func_str": "SyncTimer.timersync",
                        "type": 'plugin',
                        "args": [],
                        "job_id": "SyncTimer.timersync",
                        "trigger": CronTrigger.from_crontab(self._cron),
                        "jobstore": self._jobstore
                    })
            self.info(f"目录定时同步服务启动，周期：{self._cron}")

    def get_state(self):
        return True if self._cron else False

    def timersync(self):
        """
        开始同步
        """
        self.info("开始定时同步 ...")
        self._sync.transfer_sync()
        self.info("定时同步完成")

    def stop_service(self):
        """
        退出插件
        """
        try:
            if self._scheduler and self._scheduler.SCHEDULER:
                for job in self._scheduler.get_jobs(self._jobstore):
                    if 'timersync' in job.name:
                        self._scheduler.remove_job(job.id, self._jobstore)
        except Exception as e:
            print(str(e))
