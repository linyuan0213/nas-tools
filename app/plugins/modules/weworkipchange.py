import glob
import os
import random
import time
import re
from datetime import datetime, timedelta
from urllib import response

import pytz
from apscheduler.triggers.cron import CronTrigger

from threading import Event

from requests import Response
from app.helper.cookiecloud_helper import CookiecloudHelper
from app.plugins.modules._base import _IPluginModule
from app.utils.http_utils import RequestUtils
from config import Config

from app.scheduler_service import SchedulerService
from app.queue import scheduler_queue


class WeworkIPChange(_IPluginModule):
    # 插件名称
    module_name = "企业微信可信任IP更新"
    # 插件描述
    module_desc = "定时获取动态IP更新到企业微信可信任IP列表"
    # 插件图标
    module_icon = "wework.jpg"
    # 主题色
    module_color = "#BFBFBF"
    # 插件版本
    module_version = "1.0"
    # 插件作者
    module_author = "linyuan213"
    # 作者主页
    author_url = "https://github.com/linyuan213"
    # 插件配置项ID前缀
    module_config_prefix = "weworkipchange_"
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
    _use_cookiecloud = None
    _cookie = None
    _app_id = None
    _overwrite = True
    _onlyonce = False
    _notify = False
    _ip_url = "https://4.ipw.cn"
    # 退出事件
    _event = Event()

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
                            'title': '启用插件',
                            'required': "",
                            'tooltip': '开启后会根据周期定时获取IP更新到可信任IP列表',
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
                            'title': '是否使用cookiecloud',
                            'required': "",
                            'tooltip': '开启cookiecloud同步，cookiecloud浏览器插件添加同步域名关键词work.weixin.qq.com',
                            'type': 'switch',
                            'id': 'use_cookiecloud',
                        },
                        {
                            'title': '是否使用覆盖当前IP列表',
                            'required': "",
                            'tooltip': '覆盖可信IP列表',
                            'type': 'switch',
                            'id': 'overwrite',
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
                            'title': '同步周期',
                            'required': "",
                            'tooltip': '设置自动同步时间周期，支持5位cron表达式',
                            'type': 'text',
                            'content': [
                                {
                                    'id': 'cron',
                                    'placeholder': '0 0 0 ? *',
                                }
                            ]
                        },
                        {
                            'title': '企业微信APP ID',
                            'required': "required",
                            'tooltip': '企业微信APP ID（点击应用在URL获取modApiApp/后面的数字）',
                            'type': 'text',
                            'content': [
                                {
                                    'id': 'app_id',
                                    'placeholder': '5624501929615254',
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
                            'title': 'cookie',
                            'required': False,
                            'tooltip': '企业微信cookie(可选)',
                            'type': 'textarea',
                            'readonly': False,
                            'content':
                                {
                                    'id': 'cookie',
                                    'placeholder': '',
                                    'rows': 2,
                                }
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
            self._use_cookiecloud = config.get("use_cookiecloud")
            self._cookie = config.get("cookie")
            self._app_id = config.get("app_id")
            self._overwrite = config.get("overwrite")
            self._notify = config.get("notify")
            self._onlyonce = config.get("onlyonce")

        self._scheduler = SchedulerService()
        # 停止现有任务
        self.stop_service()
        self.run_service()

    def run_service(self):
        # 启动服务
        if self._enabled or self._onlyonce:
            # 运行一次
            if self._onlyonce:
                self.info("企业微信可信IP更新服务启动，立即运行一次")
                scheduler_queue.put({
                        "func_str": "WeworkIPChange.change_ip",
                        "type": 'plugin',
                        "args": [],
                        "job_id": "WeworkIPChange.change_ip_once",
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
                    "use_cookiecloud": self._use_cookiecloud,
                    "cookie": self._cookie,
                    "app_id": self._app_id,
                    "overwrite": self._overwrite,
                    "notify": self._notify,
                    "onlyonce": self._onlyonce,
                })

            # 周期运行
            if self._cron:
                self.info(f"企业微信可信IP更新服务启动，周期：{self._cron}")
                scheduler_queue.put({
                        "func_str": "WeworkIPChange.change_ip",
                        "type": 'plugin',
                        "args": [],
                        "job_id": "WeworkIPChange.change_ip_2",
                        "trigger": CronTrigger.from_crontab(self._cron),
                        "jobstore": self._jobstore
                    })

    def change_ip(self):
        """
        自动更新ip
        """
        self.info(f"当前时间 {time.strftime('%Y-%m-%d %H:%M:%S', time.localtime(time.time()))} 开始更新IP")

        cookie = self._cookie
        if self._use_cookiecloud:
            cookie = CookiecloudHelper().get_cookie('qq.com')
            
        

        # 获取动态ip
        dynamic_ip = self.get_current_dynamic_ip()

        iplist = []
        # 获取可信ip
        if not self._overwrite:
            iplist = self.get_current_iplist(cookie=cookie)
            if not iplist:
                iplist = []
        iplist.append(dynamic_ip)
        update_status = self.set_iplist(cookie=cookie, iplist=iplist)
        if update_status:
            self.info(f"更新可信IP成功，当前IP: {dynamic_ip}") 
        else:
            self.error("更新可信IP失败，请更新cookie")
        # 发送通知
        if self._notify:
            if self._scheduler and self._scheduler.SCHEDULER:
                for job in self._scheduler.get_jobs(self._jobstore):
                    if 'change_ip' in job.name:
                        next_run_time = job.next_run_time.strftime('%Y-%m-%d %H:%M:%S')
                        self.send_message(title="【自动更新企业微信可信IP任务完成】",
                                        text=f"当前IP{dynamic_ip}\n" if update_status else "更新可信IP失败，请更新cookie"
                                            f"下次更新时间: {next_run_time}")

    def get_current_dynamic_ip(self):
        respone: Response = RequestUtils().get_res(url=self._ip_url)
        if respone.status_code == 200:
            pattern = r'^((25[0-5]|2[0-4][0-9]|[01]?[0-9][0-9]?)\.){3}(25[0-5]|2[0-4][0-9]|[01]?[0-9][0-9]?)$'
            ip_str = respone.text
            if re.match(pattern, ip_str):
                self.debug(f"动态公网IP: {ip_str}")
                return ip_str

    def get_current_iplist(self, cookie: str):
        headers = {
            "accept": "application/json, text/javascript, */*; q=0.01",
            "accept-language": "zh-CN,zh;q=0.9,en;q=0.8,ja;q=0.7",
            "content-type": "application/x-www-form-urlencoded",
            "referer": "https://work.weixin.qq.com/wework_admin/frame",
            "cookie": cookie,
            "user-agent": Config().get_ua(),
            "x-requested-with": "XMLHttpRequest"
        }
        url = "https://work.weixin.qq.com/wework_admin/apps/getOpenApiApp"
        params = params = {
            "lang": "zh_CN",
            "f": "json",
            "ajax": "1",
            "timeZoneInfo%5Bzone_offset%5D": "-8",
            "random": str(random.random()),
            "app_id": self._app_id,
            "bind_mini_program": "false"
        }
        response: Response = RequestUtils(headers=headers).get_res(url=url, params=params)
        if response.status_code == 200:
            app_json = response.json()

            try:
                ip_list = app_json.get('data').get('white_ip_list').get('ip')
            except Exception:
                if app_json.get('result').get('errCode'):
                    self.info('cookie失效请重新同步cookie')
                return None
            self.debug(f"当前可信IP: {ip_list}")
            if ip_list:
                return ip_list

    def set_iplist(self, cookie: str, iplist: list):
        headers = {
            'accept': 'application/json, text/javascript, */*; q=0.01',
            'content-type': 'application/x-www-form-urlencoded',
            'cookie': cookie,
            'origin': 'https://work.weixin.qq.com',
            'referer': 'https://work.weixin.qq.com/wework_admin/frame',
            'user-agent': Config().get_ua(),
            'x-requested-with': 'XMLHttpRequest',
        }
        params = {
            'lang': 'zh_CN',
            'f': 'json',
            'ajax': '1',
            'timeZoneInfo[zone_offset]': '-8',
            'random': str(random.random()),
        }
        ip_str = "&".join([f"ipList[]={ip}" for ip in iplist])
        data = f'app_id={self._app_id}&{ip_str}'
        url = "https://work.weixin.qq.com/wework_admin/apps/saveIpConfig"

        response: Response = RequestUtils(headers=headers).post_res(url=url, params=params, data=data)
        if response.status_code == 200:
            json_data = response.json()
            if json_data.get('result').get('errCode'):
                self.debug('cookie失效请重新同步cookie')
                return False
            try:
                if json_data.get('data'):
                    self.debug("更新可信IP成功")
                    return True
            except Exception:
                if json_data.get('result').get('errCode'):
                    self.debug('cookie失效请重新同步cookie')
                    return False
        return False

    def stop_service(self):
        """
        退出插件
        """
        try:
            if self._scheduler and self._scheduler.SCHEDULER:
                for job in self._scheduler.get_jobs(self._jobstore):
                    if 'change_ip' in job.name:
                        self._scheduler.remove_job(job.id, self._jobstore)
        except Exception as e:
            print(str(e))

    def get_state(self):
        return self._enabled and self._cron
