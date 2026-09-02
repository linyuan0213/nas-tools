import datetime
from urllib.parse import quote

import log
from app.domain.enums import ProgressKey, SearchType
from app.indexer.client._base import _IIndexClient
from app.indexer.configuration import IndexerConf
from app.indexer.schema import ConfigField, IndexerConfigSchema
from app.infrastructure.http.client import HttpClient
from app.utils import ExceptionUtils, StringUtils


class Jackett(_IIndexClient):
    schema = "jackett"
    index_type = "Jackett"
    client_id = "jackett"
    client_type = "jackett"
    client_name = "Jackett"
    config_schema = IndexerConfigSchema(
        name="Jackett",
        icon_url="/static/img/indexer/jackett.png",
        fields=[
            ConfigField(
                id="host",
                required=True,
                title="Jackett地址",
                tooltip="Jackett访问地址和端口，如为https需加https://前缀。注意需要先在Jackett中添加indexer，才能正常测试通过和使用",
                type="text",
                placeholder="http://127.0.0.1:9117",
            ),
            ConfigField(
                id="api_key",
                required=True,
                title="Api Key",
                tooltip="Jackett管理界面右上角复制API Key",
                type="text",
                placeholder="",
            ),
            ConfigField(
                id="password",
                required=False,
                title="密码",
                tooltip="Jackett管理界面中配置的Admin password，如未配置可为空",
                type="password",
                placeholder="",
            ),
        ],
    )

    def __init__(self, config=None, **kwargs):
        super().__init__(**kwargs)
        self._client_config = config or {}
        self._password = None
        self._refresh()

    def _refresh(self):
        if self._client_config:
            self.api_key = self._client_config.get("api_key")
            self._password = self._client_config.get("password")
            self.host = self._client_config.get("host")
            if self.host:
                if not self.host.startswith("http"):
                    self.host = "http://" + self.host
                if not self.host.endswith("/"):
                    self.host = self.host + "/"

    def get_type(self):
        return self.client_type

    def get_client_id(self):
        return self.client_id

    def get_status(self):
        """
        检查连通性
        :return: True、False
        """
        if not self.api_key or not self.host:
            return False
        return bool(self.get_indexers())

    @classmethod
    def match(cls, ctype):
        return ctype in [cls.schema, cls.index_type]

    def get_indexers(self, check=True, indexer_id=None, public=True):
        """
        获取配置的jackett indexer
        :return: indexer 信息 [(indexerId, indexerName, url)]
        """
        indexer_query_url = f"{self.host}api/v2.0/indexers?configured=true"
        try:
            client = HttpClient()
            client.post(url=f"{self.host}UI/Dashboard", data={"password": self._password})
            ret = client.get(indexer_query_url)
            return [
                IndexerConf(
                    datas={
                        "id": v["id"],
                        "name": v["name"],
                        "domain": f"{self.host}api/v2.0/indexers/{v['id']}/results/torznab/api",
                    },
                    public=v["type"] in ("public", "semi-private"),
                    builtin=False,
                )
                for v in ret.json()
            ]
        except Exception as e2:
            ExceptionUtils.exception_traceback(e2)
            return []

    def list(self, index_id, page=0, page_size=100, keyword=None):
        if not index_id:
            return None
        start_time = datetime.datetime.now()
        indexers = self.get_indexers()
        matched = [i for i in indexers if str(i.id) == str(index_id) or i.name == index_id]
        if not matched:
            return None
        tracker_id = matched[0].id
        api_url = f"{self.host}api/v2.0/indexers/all/results?apikey={self.api_key}"
        if keyword:
            api_url += f"&Query={quote(keyword)}"
        api_url += f"&Tracker[]={quote(str(tracker_id))}"
        result_array: list = []
        error_flag = False
        try:
            ret = HttpClient().get(api_url)
            if ret:
                data = ret.json()
                results = data.get("Results", [])
                page_size = 20
                start = page * page_size
                items = results[start : start + page_size]
                result_array = [
                    {
                        "title": r.get("Title", ""),
                        "enclosure": r.get("Link") or r.get("MagnetUri") or "",
                        "description": r.get("Details", ""),
                        "page_url": r.get("Details", ""),
                        "size": r.get("Size", 0),
                        "seeders": r.get("Seeders", 0),
                        "peers": r.get("Peers", 0),
                        "uploadvolumefactor": r.get("UploadVolumeFactor"),
                        "downloadvolumefactor": r.get("DownloadVolumeFactor"),
                        "indexer": str(tracker_id),
                    }
                    for r in items
                ]
            else:
                error_flag = True
        except Exception as e2:
            error_flag = True
            ExceptionUtils.exception_traceback(e2)
        seconds = round((datetime.datetime.now() - start_time).total_seconds(), 1)
        if self.download_repo:
            try:
                self.download_repo.insert_indexer_statistics(
                    indexer=str(tracker_id),
                    itype=self.client_type or self.client_id,
                    seconds=int(seconds),
                    result="N" if error_flag else "Y",
                )
            except Exception as e:
                log.warn(f"[Jackett]写入统计失败: {e!s}")
        return result_array

    def search(self, order_seq, indexer, key_word, filter_args, match_media, in_from):
        if not indexer or not key_word:
            return []
        if filter_args is None:
            filter_args = {}
        if filter_args.get("site") and indexer.name not in filter_args.get("site"):
            return []
        progress_key = ProgressKey.SubscribeSearch if in_from == SearchType.SUBSCRIBE else ProgressKey.Search
        start_time = datetime.datetime.now()
        log.info(f"[Jackett]开始搜索Indexer: {indexer.name} ...")
        search_word = str(StringUtils.handler_special_chars(text=key_word, replace_word=" ", allow_space=True) or "")
        api_url = (
            f"{self.host}api/v2.0/indexers/all/results"
            f"?apikey={self.api_key}"
            f"&Query={quote(search_word)}"
            f"&Tracker[]={quote(str(indexer.id))}"
        )
        result_array: list = []
        error_flag = False
        try:
            ret = HttpClient().get(api_url)
            if ret:
                data = ret.json()
                results = data.get("Results", [])
                result_array = [
                    {
                        "title": r.get("Title", ""),
                        "enclosure": r.get("Link") or r.get("MagnetUri") or "",
                        "description": r.get("Details", ""),
                        "page_url": r.get("Details", ""),
                        "size": r.get("Size", 0),
                        "seeders": r.get("Seeders", 0),
                        "peers": r.get("Peers", 0),
                        "uploadvolumefactor": r.get("UploadVolumeFactor"),
                        "downloadvolumefactor": r.get("DownloadVolumeFactor"),
                    }
                    for r in results
                ]
            else:
                error_flag = True
        except Exception as e2:
            error_flag = True
            ExceptionUtils.exception_traceback(e2)
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
            log.debug(f"[Jackett]{indexer.name} 关键词 {key_word} 未搜索到数据")
            if self.progress:
                self.progress.update(ptype=progress_key, text=f"{indexer.name} 关键词 {key_word} 未搜索到数据")
            return []
        log.warn(f"[Jackett]{indexer.name} 关键词 {key_word} 返回数据：{len(result_array)}")
        if self.progress:
            self.progress.update(
                ptype=progress_key,
                text=f"{indexer.name} 关键词 {key_word} 返回 {len(result_array)} 条数据",
            )
        for item in result_array:
            item["_indexer_name"] = indexer.name
            item["_indexer_order"] = order_seq
            item["_indexer_public"] = getattr(indexer, "public", False)
            item["_indexer_source"] = self.client_type or self.client_id
        return result_array
