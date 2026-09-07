"""站点解析健康度自检服务.

用途：站点页面改版会让 html.conf 选择器 / api torrent_attr 字段静默失效
（如观众新版 seeders、M-Team 错误 JSON），刷流行为异常前无法察觉。
本服务每日/手动采样各站 RSS 真实种子，跑真实解析链路：

- HTML 站点：独立统计每个配置选择器命中数，零命中即降级；
- API 站点：解析成功/失败计数，业务失败(限流/鉴权)计入 attr_fail；

结果按站点每日落 SITE_PARSE_HEALTH，供前端展示与状态变更提醒。
"""

import datetime
import json
import urllib.error
import urllib.parse
import urllib.request
from typing import Any
from xml.dom import minidom

import log
from app.db.repositories.site_parse_health_repository import SiteParseHealthRepository
from app.message.message import Message
from app.sites.engine import TorrentAttrFetchError
from app.sites.site_cache import SiteCache
from app.sites.siteconf import SiteConf

DEFAULT_SAMPLE_SIZE = 5


class SiteParseHealthService:
    """站点解析健康度自检."""

    STATUS_OK = "ok"
    STATUS_DEGRADED = "degraded"
    STATUS_INVALID = "invalid"
    STATUS_SKIPPED = "skipped"
    STATUS_AUTH_ERROR = "auth_error"
    RE_ALERT_INTERVAL_DAYS = 7

    def __init__(
        self,
        site_cache: SiteCache | None = None,
        siteconf: SiteConf | None = None,
        repo: SiteParseHealthRepository | None = None,
        message: Message | None = None,
        sample_size: int = DEFAULT_SAMPLE_SIZE,
    ):
        self._cache = site_cache or SiteCache()
        self._siteconf = siteconf or SiteConf(self._cache._site_engine)
        self._repo = repo or SiteParseHealthRepository()
        self._message = message
        self._sample_size = sample_size

    # 登录页/鉴权失败特征：凭据问题，不属页面改版告警
    _AUTH_KEYWORDS = ("非法", "未登录", "未授权", "unauthorized", "forbidden")

    # 限流特征：HTTP 状态码或正文提示。限流是临时态，不能当结构失效告警
    _RATE_LIMIT_KEYWORDS = ("429", "503", "too many", "请求间隔", "访问频繁", "rate limit", "ratelimit")

    # ---- RSS 采样 ----------------------------------------------------------

    def _fetch_rss(self, site_info: dict) -> tuple[str, bool, bool]:
        """获取 RSS 文本，返回 (内容, 是否登录页/鉴权失败, 是否限流)."""
        rssurl = site_info.get("rssurl") or ""
        if not rssurl:
            return "", False, False
        headers = {"User-Agent": site_info.get("ua") or ""}
        cookie = site_info.get("cookie") or ""
        if cookie:
            headers["Cookie"] = cookie
        req = urllib.request.Request(rssurl, headers=headers)
        try:
            with urllib.request.urlopen(req, timeout=20) as resp:
                text = resp.read().decode("utf-8", "ignore")
                final_url = str(resp.url).lower()
        except urllib.error.HTTPError as e:
            if e.code in (429, 503):
                log.warn(f"[解析自检]{site_info.get('name')} RSS 限流（HTTP {e.code}），跳过")
                return "", False, True
            log.warn(f"[解析自检]{site_info.get('name')} RSS 获取失败: {e}")
            return "", False, False
        except Exception as e:  # noqa: BLE001
            log.warn(f"[解析自检]{site_info.get('name')} RSS 获取失败: {e}")
            return "", False, False
        # 未登录/Cookie 过期：重定向到 login 页，或返回登录表单而非 RSS
        if "login" in final_url:
            return "", True, False
        if "<channel" not in text and any(kw in text for kw in ("takelogin", "login.php", "请登录")):
            return "", True, False
        # 正文限流提示（如 NexusPHP "请调整RSS请求间隔"）
        if "<channel" not in text and any(kw in text for kw in self._RATE_LIMIT_KEYWORDS):
            return "", False, True
        return text, False, False

    def _detail_links(self, site_info: dict, rss_text: str) -> list[str]:
        """从 RSS XML 提取形如详情页的 link（能被站点定义解析出 tid 或 /detail 路径）."""
        try:
            dom = minidom.parseString(rss_text)
        except Exception as e:  # noqa: BLE001
            log.warn(f"[解析自检]{site_info.get('name')} RSS 解析失败: {e}")
            return []
        links: list[str] = []
        for link_node in dom.getElementsByTagName("link"):
            text = (link_node.firstChild.nodeValue if link_node.firstChild else "") or ""
            text = text.strip()
            if not text.startswith("http"):
                continue
            if any(seg in text.lower() for seg in ("/detail/", "details.php", "/torrent/", "id=")):
                links.append(text)
        # 去重保序，最多 sample_size
        seen: list[str] = []
        for link in links:
            if link not in seen:
                seen.append(link)
            if len(seen) >= self._sample_size:
                break
        return seen

    # ---- 单站点自检 ---------------------------------------------------------

    def _user_config(self, site_info: dict) -> dict:
        return {
            "cookie": site_info.get("cookie") or "",
            "api_key": site_info.get("api_key") or "",
            "bearer_token": site_info.get("bearer_token") or "",
            "ua": site_info.get("ua") or "",
            "headers": site_info.get("headers") or {},
            "proxy": bool(site_info.get("proxy")),
            "chrome": bool(site_info.get("chrome")),
            "browser_persistent": bool(site_info.get("browser_persistent")),
        }

    def _probe(self, site_info: dict, page_url: str) -> dict:
        """对单个真实种子单次抓取并解析，返回 ok/失败/鉴权失败 与选择器命中."""
        result: dict[str, Any] = {"ok": False, "auth": False, "selector_stats": None}
        uc = self._user_config(site_info)
        site_def = self._cache._site_engine.get_by_url(page_url)
        # HTML 站点：html_selector_stats 一次抓取同时给出选择器命中与属性，避免二次抓取触发反爬
        if site_def and site_def.html and site_def.html.conf:
            stats = self._cache._site_engine.html_selector_stats(page_url, uc)
            if stats.get("auth"):
                result["auth"] = True
                return result
            if not stats.get("fetched"):
                err = str(stats.get("error", "empty"))
                result["error"] = err
                # 空响应/限流（429/503/限流文案）：临时态（多为反爬/限流返回空页），不算解析失败；
                # "parse"（有内容但解析失败）才视为真实失败
                if err == "empty" or any(kw in err.lower() for kw in self._RATE_LIMIT_KEYWORDS):
                    result["limited"] = True
                return result
            result["ok"] = True
            result["free"] = bool(stats.get("free"))
            result["peer_count"] = stats.get("peer_value")
            result["selector_stats"] = stats
            return result
        # API 站点：check_torrent_attr 一次抓取解析，detail 收集配置字段是否存在
        try:
            detail = {}
            attr = self._siteconf.check_torrent_attr(
                torrent_url=page_url,
                cookie=uc["cookie"],
                api_key=uc["api_key"],
                bearer_token=uc["bearer_token"],
                ua=uc["ua"],
                headers=uc.get("headers") or {},
                proxy=uc["proxy"],
                chrome=uc["chrome"],
                browser_persistent=uc["browser_persistent"],
                detail=detail,
            )
            result["ok"] = attr is not None
            if attr:
                result["free"] = bool(attr.get("free"))
                result["peer_count"] = attr.get("peer_count", 0)
            # 字段漂移探测：配置的 free/peer 键在响应中缺失 → 结构信号
            api_keys = detail.get("api_keys") or {}
            if api_keys:
                result["selector_stats"] = {
                    "selectors": {f"api.{k}": (1 if present else 0) for k, present in api_keys.items()},
                }
        except TorrentAttrFetchError as e:
            err = str(e)
            result["error"] = err[:200]
            err_lower = err.lower()
            # 鉴权类失败（API Key 缺失/失效等）：单独归类，不计入解析失败
            if any(kw in err_lower for kw in self._AUTH_KEYWORDS):
                result["auth"] = True
            # 限流（429/503/限流文案）：临时态，不算解析失败
            elif any(kw in err_lower for kw in self._RATE_LIMIT_KEYWORDS):
                result["limited"] = True
        return result

    def check_site(self, site_info: dict) -> dict:
        """单站点自检：采样 → 逐样本解析 → 聚合判定状态."""
        site_id = site_info.get("id")
        site_name = site_info.get("name") or ""
        today = datetime.date.today().strftime("%Y-%m-%d")
        if not site_id:
            return {}
        rss_text, rss_auth, rss_limited = self._fetch_rss(site_info)
        result: dict[str, Any] = {
            "site_id": site_id,
            "site_name": site_name,
            "status": self.STATUS_SKIPPED,
            "sample_count": 0,
            "attr_ok": 0,
            "attr_fail": 0,
            "auth_fail": 0,
            "issues": [],
            "selectors": {},
        }
        if rss_auth:
            result["status"] = self.STATUS_AUTH_ERROR
            result["issues"] = ["RSS 访问被重定向/渲染为登录页（未登录 / 凭据失效）"]
            log.info(f"[解析自检]{site_name} RSS 为登录页（status=auth_error）")
            self._persist_and_notify(result)
            return result
        if rss_limited:
            # 限流是临时态，不算异常也不告警
            result["status"] = self.STATUS_SKIPPED
            result["issues"] = ["RSS 限流，跳过本轮"]
            log.info(f"[解析自检]{site_name} RSS 限流，跳过本轮（status=skipped）")
            self._repo.upsert(site_id, today, self._to_row(result))
            return result
        samples = self._detail_links(site_info, rss_text)
        if not samples:
            log.info(f"[解析自检]{site_name} RSS 无详情链接样本，跳过（status=skipped）")
            self._repo.upsert(site_id, today, self._to_row(result))
            return result

        selector_hits: dict[str, int] = {}
        peer_samples = 0
        limited_count = 0
        for url in samples:
            probe = self._probe(site_info, url)
            if probe.get("auth"):
                result["auth_fail"] += 1
                result["issues"].append({"url": url[:120], "error": "未登录/凭据失效/访问受限"})
                continue
            if probe.get("limited"):
                # 限流样本：临时态，既不算成功也不算失败
                limited_count += 1
                continue
            if probe["ok"]:
                result["attr_ok"] += 1
                if probe.get("peer_count") is not None:
                    peer_samples += 1
                stats = probe.get("selector_stats") or {}
                for key, hit in (stats.get("selectors") or {}).items():
                    selector_hits[key] = selector_hits.get(key, 0) + int(hit)
            else:
                result["attr_fail"] += 1
                result["issues"].append(f"详情抓取失败：{probe.get('error') or 'unknown'}")
        result["sample_count"] = len(samples)
        result["selectors"] = selector_hits

        # 有效样本（排除限流）：限流样本不进入成败判定
        effective = len(samples) - limited_count
        if effective <= 0:
            result["status"] = self.STATUS_SKIPPED
            result["issues"] = [f"本轮 {limited_count} 个样本均被限流，跳过"]
            self._repo.upsert(site_id, today, self._to_row(result))
            return result

        # 状态判定（限流/鉴权失败的样本不算解析失败，避免误判）
        if result["auth_fail"] >= effective:
            # 全部样本为登录页/鉴权失败：凭据问题，不是页面改版
            result["status"] = self.STATUS_AUTH_ERROR
            result["issues"] = ["详情页均不可访问（未登录 / 凭据失效 / 访问受限）"]
        elif result["attr_fail"] >= effective:
            result["status"] = self.STATUS_INVALID
        else:
            issues: list[str] = []
            # HTML：PEER_COUNT 每页必有做种栏，一次都不命中 → 选择器疑似失效
            # （FREE/2XFREE/HR 按种子实际徽标而定，随机样本零命中属正常，不作为降级依据）
            if selector_hits.get("PEER_COUNT", -1) == 0 and result["attr_ok"] > 0:
                issues.append("选择器 PEER_COUNT 全部未命中")
            # API：配置的 free/peer 字段在响应中不存在 → 配置漂移（如 Rousi peer_count 恒 0）
            missing_api = sorted(
                {k.removeprefix("api.") for k, v in selector_hits.items() if k.startswith("api.") and v == 0}
            )
            if missing_api:
                issues.append(f"接口字段缺失: {'、'.join(missing_api)}")
            if result["issues"]:
                issues.append(f"{len(result['issues'])} 个样本解析失败")
            if issues:
                result["status"] = self.STATUS_DEGRADED
                result["issues"] = issues
            else:
                result["status"] = self.STATUS_OK
        self._persist_and_notify(result)
        return result

    def _persist_and_notify(self, result: dict) -> None:
        """先读昨日状态，再落库，再决定是否告警（避免与自身当日记录比较）."""
        site_id = int(result.get("site_id") or 0)
        previous = self._repo.latest(site_id)
        today = datetime.date.today().strftime("%Y-%m-%d")
        row = self._to_row(result)
        # 非告警日也要把上次告警时间继承下来，避免 detail 覆盖导致 7 天复读失效
        if previous and getattr(previous, "DETAIL", None):
            try:
                prev_detail = json.loads(previous.DETAIL or "") or {}
            except (TypeError, ValueError):
                prev_detail = {}
            last_alert = prev_detail.get("last_alert_date") or ""
            if last_alert:
                detail = json.loads(row["detail"])
                detail.setdefault("last_alert_date", last_alert)
                row["detail"] = json.dumps(detail, ensure_ascii=False)
        self._repo.upsert(site_id, today, row)
        self._notify_transition(result, previous)

    def _notify_transition(self, result: dict, previous) -> None:
        """结构异常（降级/失效）连续两轮确认后推送；异常持续时每 RE_ALERT_INTERVAL_DAYS 天复读一次."""
        new_status = result.get("status")
        if new_status == self.STATUS_AUTH_ERROR:
            log.warn(
                f"[解析自检]{result.get('site_name')} 凭据失效（不告警）："
                f"{result.get('issues')}"
            )
            return
        if new_status not in (self.STATUS_DEGRADED, self.STATUS_INVALID):
            return
        prev_status = (getattr(previous, "STATUS", None) or "").strip() if previous else ""
        prev_date = (getattr(previous, "CHECK_DATE", None) or "") if previous else ""
        today = datetime.date.today()
        today_str = today.strftime("%Y-%m-%d")
        # 上次告警时间（存在历史行 DETAIL 中），用于异常持续时按间隔复读而非每日打扰
        last_alert_date = ""
        if previous and getattr(previous, "DETAIL", None):
            try:
                last_alert_date = (json.loads(previous.DETAIL) or {}).get("last_alert_date", "") or ""
            except (TypeError, ValueError):
                last_alert_date = ""

        def _days_between(d1: str, d2: str) -> int:
            try:
                return (datetime.date.fromisoformat(d2) - datetime.date.fromisoformat(d1)).days
            except (TypeError, ValueError):
                return 0

        if prev_status not in (self.STATUS_DEGRADED, self.STATUS_INVALID, self.STATUS_AUTH_ERROR):
            # 昨日正常/无记录，首次异常只记录不推送（等明日连续确认，防抖）
            log.warn(
                f"[解析自检]{result.get('site_name')} 首次异常 {new_status}（暂不推送，待连续确认）"
            )
            return
        if prev_date >= today_str:
            return  # 当日已跑过，不重复处理
        # 昨日异常：确认连续两轮；若近期已推送过则按间隔静默（7 天复读一次）
        if last_alert_date and last_alert_date < today_str:
            if _days_between(last_alert_date, today_str) < self.RE_ALERT_INTERVAL_DAYS:
                log.info(
                    f"[解析自检]{result.get('site_name')} 异常持续中（{last_alert_date} 已提醒过），静默"
                )
                return
        self._push_alert(result, new_status, first=True)

    def _push_alert(self, result: dict, new_status: str, first: bool = True) -> None:
        """推送站点解析告警，并在结果 DETAIL 记录 last_alert_date 以便按间隔复读."""
        site_id = int(result.get("site_id") or 0)
        site_name = result.get("site_name") or ""
        issues = "；".join(str(i) for i in (result.get("issues") or [])) or "未知问题"
        today_str = datetime.date.today().strftime("%Y-%m-%d")
        log.warn(f"[解析自检]{site_name} 连续异常 -> {new_status}：{issues}，推送告警")
        if self._message is not None:
            try:
                self._message.send_site_parse_health_message(
                    title=f"站点解析告警：{site_name}",
                    text=(
                        f"站点 {site_name} 详情页解析连续「{new_status}」。\n"
                        f"问题：{issues}\n"
                        "可能原因：站点页面改版导致选择器失效，请到「站点维护」检查或更新站点定义。"
                    ),
                )
            except Exception as e:  # noqa: BLE001
                log.error(f"[解析自检]发送站点告警消息失败: {e}")
        # 落库告警时间（upsert 当日行）
        try:
            row = self._to_row(result)
            detail = json.loads(row["detail"])
            detail["last_alert_date"] = today_str
            row["detail"] = json.dumps(detail, ensure_ascii=False)
            self._repo.upsert(site_id, today_str, row)
        except Exception as e:  # noqa: BLE001
            log.error(f"[解析自检]记录告警时间失败: {e}")

    @staticmethod
    def _to_row(result: dict) -> dict:
        return {
            "site_name": result.get("site_name", ""),
            "status": result.get("status", SiteParseHealthService.STATUS_OK),
            "sample_count": result.get("sample_count", 0),
            "attr_ok": result.get("attr_ok", 0),
            "attr_fail": result.get("attr_fail", 0),
            "detail": json.dumps(
                {
                    "issues": result.get("issues", []),
                    "selectors": result.get("selectors", {}),
                    "auth_fail": result.get("auth_fail", 0),
                },
                ensure_ascii=False,
            ),
        }

    def check_all(self, site_ids: list[int] | None = None) -> list[dict]:
        """对全部启用（刷流/订阅/统计/签到任一）且可解析的站点执行自检."""
        engine = self._cache._site_engine
        candidates = list((getattr(self._cache, "_site_by_ids", None) or {}).values())
        if not candidates:
            # 测试桩无全量索引时，用启用站点索引兜底
            for attr in ("_brush_sites", "_rss_sites", "_statistic_sites", "_signin_sites"):
                candidates.extend(list(getattr(self._cache, attr, None) or []))
        results = []
        for site_info in candidates:
            sid = site_info.get("id")
            if site_ids and sid not in site_ids:
                continue
            if not (site_info.get("rssurl")):
                continue
            if not (
                site_info.get("brush_enable")
                or site_info.get("rss_enable")
                or site_info.get("statistic_enable")
                or not site_info.get("public")
            ):
                continue
            site_def = engine.get_by_url(site_info.get("rssurl") or "") or engine.get_by_name(
                site_info.get("name") or ""
            )
            if not site_def:
                continue
            if not (site_def.html or site_def.torrent_attr):
                continue
            try:
                result = self.check_site(site_info)
                results.append(result)
                if result.get("status") in (self.STATUS_DEGRADED, self.STATUS_INVALID):
                    log.warn(
                        f"[解析自检]{result.get('site_name')} 状态={result.get('status')}，问题={result.get('issues')}"
                    )
            except Exception as e:  # noqa: BLE001
                log.error(f"[解析自检]{site_info.get('name')} 自检异常: {e}")
        return results

    # ---- 对外查询 -----------------------------------------------------------

    def latest_all(self) -> list[dict]:
        rows = self._repo.latest_all()
        return [self._row_dict(r) for r in rows]

    def history(self, site_id: int, limit: int = 30) -> list[dict]:
        rows = self._repo.history(site_id, limit)
        return [self._row_dict(r) for r in rows]

    @staticmethod
    def _row_dict(row) -> dict:
        detail = {}
        if row.DETAIL:
            try:
                detail = json.loads(row.DETAIL)
            except (TypeError, ValueError):
                detail = {"raw": row.DETAIL}
        # 兼容旧数据：issue 可能为 {"url":..,"error":..} 字典，统一转可读字符串
        issues: list[str] = []
        for issue in detail.get("issues", []) or []:
            if isinstance(issue, dict):
                url = (issue.get("url") or "")[:80]
                err = issue.get("error") or ""
                issues.append(f"{url} {err}".strip())
            else:
                issues.append(str(issue))
        return {
            "id": row.ID,
            "site_id": row.SITE_ID,
            "site_name": row.SITE_NAME,
            "check_date": row.CHECK_DATE,
            "status": row.STATUS,
            "sample_count": row.SAMPLE_COUNT,
            "attr_ok": row.ATTR_OK,
            "attr_fail": row.ATTR_FAIL,
            "issues": issues,
            "selectors": detail.get("selectors", {}),
            "created_at": row.CREATED_AT.isoformat() if row.CREATED_AT else "",
        }
