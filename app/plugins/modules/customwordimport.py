import time
from datetime import datetime, timedelta
from urllib.parse import urlsplit
import ruamel.yaml

import pytz
from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger

from threading import Event
from app.plugins.modules._base import _IPluginModule
from app.utils import RequestUtils
from config import Config
from app.utils.types import MediaType
from app.media import Media
from app.helper import WordsHelper



class CustomWordImport(_IPluginModule):
    # 插件名称
    module_name = "自定义识别词导入"
    # 插件描述
    module_desc = "从github导入自定义识别词规则。"
    # 插件图标
    module_icon = "text-recognition.png"
    # 主题色
    module_color = "#a6cce0"
    # 插件版本
    module_version = "1.0"
    # 插件作者
    module_author = "linyuan213"
    # 作者主页
    author_url = "https://github.com/linyuan213"
    # 插件配置项ID前缀
    module_config_prefix = "customwordimport_"
    # 加载顺序
    module_order = 22
    # 可使用的用户级别
    auth_level = 1

    # 私有属性
    _scheduler = None

    # 设置开关
    _enabled = False
    # 任务执行间隔
    _cron = None
    _status = None
    _github_path = None
    _default_path = 'https://github.com/linyuan0213/MediaRecognitionRule'
    _onlyonce = False
    _notify = False
    _file_list = ['common.yaml', 'tv.yaml', 'movie.yaml', 'anime.yaml']
    _github_raw_url = 'https://raw.githubusercontent.com'
    # 退出事件
    _event = Event()

    _media = None
    _wordshelper = None

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
                            'title': '是否启用插件',
                            'required': "",
                            'tooltip': '开启后会根据周期定时导入识别词',
                            'type': 'switch',
                            'id': 'enabled',
                        },
                        {
                            'title': '立即运行一次',
                            'required': "",
                            'tooltip': '打开后立即运行一次',
                            'type': 'switch',
                            'id': 'onlyonce',
                        },
                        {
                            'title': '运行时通知',
                            'required': "",
                            'tooltip': '运行任务后会发送通知（需要打开插件消息通知）',
                            'type': 'switch',
                            'id': 'notify',
                        },
                    ]
                ]
            },
            {
                'type': 'div',
                'content': [
                    # 同一行
                    [
                        {
                            'title': '导入周期',
                            'required': "",
                            'tooltip': '设置自动导入时间周期，支持5位cron表达式',
                            'type': 'text',
                            'content': [
                                {
                                    'id': 'cron',
                                    'placeholder': '0 0 0 ? *',
                                }
                            ]
                        },
                        {
                            'title': 'github 地址',
                            'required': "",
                            'tooltip': 'github 地址（默认地址 https://github.com/linyuan0213/MediaRecognitionRule）',
                            'type': 'text',
                            'content': [
                                {
                                    'id': 'github_path',
                                    'placeholder': 'https://github.com/linyuan0213/MediaRecognitionRule',
                                }
                            ]
                        }
                    ]
                ]
            },
            {
                'type': 'div',
                'content': [
                    # 同一行
                    [
                        {
                            'title': '是否启用识别词',
                            'required': "",
                            'tooltip': '开启后会启用识别词',
                            'type': 'switch',
                            'id': 'status',
                        }
                    ]
                ]
            },

        ]

    def init_config(self, config=None):
        # 读取配置
        if config:
            self._enabled = config.get("enabled")
            self._cron = config.get("cron")
            self._status = config.get("status")
            self._github_path = config.get("github_path")
            self._notify = config.get("notify")
            self._onlyonce = config.get("onlyonce")
            self._media = Media()
            self._wordshelper = WordsHelper()

        # 停止现有任务
        self.stop_service()

        # 启动服务
        if self._enabled or self._onlyonce:
            self._scheduler = BackgroundScheduler(timezone=Config().get_timezone())

            # 运行一次
            if self._onlyonce:
                self.info(f"自定义识别词导入服务启动，立即运行一次")
                self._scheduler.add_job(self.__custom_word_import, 'date',
                                        run_date=datetime.now(tz=pytz.timezone(Config().get_timezone())) + timedelta(
                                            seconds=3))
                # 关闭一次性开关
                self._onlyonce = False
                self.update_config({
                    "enabled": self._enabled,
                    "cron": self._cron,
                    "status": self._status,
                    "github_path": self._github_path,
                    "notify": self._notify,
                    "onlyonce": self._onlyonce,
                })

            # 周期运行
            if self._cron:
                self.info(f"定时导入自定义识别词服务启动，周期：{self._cron}")
                self._scheduler.add_job(self.__custom_word_import,
                                        CronTrigger.from_crontab(self._cron))

            # 启动任务
            if self._scheduler.get_jobs():
                self._scheduler.print_jobs()
                self._scheduler.start()

    def __custom_word_import(self):
        """
        自动导入
        """
        self.info(f"当前时间 {time.strftime('%Y-%m-%d %H:%M:%S', time.localtime(time.time()))} 开始导入自定义识别词")

        ua = Config().get_config('app').get('user_agent')
        github_path = self._github_path or self._default_path

        self.info(f"github url {github_path} ")

        split_url = urlsplit(github_path)
        url_path = split_url.path

        for file_name in self._file_list:
            download_url = f'{self._github_raw_url}{url_path}/master/{file_name}'
            self.info(f'开始下载规则：{download_url}')
            headers = {
                "user-agent": ua,
                "accept-language": "zh-CN,zh;q=0.9,en;q=0.8,ja;q=0.7"
            }
            res = RequestUtils(headers=headers).get_res(download_url)
            if res.status_code != 200:
                return
            yaml = ruamel.yaml.YAML()
            custom_word_dict = yaml.load(res.text)
            if not custom_word_dict:
                continue
            media_type = None
            gtype = None
            group_id = -1
            if 'tv' in file_name:
                media_type = MediaType.TV
                gtype = 2
            if 'movie' in file_name:
                media_type = MediaType.MOVIE
                gtype = 1
            if 'anime' in file_name:
                media_type = MediaType.ANIME
                gtype = 2

            for tmdb_id, rules in custom_word_dict.items():
                self.info(f'开始导入：{tmdb_id}')
                if media_type:
                    tmdb_info = self._media.get_tmdb_info(media_type, tmdb_id)
                    if not tmdb_info:
                        continue
                    if media_type == MediaType.MOVIE:
                        title = tmdb_info.get("title")
                        year = tmdb_info.get("release_date")[0:4]
                        season_count = 0
                    elif media_type == MediaType.ANIME or media_type == MediaType.TV:
                        title = tmdb_info.get("name")
                        year = tmdb_info.get("first_air_date")[0:4]
                        season_count = tmdb_info.get("number_of_seasons")

                    if not self._wordshelper.is_custom_word_group_existed(tmdbid=tmdb_id, gtype=gtype):
                        self.info(f"添加识别词组\n（tmdb_id：{tmdb_id}）")
                        self._wordshelper.insert_custom_word_groups(title=title,
                                            year=year,
                                            gtype=gtype,
                                            tmdbid=tmdb_id,
                                            season_count=season_count)

                    custom_word_groups = self._wordshelper.get_custom_word_groups(tmdbid=tmdb_id, gtype=gtype)
                    if custom_word_groups:
                        group_id = custom_word_groups[0].ID

                for import_word_info in rules:
                    replaced = import_word_info.get("replaced")
                    replace = import_word_info.get("replace")
                    front = import_word_info.get("front")
                    back = import_word_info.get("back")
                    offset = import_word_info.get("offset")
                    whelp = import_word_info.get("help")
                    wtype = int(import_word_info.get("type"))
                    season = import_word_info.get("season")
                    if gtype == 1:
                        season = -2
                    regex = 1
                    # 屏蔽, 替换, 替换+集偏移
                    if wtype in [1, 2, 3]:
                        if self._wordshelper.is_custom_words_existed(replaced=replaced):
                            self.info(f"识别词已存在\n（被替换词：{replaced}）")
                            continue
                    # 集偏移
                    elif wtype == 4:
                        if self._wordshelper.is_custom_words_existed(front=front, back=back):
                            self.info(f"识别词已存在\n（前后定位词：{front}@{back}")
                            continue
                    self._wordshelper.insert_custom_word(replaced=replaced,
                                                    replace=replace,
                                                    front=front,
                                                    back=back,
                                                    offset=offset,
                                                    wtype=wtype,
                                                    gid=group_id,
                                                    season=season,
                                                    enabled=1 if self._status else 0,
                                                    regex=regex,
                                                    whelp=whelp if whelp else "")

        self.info('自定义识别词导入任务完成')
        # 发送通知
        if self._notify:
            next_run_time = self._scheduler.get_jobs()[0].next_run_time.strftime('%Y-%m-%d %H:%M:%S')
            self.send_message(title="【自定义识别词导入任务完成】",
                              text=f"自定义识别词导入{'成功' if True else '失败'}\n"
                                   f"下次导入时间: {next_run_time}")

    def stop_service(self):
        """
        退出插件
        """
        try:
            if self._scheduler:
                self._scheduler.remove_all_jobs()
                if self._scheduler.running:
                    self._event.set()
                    self._scheduler.shutdown()
                    self._event.clear()
                self._scheduler = None
        except Exception as e:
            print(str(e))

    def get_state(self):
        return self._enabled and self._cron
