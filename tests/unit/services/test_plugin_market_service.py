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
        sid = svc.add_source("s1", "https://a.example/catalog.json")["source_id"]
        svc.update_source(sid, enabled=False, auto_update=True)
        assert svc.list_sources()[0]["enabled"] is False
        assert svc.list_sources()[0]["auto_update"] is True
        assert svc.delete_source(sid) is True


class TestCatalogSync:
    def test_sync_validates_and_caches(self):
        svc = _service()
        sid = svc.add_source("s1", "https://a.example/catalog.json")["source_id"]
        result = svc.sync_source(sid)
        assert result["plugin_count"] == 1  # bad_plugin（缺 path）被跳过
        assert result["meta"]["name"] == "我的源"
        plugins = svc.list_catalog_plugins(sid)
        assert plugins[0]["id"] == "demo_plugin"

    def test_sync_http_error_records_last_error(self):
        def boom(url):
            raise RuntimeError("network down")

        svc = _service(http=boom)
        sid = svc.add_source("s1", "https://a.example/catalog.json")["source_id"]
        try:
            svc.sync_source(sid)
        except ValueError as e:
            assert "network down" in str(e)
            assert svc.list_sources()[0]["last_error"]
            return
        raise AssertionError("同步失败应抛错")

    def test_invalid_catalog_rejected(self):
        svc = _service(http=lambda url: '{"plugins": []}')
        sid = svc.add_source("s1", "https://a.example/catalog.json")["source_id"]
        try:
            svc.sync_source(sid)
        except ValueError as e:
            assert "必需字段" in str(e)
            return
        raise AssertionError("应拒绝缺 market_version/id/plugins 的目录")

    def test_catalog_plugins_keyword_filter(self):
        svc = _service()
        sid = svc.add_source("s1", "https://a.example/catalog.json")["source_id"]
        svc.sync_source(sid)
        assert len(svc.list_catalog_plugins(sid, keyword="demo")) == 1
        assert svc.list_catalog_plugins(sid, keyword="none") == []


DETAIL = """
{
  "id": "demo_plugin",
  "name": "示例插件",
  "version": "2.0.0",
  "category": "automation",
  "tags": ["autosignin"],
  "min_app_version": "4.16.0",
  "download_url": "dist/demo_plugin@2.0.0.zip",
  "sha256": "abc"
}
"""


class TestPluginDetailAndVersion:
    @staticmethod
    def _responder(detail_body):
        return lambda url: CATALOG if url.endswith("/catalog.json") else detail_body

    def test_detail_fetch_cached_and_version_compare(self):
        calls = []
        http = lambda url: calls.append(url) or (CATALOG if url.endswith("/catalog.json") else DETAIL)  # noqa: E731
        svc = _service(http=http)
        sid = svc.add_source("s1", "https://a.example/catalog.json")["source_id"]
        svc.sync_source(sid)
        detail = svc.get_plugin_detail(sid, "demo_plugin")
        assert detail["version"] == "2.0.0"
        # 缓存命中：第二次不再发请求
        assert svc.get_plugin_detail(sid, "demo_plugin")["id"] == "demo_plugin"
        assert len(calls) == 2  # catalog + detail
        # 相对路径基于 catalog 目录拼接
        assert calls[1] == "https://a.example/plugins/demo_plugin.json"

    def test_detail_id_mismatch_rejected(self):
        bad = '{"id": "other", "version": "1.0.0"}'
        svc = _service(http=self._responder(bad))
        sid = svc.add_source("s1", "https://a.example/catalog.json")["source_id"]
        svc.sync_source(sid)
        try:
            svc.get_plugin_detail(sid, "demo_plugin")
        except ValueError as e:
            assert "不一致" in str(e)
            return
        raise AssertionError("详情 id 与请求不一致应被拒绝")

    def test_cross_origin_detail_rejected(self):
        svc = _service(http=self._responder(DETAIL))
        sid = svc.add_source("s1", "https://a.example/catalog.json")["source_id"]
        svc.sync_source(sid)
        catalog = svc.get_catalog(sid)
        assert catalog is not None
        catalog.plugins[0]["path"] = "https://evil.example/x.json"
        try:
            svc.get_plugin_detail(sid, "demo_plugin")
        except ValueError as e:
            assert "同源" in str(e)
            return
        raise AssertionError("跨源详情地址应被拒绝")

    def test_compare_versions(self):
        compare = PluginMarketService.compare_versions
        assert compare("1.0.0", "1.0.1") == -1
        assert compare("v1.2.3", "1.2.3") == 0
        assert compare("2.0.0", "1.9.9") == 1
        assert compare("1.0", "1.0.0") == 0


class TestAutoSyncJob:
    def test_sync_auto_sources_only_auto_update(self):
        svc = _service()
        auto = svc.add_source("auto", "https://a.example/catalog.json")["source_id"]
        svc.update_source(auto, auto_update=True)
        svc.add_source("manual", "https://b.example/catalog.json")
        result = svc.sync_auto_sources()
        assert result["synced"] == 1
        assert result["total"] == 1
        assert svc.list_sources()[0]["last_sync_at"]  # auto 源已记录同步时间

    def test_auto_sync_failure_recorded(self):
        def boom(url):
            raise RuntimeError("network down")

        svc = _service(http=boom)
        auto = svc.add_source("auto", "https://a.example/catalog.json")["source_id"]
        svc.update_source(auto, auto_update=True)
        result = svc.sync_auto_sources()
        assert result["synced"] == 0
        assert result["results"][0]["ok"] is False
        assert "network down" in result["results"][0]["error"]

    def test_auto_sync_detects_and_notifies_updates(self):
        catalog = '{"market_version":"1.0","id":"m","plugins":[{"id":"demo","path":"plugins/demo.json"}]}'
        detail = '{"id":"demo","name":"demo","version":"2.0.0","download_url":"dist/demo.zip"}'
        notified = []

        def http(url):
            return catalog if url.endswith("catalog.json") else detail

        svc = PluginMarketService(
            store=_MemoryStore(),
            http_get=http,
            resolver=_fake_resolver,
            installed_provider=lambda: [{"id": "demo", "version": "1.0.0"}],
            notifier=lambda updates: notified.extend(updates),
        )
        auto = svc.add_source("auto", "https://a.example/catalog.json")["source_id"]
        svc.update_source(auto, auto_update=True)
        result = svc.sync_auto_sources()
        assert len(result["updates"]) == 1
        assert result["updates"][0]["installed_version"] == "1.0.0"
        assert result["updates"][0]["remote_version"] == "2.0.0"
        assert notified and notified[0]["plugin_id"] == "demo"
