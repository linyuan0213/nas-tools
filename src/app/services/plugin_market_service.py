"""插件市场服务 — 市场源管理与目录索引同步（里程碑一核心逻辑）

存储经 PluginMarketStore 抽象注入（后续由 DB 仓库实现，单测用内存实现）；
HTTP 拉取经 http_get 注入（生产走应用 HttpClient，测试 mock），便于离线验证。
"""

import ipaddress
import json
import re
import socket
import time
import uuid
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any
from urllib.parse import urljoin, urlparse, urlsplit

import httpx

import log
from app.services.plugin_package_auditor import PluginPackageAuditor

# 目录式市场索引（catalog.json）的最小必需字段
_CATALOG_REQUIRED = ("market_version", "id", "plugins")
_PLUGIN_ENTRY_REQUIRED = ("id", "path")


@dataclass
class MarketSource:
    """市场源"""

    name: str
    url: str
    enabled: bool = True
    auto_update: bool = False
    public_key: str = ""
    last_sync_at: str = ""
    last_error: str = ""
    source_id: str = ""

    def to_dict(self) -> dict:
        return {
            "source_id": self.source_id or self.name,
            "name": self.name,
            "url": self.url,
            "enabled": self.enabled,
            "auto_update": self.auto_update,
            "public_key": self.public_key,
            "last_sync_at": self.last_sync_at,
            "last_error": self.last_error,
        }


@dataclass
class MarketCatalog:
    """同步后的目录式索引缓存"""

    source: MarketSource
    meta: dict = field(default_factory=dict)
    plugins: list[dict] = field(default_factory=list)  # [{id, path, updated_at}]
    synced_at: float = 0.0
    error: str = ""


class PluginMarketStore:
    """市场源存储抽象（DB 仓库或内存实现）"""

    def list(self) -> list[MarketSource]:
        raise NotImplementedError

    def add(self, source: MarketSource) -> MarketSource:
        raise NotImplementedError

    def update(self, source: MarketSource) -> MarketSource:
        raise NotImplementedError

    def delete(self, source_id: str) -> bool:
        raise NotImplementedError


class PluginMarketService:
    """插件市场服务：源 CRUD + catalog 拉取/校验/缓存"""

    def __init__(
        self,
        store: PluginMarketStore,
        http_get: Callable[[str], str] | None = None,
        cache: dict[str, MarketCatalog] | None = None,
        resolver: Callable[[str], list[str]] | None = None,
        http_get_bytes: Callable[[str], bytes] | None = None,
        auditor: Any | None = None,
        plugin_installer: Callable[[bytes, bool], dict] | None = None,
        plugin_updater: Callable[[bytes, str], dict] | None = None,
    ):
        self._store = store
        self._http_get = http_get or self._default_http_get
        self._http_get_bytes = http_get_bytes or self._default_http_get_bytes
        self._resolver = resolver or self._default_resolve
        self._catalog_cache: dict[str, MarketCatalog] = cache if cache is not None else {}
        self._detail_cache: dict[tuple[str, str], dict] = {}
        self._auditor: Any = auditor if auditor is not None else PluginPackageAuditor()
        self._plugin_installer = plugin_installer
        self._plugin_updater = plugin_updater

    @staticmethod
    def _default_resolve(hostname: str) -> list[str]:
        return [str(info[4][0]).split("%")[0] for info in socket.getaddrinfo(hostname, None, type=socket.SOCK_STREAM)]

    # ------------------------------------------------------------ 工具

    def _assert_public_http(self, url: str) -> None:
        """仅允许公网 http(s)，拒绝私网/回环/链路本地/元数据地址（防 SSRF）"""
        parsed = urlparse(url)
        if parsed.scheme not in ("http", "https") or not parsed.hostname:
            raise ValueError(f"仅支持 http(s) 市场源 URL: {url}")
        try:
            ips = self._resolver(parsed.hostname)
        except socket.gaierror as e:
            raise ValueError(f"市场源无法解析: {url}") from e
        if not ips:
            raise ValueError(f"市场源无法解析: {url}")
        for ip_text in ips:
            ip = ipaddress.ip_address(ip_text)
            if (
                ip.is_private
                or ip.is_loopback
                or ip.is_link_local
                or ip.is_multicast
                or ip.is_reserved
                or ip.is_unspecified
                or ip == ipaddress.ip_address("169.254.169.254")
                or ip == ipaddress.ip_address("169.254.169.253")
            ):
                raise ValueError(f"市场源指向内部网络，已拒绝: {url}")

    def _default_http_get(self, url: str) -> str:
        resp = httpx.get(url, timeout=30, follow_redirects=False)
        resp.raise_for_status()
        return resp.text

    @staticmethod
    def _validate_catalog(text: str) -> tuple[dict, list[dict]]:
        """解析并校验 catalog.json，返回 (meta, plugins)；坏记录跳过"""
        try:
            data = json.loads(text)
        except (ValueError, TypeError) as e:
            raise ValueError(f"目录索引 JSON 解析失败: {e}") from e
        if not isinstance(data, dict) or any(k not in data for k in _CATALOG_REQUIRED):
            raise ValueError("目录索引缺少必需字段: market_version/id/plugins")
        plugins = []
        for entry in data.get("plugins") or []:
            if not isinstance(entry, dict) or any(k not in entry for k in _PLUGIN_ENTRY_REQUIRED):
                continue  # 坏记录跳过
            plugins.append(
                {
                    "id": str(entry.get("id")),
                    "path": str(entry.get("path")),
                    "updated_at": entry.get("updated_at", ""),
                }
            )
        return data, plugins

    # ------------------------------------------------------------ 源管理

    def list_sources(self) -> list[dict]:
        return [s.to_dict() for s in self._store.list()]

    def add_source(self, name: str, url: str, public_key: str = "") -> dict:
        self._assert_public_http(url)
        source = MarketSource(name=name, url=url, public_key=public_key)
        source.source_id = f"src_{uuid.uuid4().hex[:10]}"
        added = self._store.add(source)
        return added.to_dict()

    def update_source(self, source_id: str, **fields) -> dict:
        sources = self._store.list()
        target = next((s for s in sources if s.source_id == source_id), None)
        if not target:
            raise ValueError(f"市场源不存在: {source_id}")
        if "url" in fields:
            self._assert_public_http(str(fields["url"]))
        for key in ("name", "url", "public_key", "enabled", "auto_update"):
            if key in fields:
                setattr(target, key, fields[key])
        updated = self._store.update(target)
        self._catalog_cache.pop(source_id, None)
        return updated.to_dict()

    def delete_source(self, source_id: str) -> bool:
        self._catalog_cache.pop(source_id, None)
        return self._store.delete(source_id)

    # ------------------------------------------------------------ 目录同步

    def sync_source(self, source_id: str) -> dict:
        sources = self._store.list()
        source = next((s for s in sources if s.source_id == source_id), None)
        if not source:
            raise ValueError(f"市场源不存在: {source_id}")
        catalog = self._fetch_catalog(source)
        if catalog.error:
            raise ValueError(catalog.error)
        return {
            "source_id": source.source_id,
            "meta": catalog.meta,
            "plugin_count": len(catalog.plugins),
            "synced_at": catalog.synced_at,
        }

    def sync_auto_sources(self) -> dict:
        """定时任务：同步所有启用且开启 auto_update 的源（单项失败不阻塞其余）"""
        results = []
        ok = 0
        for source in self._store.list():
            if not (source.enabled and source.auto_update):
                continue
            try:
                result = self.sync_source(source.source_id)
                results.append({"source_id": source.source_id, "ok": True, **result})
                ok += 1
            except Exception as e:  # noqa: BLE001
                results.append({"source_id": source.source_id, "ok": False, "error": str(e)})
        return {"synced": ok, "total": len(results), "results": results}

    def _fetch_catalog(self, source: MarketSource) -> MarketCatalog:
        try:
            self._assert_public_http(source.url)
            text = self._http_get(source.url)
            meta, plugins = self._validate_catalog(text)
            catalog = MarketCatalog(source=source, meta=meta, plugins=plugins, synced_at=time.time())
            source.last_sync_at = str(catalog.synced_at)
            source.last_error = ""
            self._store.update(source)
            self._catalog_cache[source.source_id] = catalog
            return catalog
        except Exception as e:  # noqa: BLE001
            source.last_error = str(e)
            try:
                self._store.update(source)
            except Exception:  # noqa: BLE001
                log.warn("[PluginMarket]同步失败且记录状态出错，忽略")
            log.warn(f"[PluginMarket]同步市场源失败 {source.name}: {e}")
            return MarketCatalog(source=source, error=str(e))

    def get_catalog(self, source_id: str) -> MarketCatalog | None:
        """返回最近一次同步的目录缓存（未同步过返回 None）"""
        return self._catalog_cache.get(source_id)

    def list_catalog_plugins(self, source_id: str, keyword: str = "") -> list[dict]:
        catalog = self.get_catalog(source_id)
        if not catalog:
            return []
        keyword = (keyword or "").strip().lower()
        items = []
        for p in catalog.plugins:
            if keyword and keyword not in f"{p.get('id')} {p.get('updated_at')}".lower():
                continue
            items.append({"source_id": source_id, **p})
        return items

    # ------------------------------------------------------------ 插件详情（懒加载）

    @staticmethod
    def _join_url(base_url: str, path: str) -> str:
        """把插件详情/包相对路径基于 catalog.json 所在目录拼接为完整 URL"""
        catalog_dir = base_url.rsplit("/", 1)[0] + "/" if "/" in base_url else base_url
        return urljoin(catalog_dir, path)

    def get_plugin_detail(self, source_id: str, plugin_id: str) -> dict:
        """按需拉取 plugins/<id>.json 并缓存（detail 元数据）"""
        key = (source_id, plugin_id)
        cached = self._detail_cache.get(key)
        if cached is not None:
            return cached
        catalog = self.get_catalog(source_id)
        if not catalog:
            raise ValueError("目录未同步，请先同步市场源")
        entry = next((p for p in catalog.plugins if p.get("id") == plugin_id), None)
        if not entry:
            raise ValueError(f"目录中不存在插件: {plugin_id}")
        url = self._join_url(catalog.source.url, str(entry["path"]))
        # 防 SSRF：详情/包只允许同源（与目录索引同一 host:port），禁止跳其他域名
        if urlsplit(url).netloc and urlsplit(url).netloc != urlsplit(catalog.source.url).netloc:
            raise ValueError("插件详情必须与市场源同源")
        self._assert_public_http(url)
        detail = self._validate_plugin_detail(self._http_get(url), plugin_id)
        self._detail_cache[key] = detail
        return detail

    @staticmethod
    def _validate_plugin_detail(text: str, plugin_id: str) -> dict:
        """校验单插件详情：必需 id/version；id 必须与请求一致（防路径串读）"""
        try:
            data = json.loads(text)
        except (ValueError, TypeError) as e:
            raise ValueError(f"插件详情 JSON 解析失败: {e}") from e
        if not isinstance(data, dict):
            raise ValueError("插件详情必须是 JSON 对象")
        if str(data.get("id", "")) != plugin_id:
            raise ValueError("插件详情 id 与请求不一致，可能被篡改")
        if not data.get("version"):
            raise ValueError("插件详情缺少 version")
        return data

    # ------------------------------------------------------------ 版本对比

    @staticmethod
    def compare_versions(local: str, remote: str) -> int:
        """语义化版本比较：local<remote 返回 -1；相等 0；local>remote 1（忽略 pre-release 后缀）"""
        pattern = re.compile(r"(\d+)(?:\.(\d+))?(?:\.(\d+))?")

        def parse(ver: str) -> tuple:
            m = pattern.match(str(ver).strip().lstrip("vV"))
            return tuple(int(m.group(i)) if m and m.group(i) else 0 for i in (1, 2, 3))

        a, b = parse(local), parse(remote)
        return (a > b) - (a < b)

    # ------------------------------------------------------------ 包审计（安装门禁）

    def _default_http_get_bytes(self, url: str) -> bytes:
        resp = httpx.get(url, timeout=60, follow_redirects=False)
        resp.raise_for_status()
        return resp.content

    def _fetch_package(self, source_id: str, detail: dict) -> bytes:
        """按 detail.download_url 下载插件包（同源 + 公网校验）"""
        catalog = self.get_catalog(source_id)
        if not catalog:
            raise ValueError("目录未同步，请先同步市场源")
        source_url = catalog.source.url
        download_url = detail.get("download_url") or ""
        if not download_url:
            raise ValueError("插件详情缺少 download_url")
        url = self._join_url(source_url, str(download_url))
        if urlsplit(url).netloc and urlsplit(url).netloc != urlsplit(source_url).netloc:
            raise ValueError("插件包必须与市场源同源")
        self._assert_public_http(url)
        return self._http_get_bytes(url)

    def audit_plugin(self, source_id: str, plugin_id: str) -> dict:
        """预检（audit）：下载插件包 → sha256 → 静态扫描，不落盘启用

        返回 {plugin_id, version, sha256, report}；block 级命中 report.passed=False。
        """
        detail = self.get_plugin_detail(source_id, plugin_id)
        data = self._fetch_package(source_id, detail)
        report = self._auditor.audit_bytes(data, str(detail.get("sha256") or ""))
        return {
            "plugin_id": plugin_id,
            "version": detail.get("version", ""),
            "sha256": self._auditor.sha256(data),
            "report": report.to_dict(),
        }

    def install_plugin(self, source_id: str, plugin_id: str, enabled: bool = True) -> dict:
        """安装：审计门禁通过后由插件安装器落盘（可只装不启用）

        隔离语义：enabled=False 时安装后保持禁用（quarantine），
        block 级审计命中直接拒绝安装。
        """
        detail = self.get_plugin_detail(source_id, plugin_id)
        data = self._fetch_package(source_id, detail)
        report = self._auditor.audit_bytes(data, str(detail.get("sha256") or ""))
        if not report.passed:
            findings = [f for f in report.to_dict()["findings"] if f["severity"] == "block"]
            raise ValueError(f"安装被审计门禁拦截: {len(findings)} 项高危问题")
        if self._plugin_installer is None:
            raise ValueError("插件安装服务未接入")
        installed = self._plugin_installer(data, enabled)
        return {
            "plugin_id": plugin_id,
            "version": detail.get("version", ""),
            "sha256": self._auditor.sha256(data),
            "installed": installed,
            "quarantined": not enabled,
        }

    def update_plugin(self, source_id: str, plugin_id: str) -> dict:
        """更新已装插件到市场最新版本（同样过审计门禁；配置保留，失败需回滚见后续）"""
        detail = self.get_plugin_detail(source_id, plugin_id)
        data = self._fetch_package(source_id, detail)
        report = self._auditor.audit_bytes(data, str(detail.get("sha256") or ""))
        if not report.passed:
            findings = [f for f in report.to_dict()["findings"] if f["severity"] == "block"]
            raise ValueError(f"更新被审计门禁拦截: {len(findings)} 项高危问题")
        if self._plugin_updater is None:
            raise ValueError("插件更新服务未接入")
        updated = self._plugin_updater(data, plugin_id)
        return {
            "plugin_id": plugin_id,
            "version": detail.get("version", ""),
            "sha256": self._auditor.sha256(data),
            "updated": updated,
        }

    def list_plugin_details(self, source_id: str, plugin_ids: list[str]) -> dict[str, dict]:
        """批量拉取详情（用于 /status 只取与已装插件匹配的条目）；单条失败跳过"""
        result: dict[str, dict] = {}
        for pid in plugin_ids:
            try:
                result[pid] = self.get_plugin_detail(source_id, pid)
            except Exception as e:  # noqa: BLE001
                log.warn(f"[PluginMarket]拉取插件详情失败 {source_id}/{pid}: {e}")
        return result
