"""
索引器客户端抽象基类

职责：定义所有索引器客户端必须实现的接口协议，
并提供基于 Torznab XML 的通用搜索默认实现。
所有业务逻辑（过滤、识别）已迁移到 app.indexer.core。
"""

import datetime
from abc import ABCMeta, abstractmethod
from typing import Any
from urllib.parse import quote

import defusedxml.minidom  # type: ignore[import-untyped]

import log
from app.db.repositories.download_repository import DownloadRepository
from app.domain.enums import ProgressKey, SearchType
from app.indexer.schema import IndexerConfigSchema
from app.infrastructure.http.client import HttpClient
from app.infrastructure.http.exceptions import HttpClientError
from app.utils import DomUtils, ExceptionUtils, StringUtils


class _IIndexClient(metaclass=ABCMeta):
    """
    索引器客户端抽象基类

    子类必须实现：
    - match()          : 判断是否匹配给定类型
    - get_status()     : 检查连通性
    - get_type()       : 获取索引器类型
    - get_client_id()  : 获取索引器ID
    - get_indexers()   : 获取可用站点列表

    search() 提供默认的 Torznab XML 解析实现，子类可重写。
    """

    client_id = ""
    client_type = ""
    client_name = "Indexer"
    config_schema: IndexerConfigSchema | None = None
    index_type = ""
    api_key = ""
    host = ""
    progress = None

    def __init__(self, progress=None, download_repo: DownloadRepository | None = None):
        self.progress = progress
        self.download_repo = download_repo

    @classmethod
    @abstractmethod
    def match(cls, ctype) -> Any:
        """匹配实例"""

    @abstractmethod
    def get_status(self) -> Any:
        """检查连通性"""

    @abstractmethod
    def get_type(self) -> Any:
        """获取类型"""

    @abstractmethod
    def get_client_id(self) -> Any:
        """获取索引器id"""

    @abstractmethod
    def get_indexers(self, check=True, indexer_id=None, public=True) -> Any:
        """获取索引站点列表"""

    def list(self, index_id, page=0, keyword=None) -> list | None:
        return None

    def is_enabled(self) -> bool:
        return True

    def search(self, order_seq, indexer, key_word, filter_args: dict, match_media, in_from: SearchType) -> Any:
        """
        默认搜索实现：基于 Torznab XML 协议

        子类可重写此方法来提供自定义搜索逻辑。
        返回原始搜索结果（dict 列表），不执行过滤或识别。
        """
        if not indexer or not key_word:
            return []
        if filter_args is None:
            filter_args = {}
        if filter_args.get("site") and indexer.name not in filter_args.get("site"):
            return []

        progress_key = ProgressKey.SubscribeSearch if in_from == SearchType.SUBSCRIBE else ProgressKey.Search
        start_time = datetime.datetime.now()
        log.info(f"[{self.index_type}]开始搜索Indexer：{indexer.name} ...")

        search_word = str(StringUtils.handler_special_chars(text=key_word, replace_word=" ", allow_space=True) or "")
        api_url = f"{indexer.domain}?apikey={self.api_key}&t=search&q={quote(search_word)}"
        result_array: list = []
        error_flag = False
        try:
            result_array = self._parse_torznabxml(api_url)
        except Exception as e:
            # HTTP 错误 / 超时 / 解析异常 → 计为失败
            error_flag = True
            log.warn(f"[{self.index_type}]{indexer.name} 搜索失败: {e}")

        seconds = round((datetime.datetime.now() - start_time).total_seconds(), 1)

        # 写入索引器统计（正常返回（含空结果）记 Y，请求/解析失败记 N）
        if self.download_repo:
            try:
                self.download_repo.insert_indexer_statistics(
                    indexer=indexer.name,
                    itype=self.client_type or self.client_id,
                    seconds=int(seconds),
                    result="N" if error_flag else "Y",
                )
            except Exception as e:
                log.warn(f"[Indexer]写入统计失败: {e!s}")

        if len(result_array) == 0:
            log.warn(f"[{self.index_type}]{indexer.name} 关键词 {key_word} 未搜索到数据")
            if self.progress:
                self.progress.update(ptype=progress_key, text=f"{indexer.name} 关键词 {key_word} 未搜索到数据")
            return []
        else:
            log.warn(f"[{self.index_type}]{indexer.name} 关键词 {key_word} 返回数据：{len(result_array)}")
            if self.progress:
                self.progress.update(
                    ptype=progress_key, text=f"{indexer.name} 关键词 {key_word} 返回 {len(result_array)} 条数据"
                )

        # 注入站点元信息
        for item in result_array:
            item["_indexer_name"] = indexer.name
            item["_indexer_order"] = order_seq
            item["_indexer_public"] = getattr(indexer, "public", False)
            item["_indexer_source"] = self.client_type or self.client_id

        return result_array

    @staticmethod
    def _parse_torznabxml(url):
        """解析 Torznab XML；HTTP 错误 / 超时 / 解析失败向上抛出（由调用方计为失败）"""
        ret_array = []
        if not url:
            return ret_array
        ret = HttpClient().get(url)
        if not ret:
            raise HttpClientError("Torznab 请求无响应")
        xml_doc = defusedxml.minidom.parseString(ret.text)
        items = xml_doc.getElementsByTagName("item")
        for item in items:
            try:
                title = DomUtils.tag_value(item, "title", default="")
                enclosure = DomUtils.tag_value(item, "enclosure", "url", default="")
                if not enclosure:
                    enclosure = DomUtils.tag_value(item, "link", default="")
                size = DomUtils.tag_value(item, "size", default=0)
                description = DomUtils.tag_value(item, "description", default="")
                seeders = 0
                peers = 0
                for node in item.getElementsByTagName("torznab:attr"):
                    if node.getAttribute("name") == "seeders":
                        seeders = node.getAttribute("value")
                    if node.getAttribute("name") == "peers":
                        peers = node.getAttribute("value")
                ret_array.append(
                    {
                        "title": title,
                        "enclosure": enclosure,
                        "description": description,
                        "size": size,
                        "seeders": seeders,
                        "peers": peers,
                    }
                )
            except Exception as e:
                ExceptionUtils.exception_traceback(e)
                continue
        return ret_array
