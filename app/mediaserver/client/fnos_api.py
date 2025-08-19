import hashlib
import random
import time
import json
from typing import Any, Dict, List
import requests
from urllib.parse import urlparse, parse_qs, urlencode

class Singleton(type):
    _instances = {}
    def __call__(cls, *args, **kwargs):
        if cls not in cls._instances:
            cls._instances[cls] = super().__call__(*args, **kwargs)
        return cls._instances[cls]

class FnOSClient(metaclass=Singleton):
    def __init__(self, base_url, username, password, app_name, auth_key):
        self.base_url = base_url
        self.username = username
        self.password = password
        self.app_name = app_name
        self.auth_key = auth_key
        self._token = None
        self._token_expiry = None
        self.secret = "NDzZTVxnRKP8Z0jXg1VAMonaG8akvh"
    
    def _generate_signature(self, request_data):
        """生成 API 请求签名"""
        # 1. 判断是否为 GET 请求
        is_get = request_data.get("method", "").upper() == "GET"

        # 2. 解析 URL
        url = request_data.get("url", "")
        path, query_params = self._parse_url(url)

        # 3. 构造请求数据字符串
        if is_get:  # GET 请求
            params = {}
            if "params" in request_data and request_data["params"]:
                params.update(request_data["params"])
            if query_params:
                params.update(query_params)
            data_str = "&".join([f"{k}={v}" for k, v in params.items()]) if params else ""
        else:  # 非 GET 请求
            data_str = json.dumps(request_data.get("data", {}), separators=(',', ':'))

        # 4. 计算数据 MD5
        data_md5 = hashlib.md5(data_str.encode('utf-8')).hexdigest()

        # 5. 生成随机数 (6位数字)
        nonce = str(random.randint(100000, 999999))

        # 6. 生成时间戳 (毫秒)
        timestamp = str(int(time.time() * 1000))

        # 7. 构建签名字符串并计算签名
        sign_str = "_".join([self.secret, path, nonce, timestamp, data_md5, self.auth_key])
        sign = hashlib.md5(sign_str.encode('utf-8')).hexdigest()

        # 8. 构造返回结果
        return {
            "nonce": nonce,
            "timestamp": timestamp,
            "sign": sign
        }

    def _parse_url(self, url):
        """解析 URL 返回路径和查询参数字典"""
        if not url:
            return "", {}
        
        parsed = urlparse(url)
        path = parsed.path
        
        # 解析查询参数
        query_params = {}
        if parsed.query:
            for k, v in parse_qs(parsed.query).items():
                query_params[k] = v[0] if v else ""
        
        return path, query_params

    def _get_token(self):
        """获取有效token，如果过期则自动刷新"""
        if self._is_token_expired():
            self._login()
        return self._token
    
    def _is_token_expired(self):
        """检查token是否过期"""
        if not self._token:
            return True
        # 更精确的过期检查
        if self._token_expiry and time.time() > self._token_expiry:
            return True
        return False
    
    def _login(self):
        """执行登录获取新token"""
        url = f"{self.base_url}v/api/v1/login"
        request_data = {
            "method": "post",
            "url": url,
            "params": {},
            "data": {
                "username": self.username,
                "password": self.password,
                "app_name": self.app_name
            }
        }
        
        signature = self._generate_signature(request_data)
        signature_str = "&".join([f"{k}={v}" for k, v in signature.items()])
        
        headers = {
            "Accept": "application/json, text/plain, */*",
            "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/138.0.0.0 Safari/537.36",
            "authx": signature_str
        }
        
        data = json.dumps(request_data["data"], separators=(',', ':'))
        response = requests.post(url, headers=headers, data=data, verify=False)
        res_json = response.json()
        if res_json.get("code") == 0:
            self._token = res_json.get("data").get("token")
            # 设置token过期时间为1小时后
            self._token_expiry = time.time() + 3600
            return True
        return False

    def request(self, endpoint, method="post", params=None, data=None):
        """发送API请求"""
        url = f"{self.base_url}{endpoint}"
        token = self._get_token()
        if not token:
            raise Exception("Failed to get valid token")

        request_data = {
            "method": method,
            "url": url,
            "params": params or {},
            "data": data or {}
        }
        
        signature = self._generate_signature(request_data)
        signature_str = "&".join([f"{k}={v}" for k, v in signature.items()])

        cookies = {"Trim-MC-token": token}
        headers = {
            "Accept": "application/json, text/plain, */*",
            "Authorization": token,
            "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/138.0.0.0 Safari/537.36",
            "authx": signature_str
        }
        
        method = method.lower()
        if method == "get":
            # GET请求将参数拼接到URL中
            if params:
                url += "?" + urlencode(params)
            response = requests.get(url, headers=headers, cookies=cookies, verify=False)
        else:
            # 其他请求使用POST，数据放在请求体中
            data_str = json.dumps(data or {}, separators=(',', ':'))
            response = requests.post(url, headers=headers, cookies=cookies, verify=False, data=data_str)
        return response.json()

    def fetch_all_pages(self, parent_id: str = None, max_retries: int = 3, delay: float = 1,
                       start_page: int = 1, end_page: int = None) -> List[Dict[str, Any]]:
        """
        分页获取数据
        
        Args:
            parent_id: 父级ID (可选)
            max_retries: 最大重试次数 (默认: 3)
            delay: 重试间隔(秒) (默认: 1)
            start_page: 起始页码 (默认: 1)
            end_page: 结束页码 (可选, 不指定则获取所有页)
            
        Returns:
            所有数据的列表
        """
        all_items = []
        page = start_page
        page_size = 50  # 每页大小
        total_items = None
        
        while True:
            retries = 0
            while retries <= max_retries:
                try:
                    data = {
                        "tags": {
                            "type": ["Movie", "TV", "Directory", "Video"]
                        },
                        "sort_type": "DESC",
                        "sort_column": "create_time",
                        "exclude_grouped_video": 1,
                        "page": page,
                        "page_size": page_size
                    }
                    if parent_id:
                        data["ancestor_guid"] = parent_id
                    response = self.request(
                        endpoint="v/api/v1/item/list",
                        data=data
                    )
                    
                    if response.get("code") != 0:
                        raise ValueError(f"API错误: {response.get('msg')}")
                    
                    data = response.get("data", {})
                    items = data.get("list", [])
                    all_items.extend(items)
                    
                    # 第一次请求时获取总数量
                    if total_items is None:
                        total_items = data.get("total", 0)
                        if total_items == 0:  # 如果没有数据，直接返回
                            return all_items
                    
                    # 检查是否已获取所有数据或当前页没有数据或达到结束页
                    if len(all_items) >= total_items or not items or (end_page and page >= end_page):
                        return all_items
                    
                    page += 1
                    break
                    
                except Exception as e:
                    retries += 1
                    if retries > max_retries:
                        print(f"重试{max_retries}次后失败: {str(e)}")
                        return all_items
                    time.sleep(delay)

    def search(self, title: str, libtype: str = "", year: str = "") -> List[Dict[str, Any]]:
        """
        搜索媒体数据
        
        Args:
            title: 标题
            year: 年份
            
        Returns:
            所有数据的列表
        """
        all_items = []

        response = self.request(
            endpoint="v/api/v1/search/list",
            method="get",
            data={},
            params={"q": title}
        )

        if response.get("code") != 0:
            raise ValueError(f"API错误: {response.get('msg')}")

        all_items = [sec for sec in response.get("data", [])
                     if (not libtype or sec.get("type") == libtype)
                     and (not year or (sec.get("air_date") and sec.get("air_date")[:4] == str(year)))]

        return all_items

    def get_session_list(self, item_id: str):
        """
        获取剧集季数据
        
        Args:
            item_id: 剧集guid
            
        Returns:
            所有数据的列表
        """

        response = self.request(
            endpoint=f"v/api/v1/season/list/{item_id}",
            method="get",
            data={}
        )

        if response.get("code") != 0:
            raise ValueError(f"API错误: {response.get('msg')}")
        return response.get("data")
    
    def get_episode_list(self, item_id: str):
        """
        获取剧集季数据
        
        Args:
            item_id: 季guid
            
        Returns:
            所有数据的列表
        """

        response = self.request(
            endpoint=f"v/api/v1/episode/list/{item_id}",
            method="get",
            data={}
        )

        if response.get("code") != 0:
            raise ValueError(f"API错误: {response.get('msg')}")
        return response.get("data")
        
    def get_episode_info(self, item_id: str):
        """
        获取剧集季数据
        
        Args:
            item_id: 季guid
            
        Returns:
            所有数据的列表
        """

        response = self.request(
            endpoint=f"v/api/v1/item/{item_id}",
            method="get",
            data={}
        )
        
        if response.get("code") != 0:
            raise ValueError(f"API错误: {response.get('msg')}")
        return response.get("data")

    def get_library_list(self):
        """
        获取媒体库数据
            
        Returns:
            所有数据的列表
        """
        response = self.request(
            endpoint=f"v/api/v1/mediadb/list",
            method="get",
            data={}
        )
        if response.get("code") != 0:
            raise ValueError(f"API错误: {response.get('msg')}")
        return response.get("data")
        
    
    def refresh_library(self, item_id: str):
        """
        刷新媒体库
        
        Args:
            item_id: 媒体库guid
            
        Returns:
            成功或失败
        """

        response = self.request(
            endpoint=f"v/api/v1/mdb/scan/{item_id}",
            method="post",
            data={}
        )
        if response.get("code") != 0:
            raise ValueError(f"API错误: {response.get('msg')}")
        return response.get("data")

    def get_resume_list(self):
        """
        获取媒体库数据
            
        Returns:
            所有数据的列表
        """
        response = self.request(
            endpoint=f"v/api/v1/play/list",
            method="get",
            data={}
        )
        if response.get("code") != 0:
            raise ValueError(f"API错误: {response.get('msg')}")
        return response.get("data")

# 使用示例
if __name__ == "__main__":
    # 初始化客户端
    client = FnOSClient(
        base_url="http://192.168.50.248:5666/",
        username="xxx",
        password="xxx",
        app_name="trimemedia-web",
        auth_key="16CCEB3D-AB42-077D-36A1-F355324E4237"
    )

    # 示例1: 单页请求
    response = client.request(
        endpoint="/v/api/v1/item/list",
        data={
            "tags": {
                "type": ["Movie", "TV", "Directory", "Video"]
            },
            "sort_type": "DESC",
            "sort_column": "create_time",
            "exclude_grouped_video": 1,
            "page": 1,
            "page_size": 5
        }
    )
    print("单页响应:", response)

    # 示例2: 获取所有分页数据
    try:
        print("开始获取所有数据...")
        items = client.fetch_all_pages()
        print(f"成功获取 {len(items)} 条数据")
        
        # 保存到JSON文件
        with open("all_items.json", "w", encoding="utf-8") as f:
            json.dump(items, f, ensure_ascii=False, indent=2)
        print("结果已保存到 all_items.json")
        
    except Exception as e:
        print(f"发生错误: {str(e)}")
