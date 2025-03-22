import json
from lxml import etree

from app.helper.db_helper import DbHelper
from app.plugins.modules._autogenrss._base import _ISiteRssGenHandler
from app.utils.http_utils import RequestUtils
from app.utils.string_utils import StringUtils
from config import Config


class ZhuQue(_ISiteRssGenHandler):
    """
    朱雀
    """
    # 匹配的站点Url，每一个实现类都需要设置为自己的站点Url
    site_url = "zhuque.in"
    
    
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

        # 获取页面html
        html_res = RequestUtils(cookies=site_cookie,
                                headers=ua,
                                proxies=proxy
                                ).get_res(url="https://zhuque.in")
        if not html_res or html_res.status_code != 200:
            self.error(f"生成RSS失败，请检查站点连通性")
            return False, f'【{site}】生成RSS失败，请检查站点连通性'

        if "login.php" in html_res.text:
            self.error(f"生成RSS失败，cookie失效")
            return False, f'【{site}】生成RSS失败，cookie失效'

        html = etree.HTML(html_res.text)

        if not html:
            return False, f'【{site}】生成RSS失败'

        x_csrf_token = html.xpath("//meta[@name='x-csrf-token']/@content")[0]
        if x_csrf_token:
            headers = {
                "x-csrf-token": str(x_csrf_token),
                "Content-Type": "application/json; charset=utf-8",
                "User-Agent": ua
            }
            security_res = RequestUtils(cookies=site_cookie,
                                     headers=headers,
                                     proxies=proxy
                                     ).get_res(url="https://zhuque.in/api/user/getSecurityInfo")
            if not security_res or security_res.status_code != 200:
                self.error(f"生成RSS失败")
            
        rss_link = ""
        json_data = security_res.json()
        if json_data.get("status") == 200:
            rss_key = json_data.get("data").get("rssKey")
            torrent_key = json_data.get("data").get("torrentKey")
            rss_link = f"https://zhuque.in/api/torrent/rss/{rss_key}/{torrent_key}"
            self.debug(f"生成的rss: {rss_link}")
    
            DbHelper().update_site_rssurl(site_info.get('id'), rss_link)
            self.info(f"生成RSS成功")
            return True, f'【{site}】生成RSS成功'
        else:
            self.info(f"生成RSS失败")
            return True, f'【{site}生成RSS失败'
