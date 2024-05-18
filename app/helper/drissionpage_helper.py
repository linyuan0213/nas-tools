from DrissionPage import ChromiumPage, ChromiumOptions
from typing import Callable, Tuple
from loguru import logger


class DrissionPageHelper:

    def __init__(self):
        self.co = ChromiumOptions()
        self.co.auto_port()
        self.co.headless(False)
        self.co.set_timeouts(base=2, script=3)
        self.co.set_retry(times=3, interval=2)
        self.co.incognito(True)
        self.co.set_argument('--headless', 'new')
        self.co.set_argument('--no-sandbox')

    def get_status(self):
        return True

    @staticmethod
    def sync_cf_retry(page: ChromiumPage, tries: int = 10) -> Tuple[bool, bool]:
        success = False
        cf = True
        user_tries = tries
        while tries > 0:
            page.wait(1.5)
            try:
                success = False if page(
                    "x://div[@id='challenge-stage']", timeout=10) else True
                if success:
                    page.stop_loading()
                    break
                for target_frame in page.get_frames():
                    if "challenge" in target_frame.url and "turnstile" in target_frame.url:
                        try:
                            click = target_frame(
                                "x://input[@type='checkbox']", timeout=2)
                            if click:
                                click.click()
                        except Exception as e:
                            logger.debug(f"DrissionPage Click Error: {e}")
            except Exception as e:
                logger.debug(f"DrissionPage Error: {e}")
                success = False
            tries -= 1
        if tries == user_tries:
            cf = False
        return success, cf

    def get_page_html(self,
                      url: str,
                      cookies=None,
                      ua: str = None,
                      proxies: dict = None,
                      headless: bool = True,
                      timeout: int = 20,
                      callback: Callable = None) -> str:

        if proxies:
            proxy = proxies.get('https').split('//')[1]
            self.co.set_proxy(proxy=proxy)
        self.co.headless(headless)
        self.co.set_timeouts(base=timeout, script=5)
        if ua:
            self.co.set_user_agent(user_agent=ua)
        page = ChromiumPage(self.co)
        page.set.load_mode.none()
        page.get(url)
        if cookies:
            if isinstance(cookies, str):
                cookies = cookies.strip()
            page.set.cookies(cookies)
        success, _ = self.sync_cf_retry(page)

        content = ''
        if success:
            page.set.load_mode.eager()
            page.get(url)
            if callback:
                try:
                    callback(page)
                except Exception as e:
                    logger.error(f"url: {url} 回调函数执行失败: {e}")
            logger.debug(f"url: {url} 获取网页源码成功")
            content = page.html
        else:
            logger.error(f"url: {url} 获取网页源码失败")
        page.quit()

        return content
