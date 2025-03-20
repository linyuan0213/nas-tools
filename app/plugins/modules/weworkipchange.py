from concurrent.futures import ThreadPoolExecutor
import random
import time
import re
from datetime import datetime, timedelta
import concurrent
from pyquery import PyQuery

import pytz
from apscheduler.triggers.cron import CronTrigger

from threading import Event

from requests import Response
from app.helper.cookiecloud_helper import CookiecloudHelper
from app.helper.drissionpage_helper import DrissionPageHelper
from app.plugins.event_manager import EventHandler
from app.plugins.modules._base import _IPluginModule
from app.utils.http_utils import RequestUtils
from app.utils.redis_store import RedisStore
from app.utils.types import EventType
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
    module_version = "1.1"
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
    _app_ids = None
    _overwrite = True
    _onlyonce = False
    _notify = False
    _tab_id = ""
    _drissonpage_helper = ""
    # redis 保存tab_id
    _redis_store = None
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
                            'title': '是否使用chrome仿真',
                            'required': "",
                            'tooltip': '开启chrome仿真，使用chrome组件模拟登录保活',
                            'type': 'switch',
                            'id': 'use_chrome',
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
                            'tooltip': '企业微信APP ID（点击应用在URL获取modApiApp/后面的数字）,支持多个id，按逗号分隔',
                            'type': 'text',
                            'content': [
                                {
                                    'id': 'app_ids',
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

    @staticmethod
    def get_command():
        """
        定义远程控制命令
        :return: 命令关键字、事件、描述、附带数据
        """
        return {
            "cmd": "/wxl",
            "event": EventType.WeworkLogin,
            "desc": "微信验证码登录",
            "data": {}
        }

    def init_config(self, config=None):
        # 读取配置
        if config:
            self._enabled = config.get("enabled")
            self._cron = config.get("cron")
            self._use_cookiecloud = config.get("use_cookiecloud")
            self._cookie = config.get("cookie")
            self._use_chrome = config.get("use_chrome")
            self._app_ids = config.get("app_ids")
            self._overwrite = config.get("overwrite")
            self._notify = config.get("notify")
            self._onlyonce = config.get("onlyonce")

        self._scheduler = SchedulerService()
        self._drissonpage_helper = DrissionPageHelper()
        self._redis_store = RedisStore()
        tab_id = (self._redis_store.get("tab_id") or b'').decode('utf-8')
        if not self._drissonpage_helper.get_page_html_without_closetab(tab_id=self._tab_id):
            self._tab_id = self._drissonpage_helper.create_tab('https://work.weixin.qq.com/wework_admin/frame', self._cookie)
            self._redis_store.set("tab_id", self._tab_id)
        else:
          self._tab_id = tab_id
        
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
                    "use_chrome": self._use_chrome,
                    "cookie": self._cookie,
                    "app_ids": self._app_ids,
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

    @EventHandler.register(EventType.WeworkLogin)
    def login_by_code(self, event=None) -> bool:
        item = event.event_data
        if item:
            self.debug(f"验证码: {item.get('msg')}")
            if self._drissonpage_helper.input_on_element(tab_id=self._tab_id, selector="tag:div@class=number_panel", input_str=item.get("msg")):
                self.debug(f"验证码输入成功")
                return True
        return False
    
    def get_cookie_by_chrome(self) -> bool:
        login_status = False
        html_text = self._drissonpage_helper.get_page_html_without_closetab(tab_id=self._tab_id, is_refresh=True)
        if html_text and "退出" in html_text:
            login_status = True
            self.info("登录成功")
        else:
            #获取并发送二维码
            html_text = self._drissonpage_helper.get_page_html_without_closetab(tab_id=self._tab_id, is_refresh=False, tab_category="iframe")
            if html_text:
                html_doc = PyQuery(html_text)
                img_url = html_doc('img.qrcode_login_img.js_qrcode_img').attr('src')
                self.debug(f"获取二维码成功，当前二维码url: {img_url}")
                if img_url:
                    img_url = f"https://work.weixin.qq.com{img_url}"
                    self.info("登录已过期，重新登录")
                    # 发送二维码到消息通知
                    self.send_message(title="【企业微信登录过期】",
                    text="请点击扫码重新登录",
                    url=img_url,
                    image=img_url)

        if not login_status:
            start = time.time()
            self.info("等待扫码结果...")
            # 等待扫码结果
            while time.time() - start < 60:
                time.sleep(5)
                html_text = self._drissonpage_helper.get_page_html_without_closetab(tab_id=self._tab_id)
                if html_text and ("短信安全验证" in html_text or "SMS" in html_text):
                    self.info("等待输入验证码...")
                    self.send_message(title="【企业微信登录验证码】",
                    text="请输入 /wxl+验证码 认证"
                    )

                if html_text and ("退出" in html_text or "Quit" in html_text):
                    login_status = True
                    break
            if login_status:
                self.info("登录成功")
            else:
                self.info("登录失败，请重新登录...")
                return False
        self._cookie = self._drissonpage_helper.get_cookie(self._tab_id)
        self.debug(f"获取cookie成功，当前cookie: {self._cookie}")
        return True

    def change_ip(self):
        """
        自动更新ip
        """
        self.info(f"当前时间 {time.strftime('%Y-%m-%d %H:%M:%S', time.localtime(time.time()))} 开始更新IP")
        ip_exist = False
        cookie = self._cookie
        if self._use_cookiecloud:
            # 发送刷新Cookie事件
            EventHandler.send_event(EventType.CookieSync)
            time.sleep(10)
            cookie = CookiecloudHelper().get_cookie('qq.com')
        
        # 使用chrome模拟登录
        if self._use_chrome:
            login_status = self.get_cookie_by_chrome()
            if not login_status:
                return
        cookie = self._cookie
        # 获取动态ip
        dynamic_ip = self.get_current_dynamic_ip()

        # 待完善，需要用线程池
        app_ids = [app_id for app_id in self._app_ids.split(',') if app_id]
        # 使用线程池并发处理
        all_msg = []
        with ThreadPoolExecutor(max_workers=min(4, len(app_ids))) as executor:
            futures = [
                executor.submit(
                    self.process_single_app,
                    app_id,
                    cookie,
                    dynamic_ip
                ) for app_id in app_ids
            ]
            
            for future in concurrent.futures.as_completed(futures):
                all_msg.append(future.result())

        # 汇总所有结果信息
        final_msg = "".join(all_msg)
        self.info(final_msg)  # 或根据需求处理最终消息
        # 发送通知
        if self._notify:
            if self._scheduler and self._scheduler.SCHEDULER:
                for job in self._scheduler.get_jobs(self._jobstore):
                    if 'change_ip' in job.name:
                        next_run_time = job.next_run_time.strftime('%Y-%m-%d %H:%M:%S')
                        self.send_message(title="【自动更新企业微信可信IP任务完成】",
                                        text=final_msg + ""
                                            f"下次更新时间: {next_run_time}")

    def process_single_app(self, app_id, cookie, dynamic_ip):
        """处理单个app_id的可信IP更新"""
        ip_exist = False
        msg = ""
        
        try:
            # 获取可信ip
            ips = self.get_current_iplist(cookie=cookie, app_id=app_id)
            if dynamic_ip in ips:
                ip_exist = True

            iplist = []
            if not self._overwrite:
                iplist = ips.copy() if ips else []
            iplist.append(dynamic_ip)

            update_status = False
            if not ip_exist:
                update_status = self.set_iplist(
                    cookie=cookie, 
                    iplist=iplist, 
                    app_id=app_id
                )
                if update_status:
                    self.info(f"AppID[{app_id}] 更新可信IP成功，当前IP: {dynamic_ip}")
                else:
                    self.error(f"AppID[{app_id}] 更新可信IP失败，请检查cookie")

            if ip_exist:
                msg = f"AppID[{app_id}] IP {dynamic_ip} 已存在\n"
            else:
                msg = (
                    f"AppID[{app_id}] 更新可信IP成功，当前IP: {dynamic_ip}\n"
                    if update_status
                    else f"AppID[{app_id}] 更新可信IP失败，请检查cookie\n"
                )
        except Exception as e:
            msg = f"AppID[{app_id}] 处理异常: {str(e)}\n"
            self.error(msg)
        return msg

    def get_current_dynamic_ip(self):
        respone: Response = RequestUtils().get_res(url=self._ip_url)
        if respone.status_code == 200:
            pattern = r'^((25[0-5]|2[0-4][0-9]|[01]?[0-9][0-9]?)\.){3}(25[0-5]|2[0-4][0-9]|[01]?[0-9][0-9]?)$'
            ip_str = respone.text
            if re.match(pattern, ip_str):
                self.debug(f"动态公网IP: {ip_str}")
                return ip_str

    def get_current_iplist(self, cookie: str, app_id: str):
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
            "app_id": app_id,
            "bind_mini_program": "false"
        }
        response: Response = RequestUtils(headers=headers).get_res(url=url, params=params)
        if response.status_code == 200:
            app_json = response.json()

            try:
                ip_list = app_json.get('data').get('white_ip_list').get('ip') or []
            except Exception:
                if app_json.get('result').get('errCode'):
                    self.debug('获取当前可信任IP失败')
                return []
            self.debug(f"当前可信IP: {ip_list}")
            return ip_list

    def set_iplist(self, cookie: str, iplist: list, app_id: str):
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
        data = f'app_id={app_id}&{ip_str}'
        url = "https://work.weixin.qq.com/wework_admin/apps/saveIpConfig"

        response: Response = RequestUtils(headers=headers).post_res(url=url, params=params, data=data)
        if response.status_code == 200:
            json_data = response.json()
            try:
                if json_data.get('data'):
                    self.debug("更新可信IP成功")
                    return True
            except Exception:
                if json_data.get('result').get('errCode'):
                    self.debug('更新可信IP失败')
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
