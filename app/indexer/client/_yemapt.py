import datetime
import pytz
import json

from app.utils.types import MediaType
import log
from app.utils import RequestUtils, JsonUtils
from config import Config


class YemaPTSpider(object):
    _indexerid = None
    _domain = None
    _name = ""
    _proxy = None
    _cookie = None
    _ua = None
    _size = 100
    _passkey = ""
    _searchurl = "%sapi/torrent/fetchCategoryOpenTorrentList"
    _pageurl = "%sapi/torrent/fetchTorrentDetail?id=%s&firstView=false"

    _LABEL_MAP = {
        '5': '国语',
        '6': '中字',
        '7': '粤语',
        '8': '英字'
    }

    def __init__(self, indexer):
        if indexer:
            self._indexerid = indexer.id
            self._domain = indexer.domain
            self._name = indexer.name
            if indexer.proxy:
                self._proxy = Config().get_proxies()
            self._ua = indexer.ua
            self._cookie = indexer.cookie
            if JsonUtils.is_valid_json(indexer.headers):
                self._headers = json.loads(indexer.headers)
            else:
                self._headers = {}
            self._headers.update({
                "Content-Type": "application/json; charset=utf-8",
                "User-Agent": f"{self._ua}"
            })
        self.init_config()

    def init_config(self):
        self._size = Config().get_config('pt').get('site_search_result_num') or 100

    def search(self, keyword="", mtype: MediaType = None, page=0):
        page = int(page) + 1
        cat_list = []
        if not keyword:
            keyword = ""
        self._searchurl = self._searchurl % (self._domain)
        if mtype == MediaType.MOVIE:
            cat_list = [4]
        elif mtype == MediaType.TV:
            cat_list = [5, 13, 15]
        elif mtype == MediaType.ANIME:
            cat_list = [14]
        else:
            cat_list = [4, 5, 13, 14, 15]

        param = {"keyword": '',"categoryId":4,"pageParam":{"current":1,"pageSize":40,"pageSizeOptions":["10","20","40"],"size":"small"},"sorter":None}
        torrents = []
        for cat in cat_list:
            if not keyword:
                if param.get('keyword'):
                    param.pop('keyword')
            else:
                param['keyword'] = keyword
            param['categoryId'] = cat
            param['pageParam']['current'] = page
            data = json.dumps(param, separators=(',', ':'))
            res = RequestUtils(
                headers=self._headers,
                proxies=self._proxy,
                cookies=self._cookie,
                timeout=30
            ).post_res(url=self._searchurl, data=data)
            if res and res.status_code == 200:
                results = res.json().get('data', {}) or []
                for result in results:
                    imdbid = ""
                    discount = result.get('downloadPromotion')
                    tid = result.get('id')
                    enclosure = ""
                    downloadvolumefactor = 0
                    if discount == "free":
                        downloadvolumefactor = 0
                    else:
                        downloadvolumefactor = 1.0

                    org_date = result.get('listingTime')
                    dt_utc = datetime.datetime.fromisoformat(org_date.replace('Z', '+00:00'))

                    local_tz = pytz.timezone(Config().get_timezone())
                    pubdate = dt_utc.astimezone(local_tz).strftime('%Y-%m-%d %H:%M:%S')
                    label_ids = result.get("tagList") or []
                    labels = '|'.join([self._LABEL_MAP.get(label_id) or '' for label_id in label_ids])
                    torrent = {
                        'indexer': self._indexerid,
                        'title': result.get('showName'),
                        'description': result.get('shortDesc'),
                        'labels': labels,
                        'enclosure': enclosure,
                        'pubdate': pubdate,
                        'size': result.get('fileSize'),
                        'seeders': result.get('seedNum'),
                        'peers': result.get('leechNum'),
                        'grabs': result.get('completedNum') if result.get('completedNum') else '',
                        'downloadvolumefactor': downloadvolumefactor,
                        'uploadvolumefactor': 1.0,
                        'page_url': self._pageurl % (self._domain, tid),
                        'imdbid': imdbid
                    }
                    torrents.append(torrent)
            elif res is not None:
                log.warn(f"【INDEXER】{self._name} 搜索失败，错误码：{res.status_code}")
                return True, []
            else:
                log.warn(f"【INDEXER】{self._name} 搜索失败，无法连接 {self._domain}")
                return True, []
        return False, torrents
