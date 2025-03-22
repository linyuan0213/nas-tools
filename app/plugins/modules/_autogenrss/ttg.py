from urllib.parse import urlencode
from lxml import etree

from app.helper.db_helper import DbHelper
from app.plugins.modules._autogenrss._base import _ISiteRssGenHandler
from app.utils.http_utils import RequestUtils
from app.utils.string_utils import StringUtils
from config import Config


class TTG(_ISiteRssGenHandler):
    """
    TTG
    """
    # 匹配的站点Url，每一个实现类都需要设置为自己的站点Url
    site_url = "totheglory.im"
    
    
    @classmethod
    def match(cls, url):
        """
        根据站点Url判断是否匹配当前站点签到类，大部分情况使用默认实现即可
        :param url: 站点Url
        :return: 是否匹配，如匹配则会调用该类的gen_rss方法
        """
        return True if StringUtils.url_equal(url, cls.site_url) else False
    
    def gen_rss(self, site_info: dict):
        """
        执行RSS生成
        :param site_info: 站点信息，含有站点Url、站点Cookie、UA等信息
        :return: 签到结果信息
        """
        site = site_info.get("name")
        site_cookie = site_info.get("cookie")
        ua = site_info.get("ua")
        proxy = Config().get_proxies() if site_info.get("proxy") else None

        params = {
            "c47": "47",
            "c28": "28",
            "c45": "45",
            "c49": "49",
            "c5": "5",
            "c105": "105",
            "c26": "26",
            "c104": "104",
            "c29": "29",
            "c46": "46",
            "c107": "107",
            "c110": "110",
            "c44": "44",
            "c106": "106",
            "c27": "27",
            "c43": "43",
            "c48": "48",
            "c33": "33",
            "c30": "30",
            "c31": "31",
            "c51": "51",
            "c52": "52",
            "c53": "53",
            "c54": "54",
            "c108": "108",
            "c109": "109",
            "c62": "62",
            "c63": "63",
            "c67": "67",
            "c69": "69",
            "c70": "70",
            "c73": "73",
            "c76": "76",
            "c75": "75",
            "c74": "74",
            "c87": "87",
            "c88": "88",
            "c99": "99",
            "c90": "90",
            "c77": "77",
            "c32": "32",
            "c56": "56",
            "c82": "82",
            "c83": "83",
            "c59": "59",
            "c57": "57",
            "c58": "58",
            "c103": "103",
            "c101": "101",
            "c60": "60",
            "c91": "91",
            "c84": "84",
            "c92": "92",
            "c93": "93",
            "c94": "94",
            "c95": "95",
            "c111": "111"
        }
        # 获取页面html
        html_res = RequestUtils(cookies=site_cookie,
                                headers=ua,
                                proxies=proxy
                                ).get_res(url="https://totheglory.im/rsstools.php", params=params)
        if not html_res or html_res.status_code != 200:
            self.error(f"生成RSS失败，请检查站点连通性")
            return False, f'【{site}】生成RSS失败，请检查站点连通性'

        if "login.php" in html_res.text:
            self.error(f"生成RSS失败，cookie失效")
            return False, f'【{site}】生成RSS失败，cookie失效'
     
        rss_link = self._get_link(html_res.text)
        self.debug(f"生成的rss: {rss_link}")
        
        if rss_link:
            DbHelper().update_site_rssurl(site_info.get('id'), rss_link)
            self.info(f"生成RSS成功")
            return True, f'【{site}】生成RSS成功'
        else:
            self.info(f"生成RSS失败")
            return True, f'【{site}生成RSS失败'
    
    @staticmethod
    def _get_link(html_text: str) -> str:
        if not html_text:
            return ''

        html = etree.HTML(html_text)
        return next((href for href in html.xpath('//textarea[@id="trss"]/text()')), '')
