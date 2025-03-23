import json
from lxml import etree

from app.helper.db_helper import DbHelper
from app.plugins.modules._autogenrss._base import _ISiteRssGenHandler
from app.utils.http_utils import RequestUtils
from app.utils.json_utils import JsonUtils
from app.utils.string_utils import StringUtils
from config import Config


class HDHome(_ISiteRssGenHandler):
    """
    HDHome
    """
    # 匹配的站点Url，每一个实现类都需要设置为自己的站点Url
    site_url = "hdhome.org"
    
    
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
        if not site_info:
            return ""
        site = site_info.get("name")
        site_url = site_info.get("signurl")
        site_cookie = site_info.get("cookie")
        ua = site_info.get("ua")
        headers = site_info.get("headers")
        if (not site_url or not site_cookie) and not headers:
            self.warn("未配置 %s 的Cookie或请求头，无法获取到RSS" % str(site))
            return ""
        if JsonUtils.is_valid_json(headers):
            headers = json.loads(headers)
        else:
            headers = {}
            
        home_url = StringUtils.get_base_url(site_url)
        rss_url = f"{home_url}/getrss.php"
        self.info(f"开始生成RSS站点：{site}")
        # rss参数
        data = {
            "inclbookmarked": "0",
            "itemcategory": "1",
            "itemsmalldescr": "1",
            "itemsize": "1",
            "showrows": "50",
            "search": "",
            "search_mode": "1",
            "exp": "180"
        }
        
        headers.update({'User-Agent': ua})
        html_res = RequestUtils(cookies=site_cookie,
                            headers=headers,
                            proxies=Config().get_proxies() if site_info.get("proxy") else None
                            ).post_res(url=rss_url, data=data)
        if not html_res or html_res.status_code != 200:
            self.error(f"生成RSS失败，请检查站点连通性")
            return False, f'【{site}】生成RSS失败，请检查站点连通性'

        if "login.php" in html_res.text:
            self.error(f"生成RSS失败，cookie失效")
            return False, f'【{site}】生成RSS失败，cookie失效'
                
        # 解析rss url
        gen_rss_url = self._parse_rss_link(html_res.text)
        self.debug(f"生成的rss: {gen_rss_url}")
        if gen_rss_url:
            #插入到数据库
            DbHelper().update_site_rssurl(site_info.get("id"), gen_rss_url)
        
            self.info(f"生成RSS成功")
            return True, f'【{site}】生成RSS成功'
        else:
            self.info(f"生成RSS失败")
            return True, f'【{site}生成RSS失败'
    
    @staticmethod
    def _parse_rss_link(html_text: str) -> str:
        if not html_text:
            return ''

        html = etree.HTML(html_text)
        return next((href for href in html.xpath('//a[contains(@href, "linktype=dl")]/@href')), '')
