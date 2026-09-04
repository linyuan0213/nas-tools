"""PluginMarketService 单元测试 — 源管理 + catalog 同步（里程碑一）"""

import ipaddress

from app.services.plugin_market_service import MarketSource, PluginMarketService, PluginMarketStore


def _fake_resolver(hostname: str) -> list[str]:
    # 测试离线：IP 字面量按自身解析，域名统一解析为公网地址
    try:
        ipaddress.ip_address(hostname)
        return [hostname]
    except ValueError:
        return ["8.8.8.8"]


class _MemoryStore(PluginMarketStore):
    def __init__(self):
        self.sources: dict[str, MarketSource] = {}

    def list(self):
        return list(self.sources.values())

    def add(self, source):
        source.source_id = source.source_id or source.name
        self.sources[source.source_id] = source
        return source

    def update(self, source):
        self.sources[source.source_id] = source
        return source

    def delete(self, source_id):
        return self.sources.pop(source_id, None) is not None


CATALOG = """
{
  "market_version": "1.0",
  "id": "mymarket",
  "name": "我的源",
  "plugins": [
    { "id": "demo_plugin", "path": "plugins/demo_plugin.json", "updated_at": "2026-09-04T00:00:00+08:00" },
    { "id": "bad_plugin" }
  ]
}
"""


def _service(http=None, resolver=None):
    return PluginMarketService(
        store=_MemoryStore(),
        http_get=http or (lambda url: CATALOG),
        resolver=resolver or _fake_resolver,
    )


class TestSourceCrud:
    def test_add_and_list(self):
        svc = _service()
        svc.add_source("官方源", "https://plugins.example.com/catalog.json")
        sources = svc.list_sources()
        assert len(sources) == 1
        assert sources[0]["url"].startswith("https://")

    def test_private_url_rejected(self):
        svc = _service()
        try:
            svc.add_source("bad", "http://192.168.1.1/catalog.json")
        except ValueError as e:
            assert "内部网络" in str(e)
            return
        raise AssertionError("应拒绝私网市场源 URL")

    def test_update_and_delete(self):
        svc = _service()
        svc.add_source("s1", "https://a.example/catalog.json")
        svc.update_source("s1", enabled=False, auto_update=True)
        assert svc.list_sources()[0]["enabled"] is False
        assert svc.list_sources()[0]["auto_update"] is True
        assert svc.delete_source("s1") is True


class TestCatalogSync:
    def test_sync_validates_and_caches(self):
        svc = _service()
        svc.add_source("s1", "https://a.example/catalog.json")
        result = svc.sync_source("s1")
        assert result["plugin_count"] == 1  # bad_plugin（缺 path）被跳过
        assert result["meta"]["name"] == "我的源"
        plugins = svc.list_catalog_plugins("s1")
        assert plugins[0]["id"] == "demo_plugin"

    def test_sync_http_error_records_last_error(self):
        def boom(url):
            raise RuntimeError("network down")

        svc = _service(http=boom)
        svc.add_source("s1", "https://a.example/catalog.json")
        try:
            svc.sync_source("s1")
        except ValueError as e:
            assert "network down" in str(e)
            assert svc.list_sources()[0]["last_error"]
            return
        raise AssertionError("同步失败应抛错")

    def test_invalid_catalog_rejected(self):
        svc = _service(http=lambda url: '{"plugins": []}')
        svc.add_source("s1", "https://a.example/catalog.json")
        try:
            svc.sync_source("s1")
        except ValueError as e:
            assert "必需字段" in str(e)
            return
        raise AssertionError("应拒绝缺 market_version/id/plugins 的目录")

    def test_catalog_plugins_keyword_filter(self):
        svc = _service()
        svc.add_source("s1", "https://a.example/catalog.json")
        svc.sync_source("s1")
        assert len(svc.list_catalog_plugins("s1", keyword="demo")) == 1
        assert svc.list_catalog_plugins("s1", keyword="none") == []
