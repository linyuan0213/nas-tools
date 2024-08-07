import time
import json
from datetime import datetime, timedelta
from typing import Dict, List

import pytz
from apscheduler.triggers.cron import CronTrigger

from threading import Event
from app.downloader.downloader import Downloader
from app.plugins.modules._base import _IPluginModule
from app.utils import StringUtils, RedisStore
from app.sites import Sites
from app.utils.http_utils import RequestUtils
from config import Config


from app.scheduler_service import SchedulerService
from app.queue import scheduler_queue


class MTBigPack(_IPluginModule):
    # 插件名称
    module_name = "馒头大包推送"
    # 插件描述
    module_desc = "自动推送大包消息并生成RSS"
    # 插件图标
    module_icon = "mtbigpack.png"
    # 主题色
    module_color = "bg-white"
    # 插件版本
    module_version = "1.0"
    # 插件作者
    module_author = "linyuan213"
    # 作者主页
    author_url = "https://github.com/linyuan213"
    # 插件配置项ID前缀
    module_config_prefix = "mtbigpack_"
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
    _site_info = None
    _redis_store = None

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
                            'title': '开启推送',
                            'required': "",
                            'tooltip': '开启后有新的大包更新后会定时推送',
                            'type': 'switch',
                            'id': 'enabled',
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
                    # 同一行
                    [
                        {
                            'title': '更新周期',
                            'required': "",
                            'tooltip': '设置自动更新时间周期，支持5位cron表达式',
                            'type': 'text',
                            'content': [
                                {
                                    'id': 'cron',
                                    'placeholder': '0 0 0 ? *',
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
            self._cnt = config.get("cnt")
            self._notify = config.get("notify")
            self._onlyonce = config.get("onlyonce")

        for site in Sites().get_sites():
            if 'm-team' in site.get("strict_url"):
                self._site_info = site
                break
        self._redis_store = RedisStore()
        self._scheduler = SchedulerService()
        # 停止现有任务
        self.stop_service()
        self.run_service()

    def run_service(self):
        # 启动服务
        if self._enabled or self._onlyonce:
            # 运行一次
            if self._onlyonce:
                self.info("馒头大包推送服务启动，立即运行一次")
                scheduler_queue.put({
                    "func_str": "MTBigPack.auto_push",
                    "type": 'plugin',
                    "args": [],
                    "job_id": "MTBigPack.auto_push_once",
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
                    "bk_path": self._bk_path,
                    "notify": self._notify,
                    "onlyonce": self._onlyonce,
                })

            # 周期运行
            if self._cron:
                self.info(f"馒头大包推送定时服务启动，周期：{self._cron}")
                scheduler_queue.put({
                    "func_str": "MTBigPack.auto_push",
                    "type": 'plugin',
                    "args": [],
                    "job_id": "MTBigPack.auto_push_2",
                    "trigger": CronTrigger.from_crontab(self._cron),
                    "jobstore": self._jobstore
                })

    def auto_push(self):
        """
        自动推送
        """
        self.info(
            f"当前时间 {time.strftime('%Y-%m-%d %H:%M:%S', time.localtime(time.time()))} 开始馒头大包更新")

        if not self._site_info:
            self.error("请添加馒头站点")
            return
        base_url = self._site_info.get('strict_url')

        search_url = f"{base_url}/api/torrent/search"
        collection_url = f"{base_url}/api/torrent/collection"
        rss_url = f"{base_url}/api/rss/genlink"
        rss_download_url = (self._redis_store.hget('bigpack:rss', 'rss') or b'').decode('utf-8')
        if not rss_download_url:
            rss_download_url = self._get_rss(rss_url)
            self._redis_store.hset('bigpack:rss', 'rss', rss_download_url)

        # 获取置顶大包
        data = {
            "mode": "adult",
            "categories": [],
            "visible": 1,
            "pageNumber": 1,
            "pageSize": 100
        }
        torrent_list = self._get_package(
            url=search_url, param=data, topping_level=1)

        torrent_list = [torrent for torrent in torrent_list if torrent.get('status').get('discount') == 'FREE']
        # 检查收藏
        data = {
            "mode": "adult",
            "categories": [],
            "onlyFav": 1,
            "visible": 1,
            "pageNumber": 1,
            "pageSize": 100
        }
        collect_list = self._get_package(
            url=search_url, param=data, topping_level=2)
        collect_dict = {torrent.get("id"): torrent for torrent in collect_list}

        increment_list = []
        for torrent in torrent_list:
            id = torrent.get("id")
            if collect_dict.get(id):
                continue
            if not self._redis_store.hget('bigpack', id):
                increment_list.append(torrent)
                time.sleep(1)
                self._set_collection(url=collection_url,
                                     torrent_id=id, make='true')
                self._redis_store.hset('bigpack', id, 1)
                self.info(f"添加馒头大包成功 种子id: {id}")

        remove_list = self._get_package(
            url=search_url, param=data, topping_level=0)
        for torrent in remove_list:
            id = torrent.get("id")
            time.sleep(1)
            self._set_collection(url=collection_url,
                                 torrent_id=id, make='false')
            self._redis_store.hdel('bigpack', id)
            self.info(f"馒头大包收藏移除成功 种子id: {id}")

        # 发送通知
        message_list = []
        for torrent in increment_list:
            detail_url = f"{base_url}/detail/{torrent.get('id')}"
            download_url = Downloader().get_download_url(detail_url)
            time.sleep(1)
            message_list.append(f"标题：{torrent.get('name')}\n"
                                f"大小：{StringUtils.str_filesize(torrent.get('size'))}\n"
                                f"做种人数：{torrent.get('status').get('seeders')}\n"
                                f"下载人数：{torrent.get('status').get('leechers')}\n"
                                f"到期时间：{torrent.get('status').get('toppingEndTime')}\n"
                                f"下载链接：{download_url}\n"
                                "\n————————————")
        if self._notify and message_list:
            self.send_message(title="【馒头大包推送任务完成】",
                              text="\n".join(message_list) + "\n" + f'RSS订阅链接：{rss_download_url}')

    def stop_service(self):
        """
        退出插件
        """
        try:
            self._redis_store.hdel('bigpack:rss', 'rss')

            if self._scheduler and self._scheduler.SCHEDULER:
                for job in self._scheduler.get_jobs(self._jobstore):
                    if 'auto_push' in job.name:
                        self._scheduler.remove_job(job.id, self._jobstore)
        except Exception as e:
            print(str(e))

    def get_state(self):
        return self._enabled and self._cron

    def _get_package(self, url: str, param: Dict, topping_level: int) -> List:
        """
        获取种子内容
        :param url: 种子列表url
        :param param: 搜索参数
        :param topping_level: 置顶参数 1置顶 0 普通 2 所有种子
        :return: 种子列表
        """
        if not url or not param:
            return

        data = json.dumps(param, separators=(',', ':'))
        headers = self._site_info.get('headers')
        headers = json.loads(headers)
        if headers.get("authorization"):
            headers.pop('authorization')
        headers.update({
            "Content-Type": "application/json; charset=utf-8",
            "User-Agent": f"{self._site_info.get('ua')}"
        })
        proxy = self._site_info.get('proxy')
        response = RequestUtils(headers=headers,
                                proxies=Config().get_proxies() if proxy else None).post_res(url=url, data=data)
        res = response.json()

        # 获取大包
        torrent_list = []
        if res.get('message') == 'SUCCESS':
            for torrent in res.get('data').get('data'):
                topping = torrent.get('status').get('toppingLevel')
                if int(topping) == topping_level:
                    torrent_list.append(torrent)
                if topping_level == 2:
                    torrent_list.append(torrent)

        return torrent_list

    def _set_collection(self, url: str, torrent_id: str, make: str = 'true') -> None:
        """
        添加或移除收藏
        :param url 收藏url
        :param torrent_id 种子id
        :param make true 添加收藏 false 移除收藏
        return True 成功 False 失败
        """
        data = {"id": torrent_id, "make": f"{make}"}
        headers = self._site_info.get('headers')
        headers = json.loads(headers)
        if headers.get("authorization"):
            headers.pop('authorization')
        headers.update({
            "Content-Type": "application/json; charset=utf-8",
            "User-Agent": f"{self._site_info.get('ua')}"
        })
        proxy = self._site_info.get('proxy')
        response = RequestUtils(headers=headers,
                                proxies=Config().get_proxies() if proxy else None).post_res(url=url, params=data)

        res = response.json()

        if res.get('message') == 'SUCCESS':
            return True
        return False

    def _get_rss(self, url):
        headers = self._site_info.get('headers')
        headers = json.loads(headers)
        if headers.get("authorization"):
            headers.pop('authorization')
        headers.update({
            "Content-Type": "application/json; charset=utf-8",
            "User-Agent": f"{self._site_info.get('ua')}"
        })
        proxy = self._site_info.get('proxy')
        data = {
            "categories": [
                "410",
                "424",
                "437",
                "431",
                "429",
                "430",
                "426",
                "432",
                "436",
                "440",
                "425",
                "433",
                "411",
                "412",
                "413"
            ],
            "labels": 0,
            "onlyFav": "true",
            "tkeys": [
                "ttitle"
            ],
            "pageSize": 15
        }
        data = json.dumps(data, separators=(',', ':'))
        response = RequestUtils(headers=headers,
                                proxies=Config().get_proxies() if proxy else None).post_res(url=url, data=data)
        res = response.json()
        if res.get('message') == 'SUCCESS':
            return res.get('data').get('dlUrl')
