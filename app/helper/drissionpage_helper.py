from DrissionPage import ChromiumPage, ChromiumOptions
from typing import Callable, Tuple
from loguru import logger

from app.helper.cloudflare_helper import under_challenge
from app.utils.commons import SingletonMeta
from config import CHROME_PATH

JS_SCRIPT = """
function getRandomInt(min, max) {
    return Math.floor(Math.random() * (max - min + 1)) + min;
}

function modifyClickEvent(event) {
    if (!event._isModified) {
        // Save original values only if not already saved
        event._screenX = event.screenX;
        event._screenY = event.screenY;

        // Define properties only once
        Object.defineProperty(event, 'screenX', {
            get: function() {
                return this._screenX + getRandomInt(0, 200);
            }
        });
        Object.defineProperty(event, 'screenY', {
            get: function() {
                return this._screenY + getRandomInt(0, 200);
            }
        });

        // Mark event as modified
        event._isModified = true;
    }
}

// Store the original addEventListener method
const originalAddEventListener = EventTarget.prototype.addEventListener;

// Override the addEventListener method
EventTarget.prototype.addEventListener = function(type, listener, options) {
    if (type === 'click') {
        const wrappedListener = function(event) {
            // Modify the click event properties
            modifyClickEvent(event);

            // Call the original listener with the modified event
            listener.call(this, event);
        };
        // Call the original addEventListener with the wrapped listener
        originalAddEventListener.call(this, type, wrappedListener, options);
    } else {
        // Call the original addEventListener for other event types
        originalAddEventListener.call(this, type, listener, options);
    }
};
"""

class DrissionPageHelper(metaclass=SingletonMeta):

    def __init__(self):
        self.co = ChromiumOptions()
        self.co.set_browser_path(CHROME_PATH)
        self.co.auto_port()
        self.co.set_timeouts(base=2, script=3)
        self.co.set_retry(times=3, interval=2)
        self.co.incognito(False)
        self.co.set_argument('--headless', 'new')
        self.co.set_argument('--no-sandbox')
        self.co.set_argument('--disable-webgl')
        # self.co.set_argument('--display=:99')

    def get_status(self):
        return True

    @staticmethod
    def sync_cf_retry(page: ChromiumPage, tries: int = 5) -> Tuple[bool, bool]:
        success = False
        cf = True
        user_tries = tries
        while tries > 0:
            # 非CF网站
            page.wait(5)
            if not under_challenge(page.html):
                success = True
                page.stop_loading()
                break
            try:
                page.wait(5)
                cf_wrapper = page.ele('.spacer', timeout=3).ele('tag:div').ele('tag:div')
                cf_iframe = cf_wrapper.shadow_root.ele("tag=iframe",timeout=3)
                try:
                    box = cf_iframe.ele('tag:body').shadow_root.ele('.cb-i')
                    box.click()
                except Exception as e:
                    logger.debug(f"DrissionPage Click Error: {e}")
            except Exception as e:
                if not under_challenge(page.html):
                    success = True
                    page.wait(1)
                    page.stop_loading()
                    break
                page.wait(3)
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
            proxy = proxies.get('https')
            self.co.set_proxy(proxy=proxy)
        self.co.headless(headless)
        self.co.set_timeouts(base=timeout, script=5)
        if ua:
            self.co.set_user_agent(user_agent=ua)
        page = ChromiumPage(self.co, timeout=180)
        # 等待 page 加载完成
        page.wait(1)
        try:
            page.add_init_js(JS_SCRIPT)
            page.set.window.max()
            page.set.load_mode.none()
            page.get(url, retry=3)
        except Exception as e:
            logger.debug(f"DrissionPage Error: {e}")
            page.quit()
            return ''
        if cookies:
            if isinstance(cookies, str):
                cookies = cookies.strip()
            page.set.cookies(cookies)
        try:
            success, _ = self.sync_cf_retry(page)
        except Exception:
            logger.debug(f"DrissionPage Error: {e}")
            success, _ = self.sync_cf_retry(page)
        content = ''
        if success:
            page.set.load_mode.eager()
            page.get(url, retry=3)
            if callback:
                try:
                    callback(page)
                except Exception as e:
                    logger.error(f"url: {url} 回调函数执行失败: {e}")
            # 嵌入CF处理
            try:
                content = page.html
                if 'TurnstileCallback' in content or under_challenge(content):
                    page.wait(15)
                    content = page.html
                logger.debug(f"url: {url} 获取网页源码成功")
            except Exception as e:
                logger.error(f"url: {url} 获取网页源码失败")
                page.quit()
        else:
            logger.error(f"url: {url} 获取网页源码失败")
        page.quit()

        return content
