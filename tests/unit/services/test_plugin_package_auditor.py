"""PluginPackageAuditor / audit_plugin 单元测试（安装门禁）"""

import io
import ipaddress
import zipfile

from app.services.plugin_market_service import MarketSource, PluginMarketService, PluginMarketStore
from app.services.plugin_package_auditor import PluginPackageAuditor


class _MemoryStore(PluginMarketStore):
    def __init__(self):
        self.sources: dict[str, MarketSource] = {}

    def list(self):
        return list(self.sources.values())

    def add(self, source):
        self.sources[source.source_id] = source
        return source

    def update(self, source):
        self.sources[source.source_id] = source
        return source

    def delete(self, source_id):
        return self.sources.pop(source_id, None) is not None


def _fake_resolver(hostname):
    try:
        ipaddress.ip_address(hostname)
        return [hostname]
    except ValueError:
        return ["8.8.8.8"]


def _zip_bytes(entries: dict[str, str]) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        for name, content in entries.items():
            zf.writestr(name, content)
    return buf.getvalue()


class TestAuditor:
    def test_good_package_passes(self):
        z = _zip_bytes(
            {
                "manifest.json": '{"id":"demo","version":"1.0.0","name":"demo"}',
                "backend/main.py": "def hello():\n    return 1\n",
            }
        )
        auditor = PluginPackageAuditor()
        report = auditor.audit_bytes(z, expected_sha256=auditor.sha256(z))
        assert report.passed
        assert report.sha256_ok

    def test_sha_mismatch_blocks(self):
        z = _zip_bytes({"manifest.json": "{}"})
        report = PluginPackageAuditor().audit_bytes(z, expected_sha256="0" * 64)
        assert not report.passed
        assert any(f.rule == "sha256_mismatch" for f in report.findings)

    def test_banned_eval_blocks(self):
        z = _zip_bytes({"backend/x.py": "eval(input())\n"})
        report = PluginPackageAuditor().audit_bytes(z)
        assert not report.passed
        assert any(f.rule == "eval/exec/compile" for f in report.findings)

    def test_secret_leak_blocks(self):
        z = _zip_bytes({"backend/x.py": "api_key = 'sk-1234567890abcdefghijklmnopqrst'\n"})
        report = PluginPackageAuditor().audit_bytes(z)
        assert not report.passed
        assert any(f.rule == "secret_leak" for f in report.findings)

    def test_path_traversal_blocks(self):
        z = _zip_bytes({"../../evil.sh": "x"})
        report = PluginPackageAuditor().audit_bytes(z)
        assert not report.passed
        assert any(f.rule == "path_traversal" for f in report.findings)


class TestServiceAudit:
    def test_audit_plugin_report(self):
        catalog = '{"market_version":"1.0","id":"m","plugins":[{"id":"demo","path":"plugins/demo.json"}]}'
        detail = '{"id":"demo","name":"demo","version":"1.0.0","download_url":"dist/demo.zip","sha256":"0000"}'
        good = _zip_bytes(
            {
                "manifest.json": '{"id":"demo","version":"1.0.0","name":"demo"}',
                "backend/main.py": "def ok():\n    return 1\n",
            }
        )

        def http(url):
            return catalog if url.endswith("catalog.json") else detail

        def http_bytes(url):
            assert url.endswith("demo.zip")
            return good

        auditor = PluginPackageAuditor()
        svc = PluginMarketService(
            store=_MemoryStore(),
            http_get=http,
            http_get_bytes=http_bytes,
            auditor=auditor,
            resolver=_fake_resolver,
        )
        sid = svc.add_source("m", "https://a.example/catalog.json")["source_id"]
        svc.sync_source(sid)
        result = svc.audit_plugin(sid, "demo")
        assert result["plugin_id"] == "demo"
        assert result["report"]["sha256_ok"] is False  # 期望哈希为 0000 → 不匹配
        assert result["report"]["passed"] is False
