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


class TestServiceInstall:
    def _mk(self, pkg: bytes, expected_sha: str | None = None, updater=None):
        catalog = '{"market_version":"1.0","id":"m","plugins":[{"id":"demo","path":"plugins/demo.json"}]}'
        detail = (
            '{"id":"demo","name":"demo","version":"1.0.0",'
            f'"download_url":"dist/demo.zip","sha256":"{expected_sha or ""}"}}'
        )
        calls = []

        def installer(data, enabled):
            calls.append((data, enabled))
            return {"plugin_id": "demo", "name": "demo", "version": "1.0.0"}

        auditor = PluginPackageAuditor()
        svc = PluginMarketService(
            store=_MemoryStore(),
            http_get=lambda url: catalog if url.endswith("catalog.json") else detail,
            http_get_bytes=lambda url: pkg,
            auditor=auditor,
            resolver=_fake_resolver,
            plugin_installer=installer,
            plugin_updater=updater,
        )
        sid = svc.add_source("m", "https://a.example/catalog.json")["source_id"]
        svc.sync_source(sid)
        return svc, sid, calls

    def test_install_good_package(self):
        pkg = _zip_bytes(
            {
                "manifest.json": '{"id":"demo","version":"1.0.0","name":"demo"}',
                "backend/main.py": "def ok():\n    return 1\n",
            }
        )
        svc, sid, calls = self._mk(pkg, expected_sha=PluginPackageAuditor().sha256(pkg))
        result = svc.install_plugin(sid, "demo", enabled=True)
        assert result["quarantined"] is False
        assert calls and calls[0][1] is True

    def test_install_quarantine_disabled(self):
        pkg = _zip_bytes(
            {
                "manifest.json": '{"id":"demo","version":"1.0.0","name":"demo"}',
                "backend/main.py": "def ok():\n    return 1\n",
            }
        )
        svc, sid, calls = self._mk(pkg, expected_sha=PluginPackageAuditor().sha256(pkg))
        result = svc.install_plugin(sid, "demo", enabled=False)
        assert result["quarantined"] is True
        assert calls and calls[0][1] is False

    def test_install_evil_blocked(self):
        pkg = _zip_bytes({"backend/x.py": "eval(input())\n"})
        svc, sid, calls = self._mk(pkg)
        try:
            svc.install_plugin(sid, "demo")
        except ValueError as e:
            assert "审计门禁" in str(e)
            assert calls == []
            return
        raise AssertionError("恶意包应被安装门禁拦截")

    def test_update_uses_updater(self):
        pkg = _zip_bytes(
            {
                "manifest.json": '{"id":"demo","version":"2.0.0","name":"demo"}',
                "backend/main.py": "def ok():\n    return 1\n",
            }
        )
        updated_calls = []
        svc, sid, _ = self._mk(
            pkg,
            expected_sha=PluginPackageAuditor().sha256(pkg),
            updater=lambda data, pid: updated_calls.append((data, pid)) or {"plugin_id": pid},
        )
        result = svc.update_plugin(sid, "demo")
        assert result["updated"]["plugin_id"] == "demo"
        assert updated_calls and updated_calls[0][1] == "demo"
