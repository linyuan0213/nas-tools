from lxml import etree

from app.helper.db_helper import DbHelper
from app.plugins.modules._autogenrss._base import _ISiteRssGenHandler
from app.utils.http_utils import RequestUtils
from app.utils.string_utils import StringUtils
from config import Config


class Ourbits(_ISiteRssGenHandler):
    """
    star-space
    """
    # 匹配的站点Url，每一个实现类都需要设置为自己的站点Url
    site_url = "star-space.net"
    
    
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
        :return: rss生成结果信息
        """
        site = site_info.get("name")
        site_cookie = site_info.get("cookie")
        ua = site_info.get("ua")
        proxy = Config().get_proxies() if site_info.get("proxy") else None

        # 获取页面html
        html_res = RequestUtils(cookies=site_cookie,
                                headers=ua,
                                proxies=proxy
                                ).get_res(url="https://star-space.net/p_rss/rss_create.php")
        if not html_res or html_res.status_code != 200:
            self.error(f"生成RSS失败，请检查站点连通性")
            return False, f'【{site}】生成RSS失败，请检查站点连通性'

        if "login_act.php" in html_res.text:
            self.error(f"生成RSS失败，cookie失效")
            return False, f'【{site}】生成RSS失败，cookie失效'
        rss_link = self._get_rss_link(html_res.text)
        
        # 如果rss链接不存在，重新生成一个
        if not rss_link:
            data = {
                "cat": "",
                "media": "",
                "btn_add": "创建RSS"
            }
            headers = {
                "accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8,application/signed-exchange;v=b3;q=0.7",
                "accept-language": "zh-CN,zh;q=0.9,en;q=0.8,ja;q=0.7",
                "content-type": "application/x-www-form-urlencoded",
                "origin": "https://star-space.net",
                "referer": "https://star-space.net/p_rss/rss_create.php",
                "user-agent": ua
            }
            html_res = RequestUtils(cookies=site_cookie,
                        headers=headers,
                        proxies=proxy
                        ).post_res(url="https://star-space.net/p_rss/rss_act.php", data=data)
            if "操作成功" in html_res.text:
                html_res = RequestUtils(cookies=site_cookie,
                        headers=ua,
                        proxies=proxy
                        ).get_res(url="https://star-space.net/p_rss/rss_create.php")
                if not html_res or html_res.status_code != 200:
                    self.error(f"生成RSS失败，请检查站点连通性")
                    return False, f'【{site}】生成RSS失败，请检查站点连通性'
                rss_link = self._get_rss_link(html_res.text)
        self.debug(f"生成的rss: {rss_link}")
        
        if rss_link:
            DbHelper().update_site_rssurl(site_info.get('id'), rss_link)
            self.info(f"生成RSS成功")
            return True, f'【{site}】生成RSS成功'
        else:
            self.info(f"生成RSS失败")
            return True, f'【{site}生成RSS失败'
    
    @staticmethod
    def _get_rss_link(html_text: str) -> str:
        if not html_text:
            return ''
        html = etree.HTML(html_text)
        return next((href for href in html.xpath('//a[contains(@href, "rss.php?key=")]/@href')), '')
