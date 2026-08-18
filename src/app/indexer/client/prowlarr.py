import datetime
from urllib.parse import quote

import log
from app.indexer.client._base import _IIndexClient
from app.indexer.configuration import IndexerConf
from app.indexer.schema import ConfigField, IndexerConfigSchema
from app.infrastructure.http.client import HttpClient
from app.utils import ExceptionUtils


class Prowlarr(_IIndexClient):
    schema = "prowlarr"
    index_type = "Prowlarr"
    client_id = "prowlarr"
    client_type = "prowlarr"
    client_name = "Prowlarr"
    config_schema = IndexerConfigSchema(
        name="Prowlarr",
        icon_url="/static/img/indexer/prowlarr.png",
        fields=[
            ConfigField(
                id="host",
                required=True,
                title="Prowlarr地址",
                tooltip="Prowlarr访问地址和端口，如为https需加https://前缀。注意需要先在Prowlarr中添加搜刮器，同时勾选所有搜刮器后搜索一次，才能正常测试通过和使用",
                type="text",
                placeholder="http://127.0.0.1:9696",
            ),
            ConfigField(
                id="api_key",
                required=True,
                title="Api Key",
                tooltip="在Prowlarr->Settings->General->Security-> API Key中获取",
                type="text",
                placeholder="",
            ),
        ],
    )

    def __init__(self, config=None, **kwargs):
        super().__init__(**kwargs)
        self._client_config = config or {}
        self._refresh()

    def _refresh(self):
        if self._client_config:
            self.api_key = self._client_config.get("api_key")
            self.host = self._client_config.get("host")
            if self.host:
                if not self.host.startswith("http"):
                    self.host = "http://" + self.host
                if not self.host.endswith("/"):
                    self.host = self.host + "/"

    @classmethod
    def match(cls, ctype):
        return ctype in [cls.schema, cls.index_type]

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

    def get_indexers(self, check=True, indexer_id=None, public=True):
        """
        获取配置的prowlarr indexer
        :return: indexer 信息 [(indexerId, indexerName, url)]
        """
        indexer_query_url = f"{self.host}api/v1/indexer?apikey={self.api_key}"
        try:
            ret = HttpClient().get(indexer_query_url)
        except Exception as e2:
            ExceptionUtils.exception_traceback(e2)
            return []
        indexers = ret.json()
        return [
            IndexerConf(
                {
                    "id": v.get("id"),
                    "name": v.get("name"),
                    "domain": f"{self.host}{v.get('id')}/api",
                },
                builtin=False,
                public=v.get("privacy") in ("public", "semiPrivate"),
            )
            for v in indexers
        ]

    def list(self, index_id, page=0, keyword=None):
        if not index_id:
            return None
        start_time = datetime.datetime.now()
        indexers = self.get_indexers()
        matched = [i for i in indexers if str(i.id) == str(index_id) or i.name == index_id]
        if not matched:
            return None
        api_url = f"{matched[0].domain}?apikey={self.api_key}&t=search"
        if keyword:
            api_url += f"&q={quote(keyword)}"
        if page > 0:
            api_url += f"&offset={page * 20}&limit=20"
        result_array: list = []
        error_flag = False
        try:
            result_array = self._parse_torznabxml(api_url)
        except Exception as e:
            error_flag = True
            log.warn(f"[Prowlarr]搜索失败: {e}")
        seconds = round((datetime.datetime.now() - start_time).total_seconds(), 1)
        if self.download_repo:
            try:
                self.download_repo.insert_indexer_statistics(
                    indexer=str(index_id),
                    itype=self.client_type or self.client_id,
                    seconds=int(seconds),
                    result="N" if error_flag else "Y",
                )
            except Exception as e:
                log.warn(f"[Prowlarr]写入统计失败: {e!s}")
        return result_array

    def search(self, order_seq, indexer, key_word, filter_args, match_media, in_from):
        return super().search(order_seq, indexer, key_word, filter_args, match_media, in_from)
