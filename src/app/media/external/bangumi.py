import urllib.parse
from datetime import datetime

import log
from app.core.settings import settings
from app.domain import media_metadata
from app.domain.mediatypes import MediaType
from app.infrastructure.cache_system import lru_cache_with_ttl
from app.infrastructure.http.client import HttpClient
from app.infrastructure.http.config import HttpClientConfig
from app.utils.config_tools import get_proxies


def _proxy_url_from_settings() -> str | None:
    """从全局配置读取代理地址（api.bgm.tv 为境外服务，需走代理）。"""
    proxies = get_proxies() or {}
    if isinstance(proxies, dict):
        return proxies.get("http") or proxies.get("https")
    return None


class Bangumi:
    """
    https://bangumi.github.io/api/
    """

    _urls = {
        "calendar": "calendar",
        "detail": "v0/subjects/%s",
        "relations": "v0/subjects/%s/subjects",
    }
    _base_url = "https://api.bgm.tv/"
    _page_num = 30

    def __init__(self):
        pass

    @classmethod
    @lru_cache_with_ttl(maxsize=128, ttl=3600)
    def __invoke(cls, url, **kwargs):
        req_url = cls._base_url + url
        params = {}
        if kwargs:
            params.update(kwargs)
        resp = HttpClient(config=HttpClientConfig(proxy_url=_proxy_url_from_settings(), timeout=10)).get(
            url=req_url, params=params
        )
        return resp.json()

    def calendar(self):
        """
        获取每日放送
        """
        return self.__invoke(self._urls["calendar"], _ts=datetime.strftime(datetime.now(), "%Y%m%d"))

    def detail(self, bid):
        """
        获取番剧详情
        """
        return self.__invoke(self._urls["detail"] % bid, _ts=datetime.strftime(datetime.now(), "%Y%m%d"))

    def relations(self, bid) -> list:
        """
        获取番剧系列关系（续作/前传/衍生/番外）
        返回 [{id, name, name_cn, relation, type}]，失败返回 []
        """
        try:
            data = self.__invoke(self._urls["relations"] % bid, _ts=datetime.strftime(datetime.now(), "%Y%m%d"))
            return data if isinstance(data, list) else []
        except Exception as e:
            log.debug(f"获取Bangumi关系失败: {bid}, {e}")
            return []

    @staticmethod
    def __dict_item(item, weekday):
        """
        转换为字典
        """
        bid = item.get("id")
        detail = item.get("url")
        title = item.get("name_cn") or item.get("name")
        air_date = item.get("air_date")
        rating = item.get("rating")
        if rating:
            score = rating.get("score")
        else:
            score = 0
        images = item.get("images")
        if images:
            image = images.get("large")
        else:
            image = ""
        # 转换为代理URL格式
        if image:
            try:
                if settings.get("app").get("enable_image_proxy", True):
                    image = f"/img/bgm/{urllib.parse.quote(image, safe='')}"
            except Exception as e:  # noqa: BLE001
                log.debug(f"[Bangumi]忽略异常: {e}")
        summary = item.get("summary")
        return {
            "id": f"BG:{bid}",
            "orgid": bid,
            "title": title,
            "year": air_date[:4] if air_date else "",
            "type": "tv",
            "media_type": MediaType.TV.value,
            "vote": score,
            "image": image,
            "overview": summary,
            "url": detail,
            "weekday": weekday,
            "genres": media_metadata.normalize_genres(["动画"]),
            "countries": media_metadata.normalize_countries(["jp"]),
            "languages": media_metadata.normalize_languages(["ja"]),
        }

    def get_bangumi_calendar(self, page=1, week=None):
        """
        获取每日放送
        """
        infos = self.calendar()
        if not infos:
            return []
        start_pos = (int(page) - 1) * self._page_num
        ret_list = []
        pos = 0
        for info in infos:
            weeknum = info.get("weekday", {}).get("id")
            if week and int(weeknum) != int(week):
                continue
            weekday = info.get("weekday", {}).get("cn")
            items = info.get("items")
            for item in items:
                if pos >= start_pos:
                    ret_list.append(self.__dict_item(item, weekday))
                pos += 1
                if pos >= start_pos + self._page_num:
                    break

        return ret_list
