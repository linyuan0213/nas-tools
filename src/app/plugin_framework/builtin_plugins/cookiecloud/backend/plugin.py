"""
CookieCloud Plugin v2
从 CookieCloud 云端同步数据
"""

import contextlib
import re
import time
from collections import defaultdict
from typing import Any

from app.db.repositories.site_repo_adapter import SiteRepositoryAdapter
from app.domain.entities.site import SiteEntity
from app.domain.enums import SiteUseType
from app.infrastructure.cache_system import get_cache_manager
from app.infrastructure.http.auth import CookieAuth
from app.infrastructure.http.client import HttpClient
from app.infrastructure.http.config import HttpClientConfig
from app.infrastructure.http.exceptions import HttpClientError
from app.plugin_framework.context import PluginContext
from app.sites.utils import is_logged_in
from app.utils import StringUtils
from app.utils.config_tools import get_ua
from app.utils.json_utils import JsonUtils


class CookieCloudPlugin:
    """CookieCloud 同步插件"""

    _ignore_cookies = ["CookieAutoDeleteBrowsingDataCleanup"]

    def __init__(
        self,
        ctx: PluginContext,
        sites: Any,
        index_helper: Any,
        site_repo: Any = None,
    ):
        self.ctx = ctx
        self.sites = sites
        self._site_repo = site_repo or SiteRepositoryAdapter()
        self._index_helper = index_helper
        self._cache = get_cache_manager().get_or_create("plugin_cookiecloud", cache_type="redis")

    def _get_config(self):
        return self.ctx.get_config() or {}

    def on_enable(self):
        self.ctx.info("CookieCloud 插件已启用")
        self._start_service()
        self.ctx.register_message_command("cookiecloud", "立即同步 CookieCloud", self._on_cookiecloud_cmd)

    def on_disable(self):
        self.ctx.info("CookieCloud 插件已禁用")
        self._stop_service()
        self.ctx.unregister_message_command("cookiecloud")

    def _on_cookiecloud_cmd(self, msg, in_from, user_id, user_name):
        self.ctx.info(f"收到 CookieCloud 同步命令: user={user_name}, msg={msg}")
        self._cookie_sync(manual=True)
        self.ctx._message.send_channel_msg(
            channel=in_from, title="CookieCloud 同步", text="同步任务已触发，请稍后查看同步结果", user_id=user_id
        )

    def on_hook(self, event, data):
        if event == "plugin.config_changed":
            if data.get("plugin_id") == self.ctx.plugin_id:
                self.ctx.info("配置已变更，重载服务")
                self._stop_service()
                self._start_service()
                self._write_domain_list()
        elif event == "site.cookie_sync":
            self._cookie_save()
        elif event == "site.local_storage_sync":
            self._local_storage_save()

    def run(self):
        self.ctx.info("手动触发 CookieCloud 同步")
        self._cookie_sync(manual=True)

    def _start_service(self):
        config = self._get_config()
        enabled = config.get("enabled", False)
        cron = config.get("cron")

        if not enabled:
            self.ctx.info("未启用定时同步，跳过")
            return

        if enabled and cron:
            self.ctx.info(f"CookieCloud 同步服务启动，周期：{cron}")
            try:
                self.ctx.schedule_cron("sync", self._cookie_sync, cron=cron)
            except Exception as e:
                self.ctx.error(f"schedule_cron 失败: {e}")

    def _stop_service(self):
        with contextlib.suppress(Exception):
            self.ctx.remove_schedule("sync")

    @staticmethod
    def is_domain_in_list(domain, domain_list):
        return any(re.search(pattern, domain) for pattern in domain_list)

    def _check_domain(self, domain):
        config = self._get_config()
        blacklist = config.get("blacklist", "")
        whitelist = config.get("whitelist", "")

        if blacklist and self.is_domain_in_list(domain, blacklist.splitlines()):
            self.ctx.debug(f"{domain} 在黑名单中，已排除")
            return False

        if not whitelist:
            return True

        if self.is_domain_in_list(domain, whitelist.splitlines()):
            self.ctx.debug(f"{domain} 在白名单中")
            return True

        return False

    def _get_filter_names(self) -> set[str] | None:
        config = self._get_config()
        raw = (config.get("cookie_name_filter") or "").strip()
        if not raw:
            return None
        return {line.strip() for line in raw.splitlines() if line.strip()}

    def _allow_cookie_name(self, name: str) -> bool:
        allowed = self._get_filter_names()
        if allowed is None:
            return True
        return name in allowed

    def _write_domain_list(self):
        try:
            all_sites = self.ctx.site_engine.all_sites()
        except Exception:
            self.ctx.info("[CookieCloud]站点引擎未就绪，跳过域名列表写入")
            return
        try:
            domain_list = [{"label": s.name, "value": s.domain} for s in all_sites if not s.public and s.domain]
            if domain_list:
                self.ctx.write_data("domains.json", JsonUtils.dumps(domain_list))
                self.ctx.info(f"[CookieCloud]已写入 {len(domain_list)} 个站点域名")
            else:
                self.ctx.info("[CookieCloud]站点列表为空，稍后在同步时刷新")
        except Exception as e:
            self.ctx.warn(f"[CookieCloud]写入域名列表失败: {e}")

    def _download_data(self) -> tuple[dict, str, bool]:
        config = self._get_config()
        server = config.get("server", "")
        key = config.get("key", "")
        password = config.get("password", "")

        if not server or not key or not password:
            return {}, "CookieCloud 参数不正确", False

        if not server.startswith("http"):
            server = f"http://{server}"
        if server.endswith("/"):
            server = server[:-1]

        req_url = f"{server}/get/{key}"
        try:
            with HttpClient(config=HttpClientConfig(default_headers={"Content-Type": "application/json"})) as http:
                ret = http.post(url=req_url, json={"password": password})
            result = ret.json()
            content = {}
            if not result:
                return {}, "", True
            if result.get("cookie_data"):
                content["cookie_data"] = result.get("cookie_data")
            if result.get("local_storage_data"):
                content["local_storage_data"] = result.get("local_storage_data")
            return content, "", True
        except HttpClientError as exc:
            return {}, f"同步 CookieCloud 失败，错误码：{exc.status_code}", False
        except Exception:
            return {}, "CookieCloud 请求失败，请检查服务器地址、用户 KEY 及加密密码是否正确", False

    def _cookie_sync(self, manual=False):
        if not self._get_config().get("enabled") and not manual:
            return
        self.ctx.info("同步服务开始 ...")
        contents, msg, flag = self._download_data()
        if not flag:
            self.ctx.error(msg)
            self._send_message(msg)
            return
        if not contents:
            self.ctx.info("未从 CookieCloud 获取到数据")
            self._send_message("未从 CookieCloud 获取到数据")
            return

        ls_synced = 0
        try:
            # m-team 等站点使用 localStorage 中的 JWT 认证，须随手动/定时同步一并写入
            ls_synced = self._store_local_storage(contents)
        except Exception as e:
            self.ctx.warn(f"[CookieCloud]同步 LocalStorage 失败: {e}")

        try:
            update_ok, add_ok, failed, _results = self._process_cookies(contents if isinstance(contents, dict) else {})
        except Exception as e:
            err_msg = f"处理 Cookie 数据异常: {e}"
            self.ctx.error(err_msg)
            self._send_message(err_msg)
            return

        if not contents.get("local_storage_data"):
            if update_ok or add_ok:
                msg = f"更新了 {update_ok} 个站点的 Cookie 数据，新增了 {add_ok} 个站点"
            else:
                msg = "同步完成，但未更新任何站点数据！"
        else:
            msg = f"同步完成：更新了 {update_ok} 个站点的 Cookie 数据，新增了 {add_ok} 个站点"
        if ls_synced:
            msg += f"，LocalStorage 已更新 {ls_synced} 个站点"

        if failed:
            msg += f"（{failed} 个失败/跳过）"

        self.ctx.info(msg)

        config = self._get_config()
        if config.get("notify"):
            self._send_message(msg)

    def _cookie_save(self):
        self.ctx.info("开始同步 Cookie 到 Redis ...")
        contents, msg, flag = self._download_data()
        if not flag:
            self.ctx.error(msg)
            return
        if not contents:
            self.ctx.info("未从 CookieCloud 获取到数据")
            return
        self._store_cookies_to_cache(contents if isinstance(contents, dict) else {})
        self.ctx.info("Cookie 同步 Redis 成功")

    def _store_cookies_to_cache(self, contents: dict):
        domain_cookie_groups = defaultdict(list)
        cookie_content = contents.get("cookie_data") or {}
        for _site, cookies in cookie_content.items():
            for cookie in cookies:
                if not self._check_domain(cookie["domain"]):
                    continue
                raw_domain = cookie["domain"].lstrip(".")
                domain_key = raw_domain
                domain_cookie_groups[domain_key].append(cookie)

        result = {}
        for domain, content_list in domain_cookie_groups.items():
            if not content_list:
                continue

            domain_url = domain

            cloudflare_cookie = True
            for content in content_list:
                if content["name"] != "cf_clearance":
                    cloudflare_cookie = False
                    break
            if cloudflare_cookie:
                continue

            cookie_str = ";".join(
                [
                    f"{content.get('name')}={content.get('value')}"
                    for content in content_list
                    if content.get("name")
                    and content.get("name") not in self._ignore_cookies
                    and self._allow_cookie_name(content.get("name"))
                ]
            )
            self._cache.set(f"cookie:{domain_url}", cookie_str)
            result[domain_url] = cookie_str

        return result

    def _find_matching_sites(self, domain_url: str) -> list[dict]:
        matched = []
        for site in self.sites.get_sites():
            strict_url = site.get("strict_url", "")
            if not strict_url:
                continue
            site_domain = StringUtils.get_url_domain(strict_url)
            if not site_domain:
                continue
            if domain_url in site_domain or site_domain in domain_url:
                matched.append(site)
            else:
                site_suffix = ".".join(site_domain.split(".")[-2:])
                domain_suffix = ".".join(domain_url.split(".")[-2:])
                if site_suffix == domain_suffix:
                    matched.append(site)
        return matched

    def _site_def_id(self, site_def) -> str:
        """获取站点定义的唯一 id（来自站点 JSON 配置，如 "chdbits"）。"""
        if site_def is None:
            return ""
        if hasattr(site_def, "id"):
            return str(getattr(site_def, "id", "") or "")
        if isinstance(site_def, dict):
            return str(site_def.get("id", "") or "")
        return ""

    def _site_def_aliases(self, site_def) -> list[str]:
        if site_def is None:
            return []
        if hasattr(site_def, "domain_aliases"):
            return list(site_def.domain_aliases or [])
        if isinstance(site_def, dict):
            return list(site_def.get("domain_aliases") or [])
        return []

    def _dedupe_existing_sites(self) -> int:
        """清理重复站点：依据站点 JSON 配置的唯一 id 分组，同一站点存在多条时仅保留最后（id 最大）一条。

        返回删除的条数。"""
        groups: dict[str, list[int]] = defaultdict(list)
        for e in self._site_repo.list_all():
            url = e.sign_url or e.rss_url
            if not url or not e.id:
                continue
            try:
                def_id = self._site_def_id(self.ctx.site_engine.get_by_url(url))
            except Exception:
                def_id = ""
            if def_id:
                groups[def_id].append(int(e.id))
        removed = 0
        for def_id, ids in groups.items():
            if len(ids) <= 1:
                continue
            keep = max(ids)
            drop = [sid for sid in ids if sid != keep]
            for sid in drop:
                with contextlib.suppress(Exception):
                    self._site_repo.delete(sid)
                    removed += 1
            self.ctx.info(f"[CookieCloud]站点去重 [{def_id}] 保留 id={keep}，删除 {len(drop)} 条重复")
        if removed:
            with contextlib.suppress(Exception):
                self.sites.refresh()
        return removed

    def _probe_domain(self, domain: str, cookie_str: str, attempts: int = 3) -> tuple[float, float]:
        """多次探测域名，返回 (成功率, 平均延时ms)。

        成功 = HTTP 200 且判定为已登录。全部失败时平均延时为 inf。
        用于比较多个候选域名的可用性/稳定性/延时。"""
        url = domain if domain.startswith("http") else f"https://{domain}"
        ok = 0
        latencies: list[float] = []
        for _ in range(max(1, attempts)):
            start = time.time()
            try:
                res = HttpClient(
                    config=HttpClientConfig(
                        default_headers={"User-Agent": get_ua()},
                        timeout=10.0,
                        connect_timeout=5.0,
                    )
                ).get(url=url, auth=CookieAuth(cookie_str) if cookie_str else None, raise_for_status=False)
                if res is not None and res.status_code == 200 and is_logged_in(res.text):
                    ok += 1
                    latencies.append((time.time() - start) * 1000)
            except Exception as e:
                self.ctx.debug(f"[CookieCloud]探测 {url} 失败: {e}")
        rate = ok / max(1, attempts)
        avg_latency = sum(latencies) / len(latencies) if latencies else float("inf")
        return rate, avg_latency

    def _select_best_site_domain(self, site_info: dict, synced_domains: dict[str, str]) -> None:
        """在多个候选域名（CookieCloud 同步域名 + 当前签到域名 + 配置别名）中，
        综合「可用性、稳定性(成功率)、延时」选出最优域名并更新站点签到地址。

        含迟滞：当前域名足够好时不因微小延时差异来回切换。"""
        strict_url = site_info.get("strict_url", "")
        sid = int(site_info.get("id") or 0)
        if not sid:
            return
        current_base = StringUtils.get_url_domain(strict_url)

        # 汇总候选：base_domain -> (探测用 host, 对应 cookie)
        hosts: dict[str, str] = {}
        cookies: dict[str, str] = {}
        synced_bases: set[str] = set()
        any_cookie = next(iter(synced_domains.values()), "")

        def _base(d: str) -> str:
            return StringUtils.get_url_domain(d if d.startswith("http") else f"https://{d}")

        for d, ck in synced_domains.items():
            b = _base(d)
            if b and b not in hosts:
                hosts[b], cookies[b] = d, ck
                synced_bases.add(b)
        if current_base and current_base not in hosts:
            hosts[current_base], cookies[current_base] = current_base, any_cookie
        try:
            site_def = self.ctx.site_engine.get_by_url(strict_url)
        except Exception:
            site_def = None
        for alias in self._site_def_aliases(site_def):
            b = _base(alias)
            if b and b not in hosts:
                hosts[b], cookies[b] = alias, any_cookie

        # 只有一个候选域名，无需比较
        if len(hosts) <= 1:
            return

        scored: list[tuple[float, float, str]] = []  # (成功率, 延时, base)
        for base, host in hosts.items():
            rate, latency = self._probe_domain(host, cookies.get(base, ""))
            self.ctx.debug(f"[CookieCloud]候选域名 {host} 成功率={rate:.0%} 平均延时={latency:.0f}ms")
            if rate > 0:
                scored.append((rate, latency, base))
        if not scored:
            return
        scored.sort(key=lambda x: (-x[0], x[1]))
        best_rate, best_latency, best_base = scored[0]

        # 迟滞：当前域名可用且成功率不低于最优、延时未被显著超越（>30%）→ 保持不变
        current_entry = next((s for s in scored if s[2] == current_base), None)
        if current_entry is not None:
            cur_rate, cur_latency = current_entry[0], current_entry[1]
            if cur_rate >= best_rate - 1e-9 and best_latency >= cur_latency * 0.7:
                return

        if best_base == current_base:
            return

        entity = self._site_repo.get_by_id(sid)
        if not entity:
            return
        best_host = hosts[best_base]
        new_url = best_host if best_host.startswith("http") else f"https://{best_host}"
        old_url = entity.sign_url
        entity.sign_url = new_url
        if best_base in synced_bases and cookies.get(best_base):
            entity.cookie = cookies[best_base]
        self._site_repo.update(entity)
        self.ctx.info(
            f"[CookieCloud]站点 {site_info.get('name', strict_url)} 择优切换签到地址："
            f"{old_url} → {new_url}（成功率 {best_rate:.0%}，延时 {best_latency:.0f}ms）"
        )

    def _process_cookies(self, contents: dict):
        domain_cookies = self._store_cookies_to_cache(contents)

        # 同步前先清理历史重复站点（同一站点仅保留最后一条），再配合下方去重逻辑防止新增重复
        with contextlib.suppress(Exception):
            self._dedupe_existing_sites()

        results: list[dict] = []
        updated_ids: set[int] = set()
        # 收集每个已匹配站点对应的所有同步域名及其 Cookie，用于同步后择优选择签到域名
        site_candidates: dict[int, dict] = {}
        # 新增站点优先级递增计数器（缓存在同步期间不刷新，需本地自增避免重复）
        pt_sites = self.sites.get_sites(public=False)
        next_pri = max((int(s.get("pri", 0)) for s in pt_sites), default=0) + 1 if pt_sites else 1
        # 站点定义 id -> 已存在站点 id 映射，用于新增去重。
        # 依据站点 JSON 配置（domain + domain_aliases）判定是否同一站点，
        # 从而识别 hhanclub.net 与 hhan.club 这类同站不同域名的情况，避免重复新增。
        existing_by_defid: dict[str, int] = {}
        for _e in self._site_repo.list_all():
            _url = _e.sign_url or _e.rss_url
            if not _url or not _e.id:
                continue
            _defid = self._site_def_id(self.ctx.site_engine.get_by_url(_url))
            if _defid:
                existing_by_defid.setdefault(_defid, int(_e.id))

        for domain_url, cookie_str in domain_cookies.items():
            matched_sites = []
            try:
                matched_sites = self._find_matching_sites(domain_url)
                if matched_sites:
                    for site_info in matched_sites:
                        sid = int(site_info.get("id") or 0)
                        site_name = site_info.get("name", domain_url)
                        if not sid:
                            continue
                        entry = site_candidates.setdefault(sid, {"site_info": site_info, "domains": {}})
                        entry["domains"][domain_url] = cookie_str
                        if sid not in updated_ids:
                            updated_ids.add(sid)
                            old_cookie = site_info.get("cookie") or ""
                            # Cookie 无变化则不更新、不记录，避免“显示已更新但实际未变”
                            if cookie_str and cookie_str != old_cookie:
                                self._site_repo.update_cookie_ua(sid, cookie=cookie_str)
                                results.append(
                                    {
                                        "action": "更新",
                                        "domain": domain_url,
                                        "site": site_name,
                                        "status": "成功",
                                        "reason": f"更新同步域名 {domain_url} 的 Cookie",
                                    }
                                )
                else:
                    site_url = f"https://{domain_url}"
                    site_def = self.ctx.site_engine.get_by_url(site_url)
                    if not site_def:
                        if self._index_helper is not None:
                            site_def = self._index_helper.get_indexer_info(domain_url)
                    if not site_def:
                        results.append(
                            {
                                "action": "新增",
                                "domain": domain_url,
                                "site": "-",
                                "status": "跳过",
                                "reason": "无匹配站点配置",
                            }
                        )
                        continue

                    if not self._verify_cookie(domain_url, cookie_str):
                        results.append(
                            {
                                "action": "新增",
                                "domain": domain_url,
                                "site": site_def.name
                                if hasattr(site_def, "name")
                                else site_def.get("name", domain_url),
                                "status": "失败",
                                "reason": "Cookie 验证失败",
                            }
                        )
                        continue

                    site_name = site_def.name if hasattr(site_def, "name") else site_def.get("name", domain_url)
                    # 去重：依据站点 JSON 配置的唯一 id 判定是否同一站点（覆盖同站不同域名/别名），
                    # 若已存在则仅更新其 Cookie，不重复新增
                    def_id = self._site_def_id(site_def)
                    existing_id = existing_by_defid.get(def_id) if def_id else None
                    if existing_id:
                        # existing_id == -1 表示本次同步刚新增；已在 updated_ids 表示本次已处理过。
                        if existing_id > 0 and existing_id not in updated_ids:
                            updated_ids.add(existing_id)
                            entity = self._site_repo.get_by_id(existing_id)
                            old_cookie = (entity.cookie if entity else "") or ""
                            # Cookie 无变化则不更新、不记录
                            if cookie_str and cookie_str != old_cookie:
                                self._site_repo.update_cookie_ua(existing_id, cookie=cookie_str)
                                results.append(
                                    {
                                        "action": "更新",
                                        "domain": domain_url,
                                        "site": site_name,
                                        "status": "成功",
                                        "reason": f"已存在同一站点，更新同步域名 {domain_url} 的 Cookie",
                                    }
                                )
                        continue
                    # 新增站点使用 Cookie 实际来源域名（已通过登录校验），避免写入不可用的规范域名
                    site_domain = f"https://{domain_url}"
                    site_pri = next_pri
                    next_pri += 1
                    self._site_repo.insert(
                        SiteEntity(
                            name=site_name,
                            pri=site_pri,
                            sign_url=site_domain,
                            cookie=cookie_str,
                            rss_uses=SiteUseType.STATISTIC.value,
                        )
                    )
                    if def_id:
                        existing_by_defid[def_id] = -1
                    results.append(
                        {
                            "action": "新增",
                            "domain": domain_url,
                            "site": site_name,
                            "status": "成功",
                            "reason": f"新增站点，同步域名 {domain_url}",
                        }
                    )
            except Exception as e:
                results.append(
                    {
                        "action": "更新" if matched_sites else "新增",
                        "domain": domain_url,
                        "site": "-",
                        "status": "失败",
                        "reason": str(e),
                    }
                )
                self.ctx.error(f"处理域名 {domain_url} 时出错: {e}")

        # 同步完成后，对存在多个候选域名的站点，择优选择签到域名（可用性/稳定性/延时）
        for entry in site_candidates.values():
            with contextlib.suppress(Exception):
                self._select_best_site_domain(entry["site_info"], entry["domains"])

        update_ok = sum(1 for r in results if r["action"] == "更新" and r["status"] == "成功")
        add_ok = sum(1 for r in results if r["action"] == "新增" and r["status"] == "成功")
        failed = sum(1 for r in results if r["status"] in ("失败", "跳过"))

        if updated_ids or add_ok:
            self.sites.refresh()
        failed = sum(1 for r in results if r["status"] in ("失败", "跳过"))

        summary = {
            "id": int(time.time() * 1000),
            "time": time.strftime("%Y-%m-%d %H:%M:%S"),
            "update_ok": update_ok,
            "add_ok": add_ok,
            "failed": failed,
            "results": results,
        }
        try:
            existing = self.ctx.read_data("sync_history.json") or []
            if not isinstance(existing, list):
                existing = []
            existing.insert(0, summary)
            if len(existing) > 10:
                existing = existing[:10]
            self.ctx.write_data("sync_history.json", JsonUtils.dumps(existing, ensure_ascii=False, indent=2))
        except Exception as e:
            self.ctx.warn(f"[CookieCloud]写入同步记录失败: {e}")

        return update_ok, add_ok, failed, results

    def _verify_cookie(self, domain_url: str, cookie_str: str) -> bool:
        site_url = f"https://{domain_url}"
        ua = get_ua()

        site_def = self.ctx.site_engine.get_by_url(site_url)
        auth_type = ""
        if site_def:
            api_cfg = getattr(site_def, "api", None)
            if api_cfg and getattr(api_cfg, "auth", None):
                auth_type = api_cfg.auth.get("type", "") or ""
        if site_def and auth_type in ("", "cookie", "csrf"):
            user_config = {
                "cookie": cookie_str,
                "api_key": "",
                "bearer_token": "",
                "ua": ua,
                "headers": {},
                "proxy": False,
            }
            success, msg, _ = self.ctx.site_engine.test_connection(site_url, user_config)
            if not success:
                self.ctx.warn(f"[CookieCloud]Cookie 失效 {domain_url}: {msg}")
            return success

        # 无站点定义，或混合认证站点（api_key/bearer，cookie 仅用于 HTML 页面）：
        # 引擎 test_connection 校验的是 API 凭证，无法验证 cookie，改为校验页面登录态
        try:
            res = HttpClient(
                config=HttpClientConfig(default_headers={"User-Agent": ua}),
            ).get(url=site_url, auth=CookieAuth(cookie_str))
            if res and res.status_code == 200 and is_logged_in(res.text):
                return True
            self.ctx.warn(f"[CookieCloud]Cookie 失效 {domain_url}")
            return False
        except HttpClientError as e:
            self.ctx.warn(f"[CookieCloud]请求异常 {domain_url}: {e}")
            return False
        except Exception as e:
            self.ctx.warn(f"[CookieCloud]验证异常 {domain_url}: {e}")
            return False

    def _store_local_storage(self, contents: dict) -> int:
        """把 CookieCloud local_storage_data 写入 Redis（按父域 key），返回成功站点数."""
        local_storage = contents.get("local_storage_data") or {}
        synced = 0
        for site, storage in local_storage.items():
            try:
                if not storage:
                    continue
                if not self._check_domain(site):
                    continue
                domain_url = ".".join(site.split(".")[-2:])
                self._cache.set(f"local_storage:{domain_url}", JsonUtils.dumps(storage))
                synced += 1
            except Exception as e:
                self.ctx.error(f"处理 LocalStorage {site} 时出错: {e}")
        return synced

    def _local_storage_save(self):
        self.ctx.info("开始同步 LocalStorage ...")
        contents, msg, flag = self._download_data()
        if not flag:
            self.ctx.error(msg)
            return
        if not contents:
            self.ctx.info("未从 CookieCloud 获取到数据")
            return

        synced = self._store_local_storage(contents)
        self.ctx.info(f"LocalStorage 同步 Redis 成功，共同步 {synced} 个站点")

    def _send_message(self, msg):
        self.ctx.notify(
            title="[CookieCloud 同步任务执行完成]",
            text=msg,
        )
