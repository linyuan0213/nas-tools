import json
import uuid
import requests

from app.utils.commons import SingletonMeta
from config import Config
import log

def generate_tab_id() -> str:
    """Generate a unique tab ID."""
    return str(uuid.uuid4())


class DrissionPageHelper(metaclass=SingletonMeta):

    def __init__(self):
        url = Config().get_config("laboratory").get('chrome_server_host')
        if url:
            if url.endswith("/"):
                self.url = url[:-1]
            self.url = url
        
    def get_status(self) -> bool:
        if self.url:
            return True
        return False

    def get_page_html(self,
                      url: str,
                      cookies=None,
                      timeout: int = 60,
                      click_xpath: str = None) -> str:
        """获取HTML内容"""
        headers = {"Content-Type": "application/json"}
        tab_id = generate_tab_id()
        # 打开新标签
        tabs_url = f"{self.url}/tabs"
        open_tab_data = json.dumps({
            "url": url,
            "tab_name": tab_id,
            "cookie": cookies
        }, separators=(',', ':'))
        try:
            response = requests.post(tabs_url, headers=headers, data=open_tab_data, timeout=timeout)
        except Exception as e:
            log.error(f"打开新标签页失败: {str(e)}")
            self._close_tab(tab_id=tab_id)
            return ""
        if response.status_code != 200:
            log.error(f"打开新标签页失败: {response.text}")
            return ""

        # 获取html内容
        html_url = f"{self.url}/tabs/{tab_id}/html"
        try:
            res_json = self._fetch_html(html_url, timeout)
        except Exception as e:
            log.error(f"获取html失败: {str(e)}")
            self._close_tab(tab_id)
            return ""

        # 处理点击事件
        if click_xpath:
            click_url = f"{self.url}/tabs/click/"
            click_data = json.dumps({
                "tab_name": tab_id,
                "selector": click_xpath
            }, separators=(',', ':'))
            
            try:
                response = requests.post(click_url, headers=headers, data=click_data, timeout=timeout)
            except Exception as e:
                log.error(f"点击标签页失败: {str(e)}")
                self._close_tab(tab_id=tab_id)
                return ""
            if response.status_code != 200:
                log.debug(f"点击失败: {response.text}")
                self._close_tab(tab_id)
                return ""
            try:
                res_json = self._fetch_html(html_url, timeout)
            except Exception as e:
                log.error(f"点击之后获取html失败: {str(e)}")
                self._close_tab(tab_id)
                return ""

        # 关闭标签
        self._close_tab(tab_id)
        html_dict = json.loads(res_json)
        content = html_dict.get("html")
        return content

    def _fetch_html(self, url: str, timeout: int) -> str:
        """返回html"""
        response = requests.get(url=url, timeout=timeout)
        response.raise_for_status()
        return response.text

    def _close_tab(self, tab_id: str):
        """关闭标签页"""
        close_url = f"{self.url}/tabs/{tab_id}"
        try:
            response = requests.delete(close_url)
            if response.status_code != 200:
                log.warning(f"关闭标签页失败: {response.text}")
        except Exception as e:
            log.error(f"关闭标签页异常: {str(e)}")