from concurrent.futures import ThreadPoolExecutor
import copy
import re
import json
from datetime import datetime, timedelta
from threading import Event
from apscheduler.triggers.cron import CronTrigger

import pytz
from lxml import etree

from app.helper import SubmoduleHelper, SiteHelper
from app.helper.cloudflare_helper import under_challenge
from app.helper.db_helper import DbHelper
from app.helper.drissionpage_helper import DrissionPageHelper
from app.plugins.modules._base import _IPluginModule
from app.sites.siteconf import SiteConf
from app.sites.sites import Sites
from app.utils import RequestUtils, ExceptionUtils, StringUtils, JsonUtils
from config import Config

from app.scheduler_service import SchedulerService
from app.queue import scheduler_queue


class AutoGenRss(_IPluginModule):
    # 插件名称
    module_name = "RSS自动生成"
    # 插件描述
    module_desc = "RSS自动生成"
    # 插件图标
    module_icon = "rss.png"
    # 主题色
    module_color = "#eaffd0"
    # 插件版本
    module_version = "1.0"
    # 插件作者
    module_author = "linyuan0213"
    # 作者主页
    author_url = "https://github.com/linyuan0213"
    # 插件配置项ID前缀
    module_config_prefix = "autogenrss_"
    # 加载顺序
    module_order = 20
    # 可使用的用户级别
    auth_level = 2

    # 私有属性
    siteconf = None
    _scheduler = None
    _jobstore = "plugin"
    _job_id = None
    # 设置开关
    _enabled = False
    # 任务执行间隔
    _site_schema = []
    _cron = None
    _rss_sites = None
    _dbhelper = None
    _onlyonce = False
    _notify = False
    # 退出事件
    _event = Event()

    @staticmethod
    def get_fields():
        sites = {site.get("id"): site for site in Sites().get_site_dict()}
        return [
            {
                'type': 'div',
                'content': [
                    # 同一行
                    [
                        {
                            'title': '开启定时生成RSS',
                            'required': "",
                            'tooltip': '开启后会根据周期定时生成指定站点RSS。',
                            'type': 'switch',
                            'id': 'enabled',
                        },
                        {
                            'title': '运行时通知',
                            'required': "",
                            'tooltip': '运行生成RSS任务后会发送通知',
                            'type': 'switch',
                            'id': 'notify',
                        },
                        {
                            'title': '立即运行一次',
                            'required': "",
                            'tooltip': '打开后立即运行一次',
                            'type': 'switch',
                            'id': 'onlyonce',
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
                            'title': '运行周期',
                            'required': "",
                            'tooltip': '设置自动同步时间周期，支持5位cron表达式',
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
            },
            {
                'type': 'details',
                'summary': '生成RSS站点',
                'tooltip': '只有选中的站点才会执行RSS生成任务，不选则默认为全选',
                'content': [
                    # 同一行
                    [
                        {
                            'id': 'rss_sites',
                            'type': 'form-selectgroup',
                            'content': sites
                        },
                    ]
                ]
            }
        ]

    def init_config(self, config=None):
        self.siteconf = SiteConf()

        # 读取配置
        if config:
            self._enabled = config.get("enabled")
            self._cron = config.get("cron")
            self._rss_sites = config.get("rss_sites")
            self._notify = config.get("notify")
            self._onlyonce = config.get("onlyonce")

        # 定时服务
        self._scheduler = SchedulerService()
        
        # 数据库
        self._dbhelper = DbHelper()

        # 停止现有任务
        self.stop_service()
        self.run_service()

    def run_service(self):
        # 启动服务
        if self._enabled or self._onlyonce:
            # 加载模块
            self._site_schema = SubmoduleHelper.import_submodules('app.plugins.modules._autogenrss',
                                                                  filter_func=lambda _, obj: hasattr(obj, 'match'))
            self.debug(f"加载特殊站点：{self._site_schema}")

            # 运行一次
            if self._onlyonce:
                self.info("RSS自动生成服务启动，立即运行一次")
                scheduler_queue.put({
                    "func_str": "AutoGenRss.auto_gen_rss",
                    "type": 'plugin',
                    "args": [],
                    "job_id": "AutoGenRss.auto_gen_rss_once",
                    "trigger": "date",
                    "run_date": datetime.now(tz=pytz.timezone(Config().get_timezone())) + timedelta(
                            seconds=3),
                    "jobstore": self._jobstore
                })

            if self._onlyonce:
                # 关闭一次性开关
                self._onlyonce = False
                self.update_config({
                    "enabled": self._enabled,
                    "cron": self._cron,
                    "rss_sites": self._rss_sites,
                    "notify": self._notify,
                    "onlyonce": self._onlyonce
                })

            # 周期运行
            if self._cron:
                self.info(f"同步服务启动，周期：{self._cron}")
                scheduler_queue.put({
                    "func_str": "AutoGenRss.auto_gen_rss",
                    "type": 'plugin',
                    "args": [],
                    "job_id": "AutoGenRss.auto_gen_rss_2",
                    "trigger": CronTrigger.from_crontab(self._cron),
                    "jobstore": self._jobstore
                })


    def auto_gen_rss(self):
        """
        自动生成RSS
        """

        rss_sites = [
            site_id for site_id in self._rss_sites if site_id]

        # 查询站点
        rss_sites = copy.deepcopy(Sites().get_sites(siteids=rss_sites))
        if not rss_sites:
            self.info("没有需要生成的站点，停止运行")
            return

        # 执行签到
        self.info("开始生成RSS任务")
        with ThreadPoolExecutor(min(len(rss_sites), 5)) as p:
            status = p.map(self.gen_rss, rss_sites)

        if status:
            self.info("生成RSS任务任务完成！")

            failed_msg = []

            gen_success_msg = []

            for s in status:
                if not s:
                    continue

                if "成功" in s:
                    gen_success_msg.append(s)
                else:
                    failed_msg.append(s)

            # 发送通知
            if self._notify:
                # rss生成详细信息
                rss_message = "\n".join(gen_success_msg + failed_msg)

                if self._scheduler and self._scheduler.SCHEDULER:
                    for job in self._scheduler.get_jobs():
                        if 'gen_rss' in job.name:
                            next_run_time = job.next_run_time.strftime(
                                '%Y-%m-%d %H:%M:%S')
   
                            self.send_message(title="【自动生成RSS任务完成】",
                                              text=f"生成RSS站点数: {len(rss_sites)} \n"
                                              f"{rss_message} \n"
                                              f"下次生成时间: {next_run_time} \n")
        else:
            self.error("站点生成RSS任务失败！")

    def __build_class(self, url):
        for site_schema in self._site_schema:
            try:
                if site_schema.match(url):
                    return site_schema
            except Exception as e:
                ExceptionUtils.exception_traceback(e)
        return None

    def gen_rss(self, site_info):
        """
        自动生成一个站点rss
        """
        site_module = self.__build_class(site_info.get("signurl"))
        if site_module and hasattr(site_module, "gen_rss"):
            try:
                status, msg = site_module().gen_rss(site_info)
                # 返回成功或者失败信息
                return msg
            except Exception as e:
                return f"【{site_info.get('name')}】生成RSS失败：{str(e)}"
        else:
            return self.__gen_rss_base(site_info)

    def __gen_rss_base(self, site_info):
        """
        通用RSS处理
        :param site_info: 站点信息
        :return: 生成结果信息
        """
        if not site_info:
            return ""
        site = site_info.get("name")
        try:
            site_url = site_info.get("signurl")
            site_cookie = site_info.get("cookie")
            ua = site_info.get("ua")
            headers = site_info.get("headers")
            if (not site_url or not site_cookie) and not headers:
                self.warn("未配置 %s 的Cookie或请求头，无法获取到RSS" % str(site))
                return ""
            if JsonUtils.is_valid_json(headers):
                headers = json.loads(headers)
            else:
                headers = {}
                
            home_url = StringUtils.get_base_url(site_url)
            rss_url = f"{home_url}/getrss.php"
            chrome = DrissionPageHelper()
            if site_info.get("chrome") and chrome.get_status():
                #TODO
                ...
            else:
                self.info(f"开始生成RSS站点：{site}")
                # rss参数
                data = {
                    "inclbookmarked": "0",
                    "itemcategory": "1",
                    "itemsmalldescr": "1",
                    "itemsize": "1",
                    "showrows": "50",
                    "search": "",
                    "search_mode": "1"
                }
                
                headers.update({'User-Agent': ua})
                res = RequestUtils(cookies=site_cookie,
                                    headers=headers,
                                    referer=site_url,
                                    proxies=Config().get_proxies() if site_info.get("proxy") else None
                                    ).post_res(url=rss_url, data=data)
                if res and res.status_code in [200, 500, 403]:
                    if not SiteHelper.is_logged_in(res.text):
                        if under_challenge(res.text):
                            msg = "站点被Cloudflare防护，请开启浏览器仿真"
                        elif res.status_code == 200:
                            msg = "Cookie已失效"
                        else:
                            msg = f"状态码：{res.status_code}"
                        self.warn(f"{site} 生成RSS失败，{msg}")
                        return f"【{site}】生成RSS失败，{msg}！"
                    else:
                        if re.search(r'完成两步验证', res.text, re.IGNORECASE):
                            self.warn("%s 生成RSS失败，需要两步验证" % site)
                            return f"【{site}】生成RSS失败，需要两步验证"
                        
                        # 解析rss url
                        gen_rss_url = self._parse_rss_link(res.text)
                        self.debug(f"生成的rss: {gen_rss_url}")
                        if gen_rss_url:
                            #插入到数据库
                            self._dbhelper.update_site_rssurl(site_info.get("id"), gen_rss_url)
                        
                            self.info(f"{site} 生成RSS成功")
                            return f"【{site}】生成RSS成功"
                elif res is not None:
                    self.warn(f"{site} 生成RSS失败，状态码：{res.status_code}")
                    return f"【{site}】生成RSS失败，状态码：{res.status_code}！"
                else:
                    self.warn(f"{site} 生成RSS失败，无法打开网站")
                    return f"【{site}】生成RSS失败，无法打开网站！"
        except Exception as e:
            ExceptionUtils.exception_traceback(e)
            self.warn("%s 生成RSS失败：%s" % (site, str(e)))
            return f"【{site}】生成RSS失败：{str(e)}！"

    @staticmethod
    def _parse_rss_link(html_text: str) -> str:
        if not html_text:
            return ''

        html = etree.HTML(html_text)
        return next((href for href in html.xpath('//a[contains(@href, "linktype=dl")]/@href')), '')

    def stop_service(self):
        """
        退出插件
        """
        try:
            if self._scheduler and self._scheduler.SCHEDULER:
                for job in self._scheduler.get_jobs():
                    if 'gen_rss' in job.name:
                        self._scheduler.remove_job(job.id)
        except Exception as e:
            self.error(str(e))

    def get_state(self):
        return self._enabled and self._cron
