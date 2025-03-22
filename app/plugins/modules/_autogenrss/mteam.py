import json

from app.helper.db_helper import DbHelper
from app.plugins.modules._autogenrss._base import _ISiteRssGenHandler
from app.utils.http_utils import RequestUtils
from config import MT_URL, Config


class Mteam(_ISiteRssGenHandler):
    """
    m-team
    """
    # 匹配的站点Url，每一个实现类都需要设置为自己的站点Url
    site_url = "m-team"
    
    
    @classmethod
    def match(cls, url):
        """
        根据站点Url判断是否匹配当前站点签到类，大部分情况使用默认实现即可
        :param url: 站点Url
        :return: 是否匹配，如匹配则会调用该类的gen_rss方法
        """
        return True if cls.site_url in url else False
    
    def gen_rss(self, site_info: dict):
        """
        执行RSS生成
        :param site_info: 站点信息，含有站点Url、站点Cookie、UA等信息
        :return: 签到结果信息
        """
        site = site_info.get("name")
        ua = site_info.get("ua")
        headers = json.loads(site_info.get("headers"))
        headers.update({
            "contentType": 'application/json;charset=UTF-8',
            "User-Agent": ua
        })
        
        if headers and headers.get("authorization"):
            headers.pop('authorization')

        proxy = Config().get_proxies() if site_info.get("proxy") else None
        
        rss_url = f"{MT_URL}/api/rss/genlink"
        data = {
            "labels": 0,
            "tkeys": [
                "ttitle",
                "tcat",
                "tsmalldescr",
                "tsize"
            ],
            "pageSize": 50
        }
        data = json.dumps(data, separators=(',', ':'))

        res = RequestUtils(
            headers=headers,
            proxies=proxy
        ).post_res(url=rss_url, data=data)
        if not res or res.status_code != 200:
            self.error(f"生成RSS失败，请检查站点连通性")

        rss_link = ""
        json_data = res.json()
        if json_data.get("message") == "SUCCESS":
            rss_link = json_data.get("data").get("dlUrl")
            self.debug(f"生成的rss: {rss_link}")
        
        if rss_link:
            DbHelper().update_site_rssurl(site_info.get('id'), rss_link)
            self.info(f"生成RSS成功")
            return True, f'【{site}】生成RSS成功'
        else:
            self.info(f"生成RSS失败")
            return True, f'【{site}生成RSS失败'
