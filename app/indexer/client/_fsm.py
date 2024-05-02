import datetime
import pytz
import json

import log
from app.utils import RequestUtils, JsonUtils
from config import Config


class FSMSpider(object):
    _indexerid = None
    _domain = None
    _name = ""
    _proxy = None
    _cookie = None
    _ua = None
    _size = 100
    _passkey = ""
    _searchurl = "%sapi/Torrents/listTorrents?&keyword=%s&page=%s"
    _downloadurl = "%sapi/Torrents/download?tid=%s&passkey=%s&source=direct"
    _pageurl = "%sTorrents/details?tid=%s"
    _infourl = "%sapi/Users/infos"

    def __init__(self, indexer):
        if indexer:
            self._indexerid = indexer.id
            self._domain = indexer.domain
            self._name = indexer.name
            if indexer.proxy:
                self._proxy = Config().get_proxies()
            self._ua = indexer.ua
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
        self.get_passkey()

    def get_passkey(self):
        self._infourl = self._infourl % self._domain
        res = RequestUtils(
            headers=self._headers,
            proxies=self._proxy,
            timeout=30
        ).get_res(url=self._infourl)
        if res and res.status_code == 200:
            info = res.json().get('data')
            if res.json().get('success'):
                self._passkey = info.get('passkey')

    def search(self, keyword="", page=0):
        page = int(page) + 1
        if not keyword:
            keyword = ""
        self._searchurl = self._searchurl % (self._domain, keyword, page)
        res = RequestUtils(
            headers=self._headers,
            proxies=self._proxy,
            timeout=30
        ).get_res(url=self._searchurl)
        torrents = []
        if res and res.status_code == 200:
            results = res.json().get('data', {}).get("list") or []
            for result in results:
                imdbid = ""
                discount = result.get('status').get('name')
                tid = result.get('tid')
                enclosure = self._downloadurl % (self._domain, tid, self._passkey)
                downloadvolumefactor = 0
                if discount == "Free":
                    downloadvolumefactor = 0
                else:
                    downloadvolumefactor = 1.0
                torrent = {
                    'indexer': self._indexerid,
                    'title': result.get('title'),
                    'description': "",
                    'enclosure': enclosure,
                    'pubdate': datetime.datetime.fromtimestamp(result.get('createdTs'), pytz.timezone('Asia/Shanghai')),
                    'size': result.get('fileSize'),
                    'seeders': result.get('peers').get('upload'),
                    'peers': result.get('peers').get('download'),
                    'grabs': result.get('finish'),
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
