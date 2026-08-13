import re
from urllib.parse import urlsplit

import defusedxml.minidom  # type: ignore[import-untyped]

import log
from app.db.repositories.subscribe_torrent_repo_adapter import SubscribeTorrentRepositoryAdapter
from app.infrastructure.cache_system import get_cache_manager
from app.infrastructure.http.client import HttpClient
from app.infrastructure.http.config import HttpClientConfig
from app.services.rss_automation.rsstitle_utils import RssTitleUtils
from app.sites.engine import SiteEngine
from app.utils import DomUtils, ExceptionUtils, StringUtils
from app.utils.config_tools import get_proxies, get_ua


class RssHelper:
    """RSS 解析助手"""

    def __init__(
        self,
        site_engine: SiteEngine,
        repo: SubscribeTorrentRepositoryAdapter | None = None,
        cache_ttl: int = 60,
    ):
        self._repo = repo or SubscribeTorrentRepositoryAdapter()
        self._site_engine = site_engine
        self._cache = get_cache_manager().get_or_create(
            "rss_processor", cache_type="memory", maxsize=200, ttl=cache_ttl
        )
        self._cache_ttl = cache_ttl

    def _cache_key(self, url: str, proxy: bool) -> str:
        return f"rss:{url}:proxy={proxy}"

    @staticmethod
    def _looks_like_torrent_url(url: str) -> bool:
        """判断链接是否为种子直链（而非详情页/公告页），用于仅 link 无 enclosure 的 RSS 回退"""
        if not url:
            return False
        parsed = urlsplit(url)
        path = (parsed.path or "").lower()
        query = (parsed.query or "").lower()
        if path.endswith(".torrent"):
            return True
        if any(k in path for k in ("download", "/dl", "torrents", "torrent/")):
            return True
        if any(k in query for k in ("passkey=", "authkey=", "torrent_pass=")):
            return True
        return False

    def parse_rssxml(self, url, proxy=False):
        """
        解析RSS订阅URL，获取RSS中的种子信息
        :param url: RSS地址
        :param proxy: 是否使用代理
        :return: 种子信息列表，如为None代表Rss过期
        """
        _special_title_sites = {"pt.keepfrds.com": RssTitleUtils.keepfriends_title}

        _rss_expired_msg = ["RSS 链接已过期, 您需要获得一个新的!", "RSS Link has expired, You need to get a new one!"]

        # 开始处理
        if not url:
            return []
        cache_key = self._cache_key(url, proxy)
        cached = self._cache.get(cache_key)
        if cached is not None:
            return cached

        ret_array = []
        site_domain = StringUtils.get_url_domain(url)
        try:
            headers = {
                "Accept": (
                    "application/xml;q=0.9,image/avif,image/webp,image/apng,"
                    "*/*;q=0.8,application/signed-exchange;v=b3;q=0.7"
                ),
                "User-Agent": get_ua(),
            }
            proxies = get_proxies() if proxy else None
            proxy_url = proxies.get("http") if proxies else None
            rate_limiter = getattr(self._site_engine, "site_limiter", None)
            rate_limiter_engine = rate_limiter.engine if rate_limiter else None
            ret = HttpClient(
                config=HttpClientConfig(proxy_url=proxy_url, default_headers=headers),
                rate_limiter=rate_limiter_engine,
            ).get(url)
        except Exception as e2:
            ExceptionUtils.exception_traceback(e2)
            return []
        if ret:
            ret_xml = ret.text
            # 检查返回内容是否为 RSS/XML
            xml_start = ret_xml.strip()[:100].lower()
            if not ret_xml or not (
                xml_start.startswith("<?xml")
                or xml_start.startswith("<rss")
                or xml_start.startswith("<feed")
                or xml_start.startswith("<channel")
            ):
                log.warn(f"RSS 返回非 XML 内容 ({url[:80]}...): {ret_xml[:500]}")
                return []
            # 清理非法 XML 字符（控制字符）
            ret_xml = re.sub(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]", "", ret_xml)
            try:
                # 解析XML
                dom_tree = defusedxml.minidom.parseString(ret_xml)
                root_node = dom_tree.documentElement
                if not root_node:
                    return []
                items = root_node.getElementsByTagName("item")
                for item in items:
                    try:
                        # 标题
                        title = DomUtils.tag_value(item, "title", default="")
                        if not title:
                            continue
                        # 标题特殊处理
                        if site_domain and site_domain in _special_title_sites:
                            handler = _special_title_sites.get(site_domain)
                            if handler:
                                title = handler(title)
                        # 描述
                        description = DomUtils.tag_value(item, "description", default="")
                        # 种子页面
                        link = DomUtils.tag_value(item, "link", default="")
                        # 种子链接
                        enclosure = DomUtils.tag_value(item, "enclosure", "url", default="")

                        if not enclosure and not link:
                            continue
                        # 部分RSS只有link没有enclosure：仅当 link 为种子直链时作为下载链接；
                        # 公告/提醒类条目（无 enclosure、link 为详情/公告页）直接跳过
                        if not enclosure and link:
                            if not self._looks_like_torrent_url(link):
                                continue
                            enclosure = link
                            link = None

                        # monika rss兼容
                        if enclosure and "monikadesign" in enclosure:
                            tids = re.findall(r"(\d+)\.", enclosure)
                            if tids:
                                split_url = urlsplit(enclosure)
                                link = f"{split_url.scheme}://{split_url.netloc}/torrents/{tids[0]}"
                        # 大小
                        size = DomUtils.tag_value(item, "enclosure", "length", default=0)
                        if size == 0:
                            size = StringUtils.num_filesize(DomUtils.tag_value(item, "torrent:size", default=0))
                        if size and str(size).isdigit():
                            size = int(size)
                        else:
                            size = 0
                        # 发布日期
                        pubdate = DomUtils.tag_value(item, "pubDate", default="")
                        if pubdate:
                            # 转换为时间
                            pubdate = StringUtils.get_time_stamp(pubdate)
                        # 返回对象
                        category = DomUtils.tag_value(item, "category", default="")
                        tmp_dict = {
                            "title": title,
                            "enclosure": enclosure,
                            "size": size,
                            "description": description,
                            "link": link,
                            "pubdate": pubdate,
                            "category": category,
                        }
                        ret_array.append(tmp_dict)
                    except Exception as e1:
                        ExceptionUtils.exception_traceback(e1)
                        continue
            except Exception as e2:
                # RSS过期 观众RSS 链接已过期，您需要获得一个新的！
                # pthome RSS Link has expired, You need to get a new one!
                if ret_xml in _rss_expired_msg:
                    return None
                ExceptionUtils.exception_traceback(e2)
        self._cache.set(cache_key, ret_array, ttl=self._cache_ttl)
        return ret_array

    def insert_rss_torrents(self, media_info):
        """
        将RSS的记录插入数据库
        """
        enclosure = media_info.enclosure
        if enclosure and len(enclosure) > 8192:
            enclosure = enclosure[:8192]
        self._repo.insert(
            torrent_name=media_info.org_string,
            enclosure=enclosure,
            type_=media_info.type.value,
            title=media_info.title,
            year=media_info.year,
            season=media_info.get_season_string(),
            episode=media_info.get_episode_string(),
        )

    def is_rssd_by_enclosure(self, enclosure):
        """
        查询RSS是否处理过，根据下载链接
        """
        if not enclosure:
            return True
        return self._repo.is_exists_by_enclosure(enclosure)

    def is_rssd_by_simple(self, torrent_name, enclosure):
        """
        查询RSS是否处理过，根据名称或下载链接
        """
        if not torrent_name and not enclosure:
            return True
        return self._repo.is_exists_by_name(torrent_name, enclosure)

    def simple_insert_rss_torrents(self, title, enclosure):
        """
        将RSS的记录插入数据库（简式）
        """
        self._repo.simple_insert(title, enclosure)

    def simple_delete_rss_torrents(self, title, enclosure=None):
        """
        删除RSS的记录
        """
        self._repo.simple_delete(title, enclosure)

    def truncate_rss_history(self):
        """
        清空RSS历史记录
        """
        self._repo.truncate()
