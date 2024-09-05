from copy import deepcopy
import re
import json

from app.utils.string_utils import StringUtils
from app.utils.types import MediaType
import log
from app.utils import RequestUtils, JsonUtils
from config import Config
from lxml import etree


class FireFlySpider(object):
    _indexerid = None
    _domain = None
    _name = ""
    _proxy = None
    _cookie = None
    _ua = None
    _size = 100
    _searchurl = "%sp_torrent/video_list_g.php?cat=%s&search=%s&area=name&column=g_last_upload_date&sort=desc&btn_search=搜索"
    _pageurl = "%sp_torrent/video_detail.php?tid=%s"

    def __init__(self, indexer):
        if indexer:
            self._indexerid = indexer.id
            self._visit_domain = indexer.domain
            self._name = indexer.name
            if indexer.proxy:
                self._proxy = Config().get_proxies()
            self._cookie = indexer.cookie
            self._ua = indexer.ua
            if JsonUtils.is_valid_json(indexer.headers):
                self._headers = json.loads(indexer.headers)
            else:
                self._headers = {}
        self.init_config()

    def init_config(self):
        self._size = Config().get_config('pt').get('site_search_result_num') or 100

    def search(self, keyword="", mtype: MediaType = None, page=0):

        if mtype == MediaType.MOVIE:
            cat = "mo"
        elif mtype == MediaType.TV:
            cat = "tv"
        elif mtype == MediaType.ANIME:
            cat = "an"
        else:
            cat = ""
        if not keyword:
            searchurl = f"{self._visit_domain}p_torrent/video_list_g.php?page={int(page) + 1}"
        else:
            searchurl = self._searchurl % (self._visit_domain, cat, keyword)
        self._headers.update({
                "Content-Type": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8,application/signed-exchange;v=b3;q=0.7",
                "User-Agent": f"{self._ua}"
            })
        res = RequestUtils(
            headers=self._headers,
            proxies=self._proxy,
            cookies=self._cookie,
            timeout=30
        ).get_res(url=searchurl)
        torrents = []
        if res and res.status_code == 200:
            html_text = res.text
            html_doc = etree.HTML(html_text)

            media_items = html_doc.xpath('//table[contains(@class, "gm_table")]')
            for item in media_items:
                item_tmp = deepcopy(item)
                imdbid = (re.findall(r'tt\d+', (item_tmp.xpath('//*[@id="gm_td_title"]/a[contains(@href, "imdb")]/@href') or [''])[0]) or [''])[0]
                description = (item_tmp.xpath('//*[@id="gm_td_title"]/div[@id="gm_div_title"]/text()') or [''])[0]
                for media in item_tmp.xpath('//tr[@id="gm_tr_item"]'):
                    media_tmp = deepcopy(media)
                    discount = media_tmp.xpath('//span[@id="free"]')
                    if discount:
                        downloadvolumefactor = 0
                    else:
                        downloadvolumefactor = 1.0
                    id = (re.findall(r'tid=(\d+)', (media_tmp.xpath('//div[@id="gm_div_name"]/a/@href') or [''])[0]) or [''])[0]
                    title = (media_tmp.xpath('//div[@id="gm_div_name"]/a/text()') or [''])[0]
                    labels = '|'.join(media_tmp.xpath('//span[@class="tag"]/text()'))
                    enclosure = (media_tmp.xpath('//td[@id="gm_td_icon"]/div/a[contains(@href, "download")]/@href') or [''])[0].replace('../', self._visit_domain)
                    pubdate = (media_tmp.xpath('//td[@id="gm_td_user"]/text()') or [''])[0]
                    size_tmp = (media_tmp.xpath('//td[@id="gm_td_size"]/text()') or ['0'])[0]
                    size = StringUtils.num_filesize(f'{size_tmp}B')
                    seeders = (media_tmp.xpath('//span[@id="user_info" and a/img[contains(@title, "做种数")]]/a/text()') or ['0'])[0].strip()
                    peers = (media_tmp.xpath('//span[@id="user_info" and a/img[contains(@title, "下载数")]]/a/text()') or ['0'])[0].strip()

                    torrent = {
                        'indexer': self._indexerid,
                        'title': title,
                        'description': description,
                        'labels': labels,
                        'enclosure': enclosure,
                        'pubdate': pubdate,
                        'size': size,
                        'seeders': seeders,
                        'peers': peers,
                        'grabs': '',
                        'downloadvolumefactor': downloadvolumefactor,
                        'uploadvolumefactor': 1.0,
                        'page_url': self._pageurl %(self._visit_domain, id),
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
