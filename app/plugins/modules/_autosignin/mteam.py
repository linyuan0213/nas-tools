from time import sleep
import time
from app.helper.drissionpage_helper import DrissionPageHelper
from app.plugins.event_manager import EventHandler
from app.plugins.modules._autosignin._base import _ISiteSigninHandler
from app.helper.cookiecloud_helper import CookiecloudHelper
from app.utils import StringUtils, RequestUtils
from app.utils.types import EventType
from config import Config


class MTeam(_ISiteSigninHandler):
    """
    馒头登录
    """
    # 匹配的站点Url，每一个实现类都需要设置为自己的站点Url
    site_url = "kp.m-team.cc"

    # 已登录
    _sign_text = '魔力值'

    @classmethod
    def match(cls, url):
        """
        根据站点Url判断是否匹配当前站点签到类，大部分情况使用默认实现即可
        :param url: 站点Url
        :return: 是否匹配，如匹配则会调用该类的signin方法
        """
        return True if StringUtils.url_equal(url, cls.site_url) else False

    def signin(self, site_info: dict):
        """
        执行签到操作
        :param site_info: 站点信息，含有站点Url、站点Cookie、UA等信息
        :return: 签到结果信息
        """
        site = site_info.get("name")
        site_cookie = site_info.get("cookie")
        ua = site_info.get("ua")
        proxy = Config().get_proxies() if site_info.get("proxy") else None
        
        EventHandler.send_event(EventType.LocalStorageSync)
        time.sleep(10)
        local_storage = CookiecloudHelper().get_local_storage('m-team.io')

        if not local_storage:
            self.error("仿真登录失败，LocalStorage获取失败或为空")
            return False, f'【{site}】仿真登录失败，LocalStorage获取失败或为空'
        
        persist_user = local_storage.get('persist:user')
        auth = local_storage.get('auth')
        if not persist_user or not auth:
            self.error("仿真登录失败，persist:user获取失败或为空")
            return False, f'【{site}】仿真登录失败，persist:user获取失败或为空'
        self.info(f"{site} 开始仿真登录")
        
        
        # 首页
        chrome = DrissionPageHelper()
        if site_info.get("chrome") and chrome.get_status():
            self.info(f"{site} 开始仿真登录")
            
            html_text = chrome.get_page_html(url="https://kp.m-team.cc/index", local_storage=local_storage)

            if not html_text:
                self.warn("%s 获取站点源码失败" % site)
                return f"【{site}】仿真登录失败，获取站点源码失败！", None

            # 登录成功
            if self._sign_text in html_text:
                self.info("仿真登录成功")
                return True, f'【{site}】仿真登录成功'
            else:
                self.error("仿真登录失败，未找到登录标识")
                return False, f'【{site}】仿真登录失败，未找到登录标识'

