import json
from typing import List, Optional, Tuple, Dict, Any

from app.utils.types import MediaType
import log
from app.utils import RequestUtils, StringUtils, JsonUtils
from config import Config


class RousiSpider:
    """Rousi.pro API v1 Spider

    使用 API v1 接口进行种子搜索
    - 认证方式：Bearer Token (Passkey)
    - 搜索接口：/api/v1/torrents
    - 详情接口：/api/v1/torrents/:id
    """

    _CATEGORY_ID_MAP: Dict[str, str] = {
        '1': 'movie',
        '2': 'tv',
        '3': 'documentary',
        '4': 'animation',
        '6': 'variety'
    }

    _BEARER_PREFIX = "Bearer "
    _DEFAULT_PAGE_SIZE = 100
    _DEFAULT_TIMEOUT = 15
    _MOVIE_CATEGORY = 'movie'
    _TV_CATEGORY = 'tv'

    _indexerid = None
    _domain = None
    _url = None
    _name = ""
    _proxy = None
    _cookie = None
    _ua = None
    _size = _DEFAULT_PAGE_SIZE
    _searchurl = "https://%s/api/v1/torrents"
    _timeout = _DEFAULT_TIMEOUT
    _headers: Dict[str, str] = {}

    @staticmethod
    def _get_header(headers: dict, key: str) -> str:
        """大小写不敏感地获取 header 值"""
        key_lower = key.lower()
        for k, v in headers.items():
            if k.lower() == key_lower:
                return v
        return ""

    def __init__(self, indexer) -> None:
        self._indexerid = indexer.id
        self._url = indexer.domain
        self._domain = StringUtils.get_url_domain(self._url)
        self._searchurl = self._searchurl % self._domain
        self._name = indexer.name
        if indexer.proxy:
            self._proxy = Config().get_proxies()
        self._cookie = indexer.cookie
        self._ua = indexer.ua
        if JsonUtils.is_valid_json(indexer.headers):
            self._headers = json.loads(indexer.headers) or {}
        else:
            self._headers = {}
        self.init_config()

    def init_config(self) -> None:
        """从配置中读取站点搜索结果数量限制"""
        try:
            pt_config = Config().get_config('pt')
            self._size = pt_config.get('site_search_result_num') or self._DEFAULT_PAGE_SIZE
        except (AttributeError, TypeError):
            self._size = self._DEFAULT_PAGE_SIZE

    def _get_apikey(self) -> Optional[str]:
        """从 Authorization header 中提取 API Key"""
        auth_header = self._get_header(self._headers, "Authorization")
        if not auth_header.startswith(self._BEARER_PREFIX):
            return None
        apikey = auth_header[len(self._BEARER_PREFIX):].strip()
        return apikey if apikey else None

    def __get_params(
        self,
        keyword: str,
        mtype: Optional[MediaType] = None,
        cat: Optional[str] = None,
        page: int = 0
    ) -> Dict[str, Any]:
        """构建 API 请求参数"""
        params: Dict[str, Any] = {
            "page": page + 1,
            "page_size": self._size
        }
        if keyword:
            params["keyword"] = keyword

        category = self._resolve_category(cat, mtype)
        if category:
            params["category"] = category

        return params

    def _resolve_category(
        self,
        cat: Optional[str],
        mtype: Optional[MediaType]
    ) -> Optional[str]:
        """解析分类参数，优先使用用户选择的分类，否则根据媒体类型推断"""
        if cat:
            category_names = self.__get_category_names_by_ids(cat)
            return category_names[0] if category_names else None

        if mtype == MediaType.MOVIE:
            return self._MOVIE_CATEGORY
        elif mtype == MediaType.TV:
            return self._TV_CATEGORY

        return None

    def __get_category_names_by_ids(self, cat: str) -> List[str]:
        """将分类 ID 字符串映射为 category names"""
        if not cat:
            return []

        cat_ids = [c.strip() for c in cat.split(',') if c.strip()]
        return [
            self._CATEGORY_ID_MAP[cat_id]
            for cat_id in cat_ids
            if cat_id in self._CATEGORY_ID_MAP
        ]

    def __process_response(self, res) -> Tuple[bool, List[dict]]:
        """处理 API 响应，返回 (是否错误, 种子列表)"""
        if res is None:
            log.warn(f"【INDEXER】{self._name} 搜索失败，无法连接 {self._domain}")
            return True, []

        if res.status_code != 200:
            log.warn(f"【INDEXER】{self._name} 搜索失败，HTTP 错误码：{res.status_code}")
            return True, []

        try:
            data = res.json()
        except ValueError as e:
            log.warn(f"【INDEXER】{self._name} 解析 JSON 响应失败：{e}")
            return True, []

        if data.get('code') != 0:
            log.warn(f"【INDEXER】{self._name} 搜索失败，错误信息：{data.get('message')}")
            return True, []

        results = data.get('data', {}).get('torrents', [])
        return False, self.__parse_result(results)

    @staticmethod
    def __parse_category(raw_cat: Any) -> str:
        """解析分类信息为 MediaType 值"""
        if isinstance(raw_cat, dict):
            cat_val = raw_cat.get('slug') or raw_cat.get('name')
        elif isinstance(raw_cat, str):
            cat_val = raw_cat
        else:
            return MediaType.UNKNOWN.value

        if not cat_val:
            return MediaType.UNKNOWN.value

        cat_val = str(cat_val).lower()
        if cat_val == RousiSpider._MOVIE_CATEGORY:
            return MediaType.MOVIE.value
        elif cat_val == RousiSpider._TV_CATEGORY:
            return MediaType.TV.value
        return MediaType.UNKNOWN.value

    @staticmethod
    def __parse_promotion(promotion: Optional[Dict[str, Any]]) -> Tuple[float, float, Optional[str]]:
        """解析促销信息，返回 (下载系数, 上传系数, 促销到期时间)"""
        if not promotion or not promotion.get('is_active'):
            return 1.0, 1.0, None

        downloadvolumefactor = float(promotion.get('down_multiplier', 1.0))
        uploadvolumefactor = float(promotion.get('up_multiplier', 1.0))
        freedate = None

        until = promotion.get('until')
        if until:
            freedate = StringUtils.unify_datetime_str(until)

        return downloadvolumefactor, uploadvolumefactor, freedate

    def __parse_result(self, results: List[dict]) -> List[dict]:
        """将 API 返回的种子数据转换为标准格式"""
        if not results:
            return []

        torrents = []
        for result in results:
            category = self.__parse_category(result.get('category'))
            downloadvolumefactor, uploadvolumefactor, freedate = self.__parse_promotion(
                result.get('promotion')
            )

            torrent = {
                'indexer': self._indexerid,
                'title': result.get('title', ''),
                'description': result.get('subtitle', ''),
                'enclosure': self.__get_download_url(result.get('uuid')),
                'pubdate': StringUtils.unify_datetime_str(result.get('created_at')),
                'size': int(result.get('size') or 0),
                'seeders': int(result.get('seeders') or 0),
                'peers': int(result.get('leechers') or 0),
                'grabs': int(result.get('downloads') or 0),
                'downloadvolumefactor': downloadvolumefactor,
                'uploadvolumefactor': uploadvolumefactor,
                'freedate': freedate,
                'page_url': f"https://{self._domain}/torrent/{result.get('uuid')}",
                'labels': [],
                'category': category
            }
            torrents.append(torrent)

        return torrents

    def search(
        self,
        keyword: str,
        mtype: Optional[MediaType] = None,
        cat: Optional[str] = None,
        page: int = 0
    ) -> Tuple[bool, List[dict]]:
        """同步搜索种子，返回 (是否错误, 种子列表)"""
        params = self.__get_params(keyword, mtype, cat, page)

        headers = {**self._headers, "Accept": "application/json"}

        res = RequestUtils(
            headers=headers,
            proxies=self._proxy,
            timeout=self._timeout
        ).get_res(url=self._searchurl, params=params)

        return self.__process_response(res)

    def __get_download_url(self, uuid: Optional[str]) -> str:
        """构建种子下载链接，格式: https://rousi.pro/api/torrent/{uuid}/download/{apikey}"""
        if not uuid:
            log.warn(f"【INDEXER】{self._name} 获取下载链接失败，uuid 为空")
            return ""

        apikey = self._get_apikey()
        if not apikey:
            log.warn(f"【INDEXER】{self._name} 获取下载链接失败，未找到有效的 apikey")
            return ""

        return f"https://{self._domain}/api/torrent/{uuid}/download/{apikey}"
