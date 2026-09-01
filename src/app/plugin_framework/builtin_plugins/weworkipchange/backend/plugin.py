"""
WeworkIPChange Plugin v2
定时获取动态IP更新到企业微信可信任IP列表
"""

import contextlib
import random
import re
import time
from concurrent.futures import ThreadPoolExecutor
from threading import Event

from pyquery import PyQuery

import log
from app.infrastructure.cache_system import get_cache_manager
from app.infrastructure.cache_system.cookiecloud_adapter import CookiecloudAdapter
from app.infrastructure.chrome import BrowserSession
from app.infrastructure.http.client import HttpClient
from app.plugin_framework.context import PluginContext
from app.utils.browser_mode import get_chrome_server_url
from app.utils.config_tools import get_ua


class WeworkIPChangePlugin:
    """企业微信可信任IP更新插件"""

    def __init__(
        self,
        ctx: PluginContext,
    ):
        self.ctx = ctx
        self._cache = None
        self._session: BrowserSession | None = None
        self._session_id = "wework"
        self._ip_url = "https://4.ipw.cn"
        self._event = Event()

    def _get_server_url(self) -> str:
        return get_chrome_server_url() or ""

    def _get_config(self):
        return self.ctx.get_config() or {}

    def _ensure_session(self) -> BrowserSession | None:
        """获取或创建 BrowserSession。"""
        server_url = self._get_server_url()
        if not server_url:
            return None
        if self._session is None:
            self._session = BrowserSession(
                site_key=self._session_id,
                server_url=server_url,
            )
        return self._session

    def on_enable(self):
        self.ctx.info("企业微信可信IP更新插件已启用")
        self._cache = get_cache_manager().get_or_create("wework_ipchange", cache_type="redis", fallback_maxsize=10)
        self._init_chrome_tab()
        self.ctx.hook_system.register("wework.login", self.ctx.plugin_id)
        self._start_service()

    def on_disable(self):
        self.ctx.info("企业微信可信IP更新插件已禁用")
        self._event.set()
        self._stop_service()
        if self._session is not None:
            try:
                self._session.close()
            except Exception as e:
                log.debug(f"[Wework] 关闭 BrowserSession 失败: {e}")
            self._session = None

    def on_hook(self, event, data):
        if event == "plugin.config_changed":
            if data.get("plugin_id") == self.ctx.plugin_id:
                self.ctx.info("配置已变更，重载服务")
                self._stop_service()
                self._start_service()
        elif event == "wework.login":
            self.login_by_code(data)

    def run(self):
        """立即运行IP更新"""
        self.ctx.info("手动触发企业微信可信IP更新")
        self._change_ip(manual=True)

    def _init_chrome_tab(self):
        if not self._cache:
            return
        session = self._ensure_session()
        if not session:
            return
        try:
            cached_id = self._cache.get("session_id")
            if isinstance(cached_id, bytes):
                cached_id = cached_id.decode("utf-8")
            if not cached_id:
                self.ctx.info("初始化企业微信 BrowserSession")
                session.navigate(
                    "https://work.weixin.qq.com/wework_admin/frame",
                    cookie=self._get_config().get("cookie", ""),
                )
                self._cache.set("session_id", self._session_id)
            else:
                self.ctx.debug(f"复用 BrowserSession: {cached_id}")
                self._session_id = cached_id
        except Exception as e:
            self.ctx.error(f"初始化BrowserSession失败: {e}")

    def _start_service(self):
        config = self._get_config()
        enabled = config.get("enabled", False)
        cron = config.get("cron")

        if not enabled:
            return

        self._event.clear()

        if cron:
            self.ctx.info(f"企业微信可信IP更新服务启动，周期：{cron}")
            self.ctx.schedule_cron("change_ip", self._change_ip, cron=str(cron))

    def _stop_service(self):
        try:
            self.ctx.remove_schedule("change_ip")
            self.ctx.remove_schedule("change_ip_once")
        except Exception as e:  # noqa: BLE001
            log.debug(f"[Plugin]忽略异常: {e}")

    def login_by_code(self, data=None) -> bool:
        session = self._ensure_session()
        if not session:
            return False
        item = data or {}
        if item:
            msg = item.get("msg")
            self.ctx.debug(f"验证码: {msg}")
            try:
                session.input("tag:div@class=number_panel", msg or "")
                self.ctx.debug("验证码输入成功")
                return True
            except Exception as e:
                self.ctx.error(f"验证码输入失败: {e}")
        return False

    def _get_cookie_by_chrome(self) -> bool:
        session = self._ensure_session()
        if not session:
            return False
        login_status = False
        try:
            # 刷新页面重新获取状态
            session.navigate("https://work.weixin.qq.com/wework_admin/frame")
            html_text = session.html()
            if html_text and "退出" in html_text:
                login_status = True
                self.ctx.info("登录成功")
            else:
                # 尝试 iframe 内二维码
                html_text = session.html()
                if html_text:
                    html_doc = PyQuery(html_text)
                    img_url = html_doc("img.qrcode_login_img.js_qrcode_img").attr("src")
                    self.ctx.debug(f"获取二维码成功，当前二维码url: {img_url}")
                    if img_url:
                        img_url = f"https://work.weixin.qq.com{img_url}"
                        self.ctx.info("登录已过期，重新登录")
                        self.ctx.notify(title="[企业微信登录过期]", text="请点击扫码重新登录", image=img_url)
        except Exception as e:
            self.ctx.error(f"刷新页面失败: {e}")

        if not login_status:
            start = time.time()
            self.ctx.info("等待扫码结果...")
            while time.time() - start < 60:
                time.sleep(5)
                try:
                    html_text = session.html()
                except Exception:
                    html_text = ""
                if html_text and ("短信安全验证" in html_text or "SMS" in html_text):
                    self.ctx.info("等待输入验证码...")
                    self.ctx.notify(title="[企业微信登录验证码]", text="请输入 /wxl+验证码 认证")
                if html_text and ("退出" in html_text or "Quit" in html_text):
                    login_status = True
                    break
            if login_status:
                self.ctx.info("登录成功")
            else:
                self.ctx.info("登录失败，请重新登录...")
                return False

        try:
            cookie = session.cookies().get("cookie", "")
            self.ctx.debug(f"获取cookie成功，当前cookie: {cookie}")
            self.ctx.set_config("cookie", cookie)
            return True
        except Exception as e:
            self.ctx.error(f"获取cookie失败: {e}")
            return False

    def _change_ip(self, manual=False):
        config = self._get_config()
        if not manual and not config.get("enabled", False):
            self.ctx.info("插件未启用，跳过IP更新")
            return
        self.ctx.info(f"当前时间 {time.strftime('%Y-%m-%d %H:%M:%S', time.localtime(time.time()))} 开始更新IP")
        use_cookiecloud = config.get("use_cookiecloud")
        use_chrome = config.get("use_chrome")
        cookie = config.get("cookie")
        app_ids = config.get("app_ids")
        overwrite = config.get("overwrite", True)
        notify = config.get("notify", False)

        if not app_ids:
            self.ctx.warn("未配置企业微信APP ID")
            return

        if use_cookiecloud:
            self.ctx.emit("site.cookie_sync", {})
            time.sleep(10)
            cookie = CookiecloudAdapter().get_cookie("qq.com")

        if use_chrome:
            if not self._get_cookie_by_chrome():
                return
            cookie = self.ctx.get_config("cookie")

        dynamic_ip = self._get_current_dynamic_ip()
        if not dynamic_ip:
            self.ctx.error("获取动态IP失败")
            return

        app_ids_list = [app_id.strip() for app_id in app_ids.split(",") if app_id.strip()]
        if not app_ids_list:
            self.ctx.warn("APP ID解析为空")
            return

        all_msg = []
        with ThreadPoolExecutor(max_workers=min(4, len(app_ids_list))) as executor:
            futures = [
                executor.submit(self._process_single_app, app_id, cookie, dynamic_ip, overwrite)
                for app_id in app_ids_list
            ]
            for future in futures:
                try:
                    all_msg.append(future.result())
                except Exception as e:
                    all_msg.append(f"处理异常: {e}\n")

        final_msg = "".join(all_msg)
        self.ctx.info(final_msg)

        if notify:
            schedules = self.ctx.get_schedules()
            next_run_time = ""
            if schedules:
                with contextlib.suppress(Exception):
                    next_run_time = schedules[0].next_run_time.strftime("%Y-%m-%d %H:%M:%S")
            self.ctx.notify(
                title="[自动更新企业微信可信IP任务完成]", text=final_msg + f"\n下次更新时间: {next_run_time}"
            )

    def _process_single_app(self, app_id, cookie, dynamic_ip, overwrite):
        if self._event.is_set():
            return ""
        msg = ""
        update_status = False
        try:
            ips = self._get_current_iplist(cookie=cookie, app_id=app_id)
            ip_exist = dynamic_ip in ips if ips else False

            iplist = []
            if not overwrite:
                iplist = ips.copy() if ips else []
            iplist.append(dynamic_ip)

            if not ip_exist:
                update_status = self._set_iplist(cookie=cookie, iplist=iplist, app_id=app_id)
                if update_status:
                    self.ctx.info(f"AppID[{app_id}] 更新可信IP成功，当前IP: {dynamic_ip}")
                else:
                    self.ctx.error(f"AppID[{app_id}] 更新可信IP失败，请检查cookie")

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
            self.ctx.error(msg)
        return msg

    def _get_current_dynamic_ip(self):
        try:
            response = HttpClient().get(url=self._ip_url)
            pattern = r"^((25[0-5]|2[0-4][0-9]|[01]?[0-9][0-9]?)\.){3}(25[0-5]|2[0-4][0-9]|[01]?[0-9][0-9]?)"
            ip_str = response.text.strip()
            if re.match(pattern, ip_str):
                self.ctx.debug(f"动态公网IP: {ip_str}")
                return ip_str
        except Exception as e:
            self.ctx.error(f"获取动态IP失败: {e}")
        return None

    def _get_current_iplist(self, cookie: str, app_id: str):
        headers = {
            "accept": "application/json, text/javascript, */*; q=0.01",
            "accept-language": "zh-CN,zh;q=0.9,en;q=0.8,ja;q=0.7",
            "content-type": "application/x-www-form-urlencoded",
            "referer": "https://work.weixin.qq.com/wework_admin/frame",
            "cookie": cookie,
            "user-agent": get_ua(),
            "x-requested-with": "XMLHttpRequest",
        }
        url = "https://work.weixin.qq.com/wework_admin/apps/getOpenApiApp"
        params = {
            "lang": "zh_CN",
            "f": "json",
            "ajax": "1",
            "timeZoneInfo%5Bzone_offset%5D": "-8",
            "random": str(random.random()),
            "app_id": app_id,
            "bind_mini_program": "false",
        }
        try:
            response = HttpClient().get(url=url, params=params, headers=headers)
            app_json = response.json()
            try:
                ip_list = app_json.get("data", {}).get("white_ip_list", {}).get("ip") or []
            except Exception:
                if app_json.get("result", {}).get("errCode"):
                    self.ctx.debug("获取当前可信任IP失败")
                return []
            self.ctx.debug(f"当前可信IP: {ip_list}")
            return ip_list
        except Exception as e:
            self.ctx.error(f"获取可信IP列表失败: {e}")
        return []

    def _set_iplist(self, cookie: str, iplist: list, app_id: str):
        headers = {
            "accept": "application/json, text/javascript, */*; q=0.01",
            "content-type": "application/x-www-form-urlencoded",
            "cookie": cookie,
            "origin": "https://work.weixin.qq.com",
            "referer": "https://work.weixin.qq.com/wework_admin/frame",
            "user-agent": get_ua(),
            "x-requested-with": "XMLHttpRequest",
        }
        params = {
            "lang": "zh_CN",
            "f": "json",
            "ajax": "1",
            "timeZoneInfo[zone_offset]": "-8",
            "random": str(random.random()),
        }
        ip_str = "&".join([f"ipList[]={ip}" for ip in iplist])
        data = f"app_id={app_id}&{ip_str}"
        url = "https://work.weixin.qq.com/wework_admin/apps/saveIpConfig"

        try:
            response = HttpClient().post(url=url, params=params, data=data, headers=headers)
            json_data = response.json()
            try:
                if json_data.get("data"):
                    self.ctx.debug("更新可信IP成功")
                    return True
            except Exception:
                if json_data.get("result", {}).get("errCode"):
                    self.ctx.debug("更新可信IP失败")
                return False
        except Exception as e:
            self.ctx.error(f"设置可信IP列表失败: {e}")
        return False
