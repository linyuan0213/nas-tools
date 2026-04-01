import requests
import urllib3
import time
import threading
from urllib3.exceptions import InsecureRequestWarning
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry
from config import Config
import log

urllib3.disable_warnings(InsecureRequestWarning)


class RequestUtils:
    _headers = None
    _cookies = None
    _proxies = None
    _timeout = 20
    _session = None
    
    # 类级别的session缓存
    _session_pool = {}
    _pool_lock = threading.Lock()

    def __init__(self,
                 headers=None,
                 cookies=None,
                 proxies=None,
                 session=None,
                 timeout=None,
                 referer=None,
                 content_type=None,
                 accept_type=None):
        if not content_type:
            content_type = "application/x-www-form-urlencoded; charset=UTF-8"
        if headers:
            if isinstance(headers, str):
                self._headers = {
                    "Content-Type": content_type,
                    "User-Agent": f"{headers}",
                    "Accept": accept_type
                }
            else:
                self._headers = headers
        else:
            self._headers = {
                "Content-Type": content_type,
                "User-Agent": Config().get_ua(),
                "Accept": accept_type
            }
        if referer:
            self._headers.update({
                "referer": referer
            })
        if cookies:
            if isinstance(cookies, str):
                self._cookies = self.cookie_parse(cookies)
            else:
                self._cookies = cookies
        if proxies:
            self._proxies = proxies
        if session:
            self._session = session
            # 将cookies和headers集成到session中
            if self._cookies:
                self._session.cookies.update(self._cookies)
            if self._headers:
                self._session.headers.update(self._headers)
        else:
            # 使用共享的session
            self._session = self._get_shared_session(proxies)
        if timeout:
            self._timeout = timeout
    
    @classmethod
    def _get_shared_session(cls, proxies=None):
        """获取共享的session实例，带连接池"""
        proxy_key = str(proxies) if proxies else "no_proxy"
        
        with cls._pool_lock:
            if proxy_key not in cls._session_pool:
                session = requests.Session()
                
                # 配置重试策略
                retry_strategy = Retry(
                    total=3,
                    backoff_factor=0.5,
                    status_forcelist=[429, 500, 502, 503, 504],
                    allowed_methods=["HEAD", "GET", "OPTIONS", "POST"]
                )
                
                # 配置连接池
                adapter = HTTPAdapter(
                    pool_connections=10,
                    pool_maxsize=50,
                    max_retries=retry_strategy,
                    pool_block=False
                )
                
                session.mount("http://", adapter)
                session.mount("https://", adapter)
                cls._session_pool[proxy_key] = session
            
            return cls._session_pool[proxy_key]

    def post(self, url, data=None, json=None, retries=3):
        if json is None:
            json = {}
        for attempt in range(retries):
            try:
                if self._session:
                    response = self._session.post(url,
                                              data=data,
                                              verify=False,
                                              headers=self._headers,
                                              proxies=self._proxies,
                                              cookies=self._cookies,
                                              timeout=self._timeout,
                                              json=json)
                else:
                    response = requests.post(url,
                                         data=data,
                                         verify=False,
                                         headers=self._headers,
                                         cookies=self._cookies,
                                         proxies=self._proxies,
                                         timeout=self._timeout,
                                         json=json)

                # 检查返回的内容是否为空字符串
                if response.text.strip() == "" and response.status_code not in [301, 302]:
                    log.debug(f"Attempt {attempt + 1} returned an empty string.")
                    # 对于成功的状态码（2xx），即使响应体为空也返回响应对象
                    if 200 <= response.status_code < 300:
                        return response
                    if attempt + 1 < retries:
                        time.sleep(2)  # 重试前等待2秒
                        continue  # 重试
                    else:
                        return response
                return response  # 请求成功且非空字符串时返回响应

            except requests.exceptions.RequestException as e:
                log.debug(f"Attempt {attempt + 1} failed: {e}")
                if attempt + 1 < retries:
                    time.sleep(2)  # 重试前等待2秒
                else:
                    return None  # 达到重试次数上限时，返回None

    def get(self, url, params=None, retries=3):
        for attempt in range(retries):
            try:
                if self._session:
                    r = self._session.get(url,
                                          verify=False,
                                          headers=self._headers,
                                          proxies=self._proxies,
                                          cookies=self._cookies,
                                          timeout=self._timeout,
                                          params=params)
                else:
                    r = requests.get(url,
                                     verify=False,
                                     headers=self._headers,
                                     cookies=self._cookies,
                                     proxies=self._proxies,
                                     timeout=self._timeout,
                                     params=params)
                # 检查返回的内容是否为空字符串
                if r.text.strip() == "" and r.status_code not in [301, 302]:
                    log.debug(f"Attempt {attempt + 1} returned an empty string.")
                    # 对于成功的状态码（2xx），即使响应体为空也返回空字符串（这是预期的）
                    if 200 <= r.status_code < 300:
                        return ""
                    if attempt + 1 < retries:
                        time.sleep(2)  # 重试前等待2秒
                        continue  # 重试
                    else:
                        return ""  # 达到重试次数上限，返回空字符串
                return r.text  # 请求成功且非空字符串时返回响应

            except requests.exceptions.RequestException as e:
                log.debug(f"Attempt {attempt + 1} failed: {e}")
                if attempt + 1 < retries:
                    time.sleep(2)  # 重试前等待2秒
                else:
                    return None  # 达到重试次数上限时，返回None

    def get_res(self, url, params=None, allow_redirects=True, raise_exception=False, retries=3):
        for attempt in range(retries):
            try:
                if self._session:
                    response = self._session.get(url,
                                            params=params,
                                            verify=False,
                                            headers=self._headers,
                                            proxies=self._proxies,
                                            cookies=self._cookies,
                                            timeout=self._timeout,
                                            allow_redirects=allow_redirects)
                else:
                    response = requests.get(url,
                                        params=params,
                                        verify=False,
                                        headers=self._headers,
                                        proxies=self._proxies,
                                        cookies=self._cookies,
                                        timeout=self._timeout,
                                        allow_redirects=allow_redirects)
                
                # 检查返回的内容是否为空字符串
                if response.text.strip() == "" and response.status_code not in [301, 302]:
                    log.debug(f"Attempt {attempt + 1} returned an empty string.")
                    # 对于成功的状态码（2xx），即使响应体为空也返回响应对象
                    if 200 <= response.status_code < 300:
                        return response
                    if attempt + 1 < retries:
                        time.sleep(2)  # 重试前等待2秒
                        continue  # 重试
                    else:
                        return response
                return response  # 请求成功且非空字符串时返回响应

            except requests.exceptions.RequestException as e:
                log.debug(f"Attempt {attempt + 1} failed: {e}")
                if attempt + 1 < retries:
                    time.sleep(2)  # 重试前等待2秒
                else:
                    return None  # 达到重试次数上限时，返回None

    def post_res(self, url, data=None, params=None, allow_redirects=True, files=None, json=None, retries=3):
        for attempt in range(retries):
            try:
                if self._session:
                    response = self._session.post(url,
                                                data=data,
                                                params=params,
                                                verify=False,
                                                headers=self._headers,
                                                proxies=self._proxies,
                                                cookies=self._cookies,
                                                timeout=self._timeout,
                                                allow_redirects=allow_redirects,
                                                files=files,
                                                json=json)
                else:
                    response = requests.post(url,
                                            data=data,
                                            params=params,
                                            verify=False,
                                            headers=self._headers,
                                            proxies=self._proxies,
                                            cookies=self._cookies,
                                            timeout=self._timeout,
                                            allow_redirects=allow_redirects,
                                            files=files,
                                            json=json)

                # 检查返回的内容是否为空字符串
                if response.text.strip() == "" and response.status_code not in [301, 302]:
                    log.debug(f"Attempt {attempt + 1} returned an empty string.")
                    # 对于成功的状态码（2xx），即使响应体为空也返回响应对象
                    if 200 <= response.status_code < 300:
                        return response
                    if attempt + 1 < retries:
                        time.sleep(2)  # 重试前等待2秒
                        continue  # 重试
                    else:
                        return ""  # 达到重试次数上限，返回空字符串
                return response  # 请求成功且非空字符串时返回响应

            except requests.exceptions.RequestException as e:
                log.debug(f"Attempt {attempt + 1} failed: {e}")
                if attempt + 1 < retries:
                    time.sleep(2)  # 重试前等待2秒
                else:
                    return None  # 达到重试次数上限时，返回None

    @staticmethod
    def cookie_parse(cookies_str, array=False):
        """
        解析cookie，转化为字典或者数组
        :param cookies_str: cookie字符串
        :param array: 是否转化为数组
        :return: 字典或者数组
        """
        if not cookies_str:
            return {}
        cookie_dict = {}
        cookies = cookies_str.split(';')
        for cookie in cookies:
            cstr = cookie.split('=')
            if len(cstr) > 1:
                cookie_dict[cstr[0].strip()] = cstr[1].strip()
        if array:
            cookiesList = []
            for cookieName, cookieValue in cookie_dict.items():
                cookies = {'name': cookieName, 'value': cookieValue}
                cookiesList.append(cookies)
            return cookiesList
        return cookie_dict
