"""
配置驱动的 HTML 站点用户信息解析器

架构自动检测 → 委托对应模块解析：
- NexusPhp → nexus_php.py
- Gazelle  → gazelle.py
- Unit3d   → unit3d.py
- Discuz   → discuz.py
- SmallHorse → small_horse.py
- JSON user_info.type=html → CSS 选择器
"""

from __future__ import annotations

import re
from typing import Any
from urllib.parse import urljoin

from lxml import etree

import log
from app.infrastructure.chrome.challenge import is_challenge
from app.infrastructure.http.auth import CookieAuth
from app.infrastructure.http.client import HttpClient
from app.infrastructure.http.config import HttpClientConfig
from app.sites import engine_tools
from app.sites.siteuserinfo import discuz, gazelle, nexus_php, small_horse, unit3d
from app.utils import StringUtils
from app.utils.browser_mode import build_browser_mode
from app.utils.config_tools import get_proxies
from app.utils.json_utils import JsonUtils

_ARCH_PARSERS = [
    (gazelle.is_gazelle, gazelle.parse),
    (unit3d.is_unit3d, unit3d.parse),
    (discuz.is_discuz, discuz.parse),
    (small_horse.is_small_horse, small_horse.parse),
    (nexus_php.is_nexusphp, nexus_php.parse),
]


class ConfigHtmlUserInfo:
    order = 5

    def __init__(
        self,
        site_def: Any,
        site_name: str,
        url: str,
        site_cookie: str,
        site_engine: Any,
        site_headers: dict | None = None,
        ua: str = "",
        emulate: bool = False,
        proxy: bool = False,
        session: Any = None,
        json_data: str | None = None,
        api_key: str | None = None,
        bearer_token: str | None = None,
    ) -> None:
        self.site_name: str = site_name
        self.site_url: str = url
        self._def: Any = site_def
        self._cookie: str = site_cookie
        self._headers: dict = site_headers or {}
        self._ua: str = ua
        self._emulate: bool = emulate
        self._proxy: bool = proxy
        self._proxies: Any = get_proxies() if proxy else None
        self._session: Any = session
        self._index_html: str = json_data or ""
        self._base_url_str: str = self.site_url.rstrip("/") if self.site_url else ""
        self._site_engine: Any = site_engine
        self._api_key: str | None = api_key
        self._bearer_token: str | None = bearer_token

        self.username: str | None = None
        self.userid: str | None = None
        self.user_level: str | None = None
        self.join_at: str | None = None
        self.bonus: float = 0.0
        self.upload: int = 0
        self.download: int = 0
        self.ratio: float = 0.0
        self.seeding: int = 0
        self.seeding_size: int = 0
        self.seeding_info: str = "[]"
        self.leeching: int = 0
        self.leeching_size: int = 0
        self.message_unread: int = 0
        self.message_unread_contents: list = []
        self.err_msg: str | None = None
        self.site_favicon: str | None = None

    @classmethod
    def match(cls, _html_text: str) -> bool:
        return False

    @property
    def schema(self) -> str:
        return "ConfigHtml"

    def site_schema(self) -> str:
        return "ConfigHtml"

    def parse(self) -> None:
        cfg = self._def.user_info if isinstance(self._def.user_info, dict) else {}
        if cfg.get("type") == "html" and cfg.get("fields"):
            nexus_php._parse_userid(self)
            nexus_php._parse_base_info(self)
            self._parse_fields(cfg)
            self.user_level = self.user_level or ""
            self._parse_seeding(cfg)
            return
        for check, parser in _ARCH_PARSERS:
            if check(self):
                parser(self)
                break
        if cfg.get("seeding") and not self.seeding:
            self._parse_seeding(cfg)

    def _parse_fields(self, cfg: dict) -> None:
        fields = cfg.get("fields", {})
        if not fields:
            return
        if not self.userid:
            brief_page = cfg.get("brief_page", "")
            if brief_page:
                brief_url = urljoin(self._base_url_str + "/", brief_page)
                brief_html = self._fetch_html(brief_url, use_ajax_headers=False)
                if brief_html:
                    m = re.search(r"user_detail\.php\?uid=(\d+)", brief_html)
                    if m and m.group(1):
                        self.userid = m.group(1)
        page = cfg.get("page")
        html_text = self._index_html
        if page:
            if not self.userid and "{userid}" in page:
                brief_page = cfg.get("brief_page", "")
                if brief_page:
                    brief_url = urljoin(self._base_url_str + "/", brief_page)
                    brief_html = self._fetch_html(brief_url, use_ajax_headers=False)
                    if brief_html:
                        m = re.search(r"user_detail\.php\?uid=(\d+)", brief_html)
                        if m and m.group(1):
                            self.userid = m.group(1)
            if self.userid or "{userid}" not in page:
                url = urljoin(self._base_url_str + "/", page.format(userid=self.userid or ""))
                html_text = self._fetch_html(url, use_ajax_headers=False)
        if not html_text:
            return
        doc: Any = etree.HTML(html_text)
        if doc is None:
            return
        for fname, fcfg in fields.items():
            val = self._extract_field(doc, html_text, fcfg)
            if val is not None:
                setattr(self, fname, val)
        if self.upload and self.download and not self.ratio:
            self.ratio = round(self.upload / self.download, 2) if self.download else 0

    def _extract_field(self, doc: Any, html_text: str, cfg: dict) -> Any:
        selector = cfg.get("selector", "")
        extract = cfg.get("extract", "text")
        attr = cfg.get("attribute", "")
        # 空 selector + regex 提取：直接在整页 HTML 上跑正则
        if not selector and extract != "regex":
            return None
        raw = None
        try:
            els = doc.cssselect(selector)
        except Exception:
            els = []
        if not els:
            try:
                els = doc.xpath(selector)
            except Exception:
                els = []
        if els:
            raw = els[0].get(attr, "") if attr else els[0].xpath("string(.)").strip()
        pattern = cfg.get("pattern", "")
        if pattern and raw:
            m = re.search(pattern, str(raw), re.I)
            if m:
                raw = m.group(1) if m.lastindex else m.group(0)
        if not raw and extract == "regex" and pattern and html_text:
            m = re.search(pattern, html_text, re.I)
            if m:
                raw = m.group(1) if m.lastindex else m.group(0)
        if raw is None:
            return None
        values = cfg.get("values", {})
        if values and raw in values:
            raw = values[raw]
        if extract == "filesize":
            return StringUtils.num_filesize(str(raw))
        elif extract == "float":
            return StringUtils.str_float(str(raw))
        elif extract == "int":
            return StringUtils.str_int(str(raw))
        elif extract == "datetime":
            return StringUtils.unify_datetime_str(str(raw))
        elif extract == "text":
            return str(raw).strip()
        return raw

    def _parse_seeding(self, cfg: dict) -> None:
        sc = cfg.get("seeding", {})
        if not sc:
            return
        if sc.get("type") == "api":
            self._parse_seeding_api(sc)
            return
        page = sc.get("page") or "getusertorrentlistajax.php?userid={userid}&type=seeding"
        ls = sc.get("list_selector", "table.torrents tr")
        ss = sc.get("size_selector", "td:nth-child(4)")
        sd = sc.get("seeders_selector", "td:nth-child(5) a")
        uid = self.userid or ""
        pn = 1
        total = 0
        info = []
        has_pagination = "{page}" in page
        while True:
            url = urljoin(self._base_url_str + "/", page.format(userid=str(uid), page=pn))
            referer = f"{self._base_url_str}/userdetails.php?id={uid}" if uid else None
            is_ajax_url = has_pagination or "ajax" in page.lower()
            html_text = self._fetch_html(url, referer=referer, use_ajax_headers=is_ajax_url)
            if not html_text:
                break
            total_regex = sc.get("total_regex")
            total_match = None
            if total_regex:
                m = re.search(total_regex, html_text, re.I)
                if m and m.group(1) and m.group(2):
                    total_match = m
            else:
                for pat in [
                    r"<b>(\d+)</b>条记录 Total: ([\d.]+\s*[KMGT]B)",
                    r"<b>(\d+)</b>\s*条记录，共计<b>([\d.]+\s*[KMGT]B)</b>",
                ]:
                    m = re.search(pat, html_text, re.I)
                    if m and m.group(1) and m.group(2):
                        total_match = m
                        break
            if total_match:
                self.seeding = StringUtils.str_int(total_match.group(1))
                self.seeding_size = StringUtils.num_filesize(total_match.group(2))
                return
            doc: Any = etree.HTML(html_text.replace(r"\/", "/"))
            if doc is None:
                break
            rows = doc.cssselect(ls)
            if not rows:
                try:
                    rows = doc.xpath(ls)
                except Exception:
                    rows = []
                if not isinstance(rows, list):
                    rows = []
            cnt = 0
            for row in rows:
                if row.xpath(".//td[contains(@class,'colhead')]") or row.xpath(".//th"):
                    continue
                try:
                    se = row.cssselect(ss)
                    if not se:
                        continue
                    sd_els = row.cssselect(sd)
                    seeders = StringUtils.str_int(sd_els[0].xpath("string(.)").strip()) if sd_els else 0
                    size = StringUtils.num_filesize(se[0].xpath("string(.)").strip())
                    total += size
                    cnt += 1
                    info.append([seeders, size])
                except Exception as e:  # noqa: BLE001
                    log.debug(f"[SiteConfigUpdater]忽略异常: {e}")
            if cnt == 0 or not has_pagination:
                break
            pn += 1
        self.seeding_size = total
        self.seeding_info = JsonUtils.dumps(info)

    def _parse_seeding_api(self, sc: dict) -> None:
        engine = self._site_engine
        rate_limiter = getattr(engine, "site_limiter", None)
        rate_limiter_engine = rate_limiter.engine if rate_limiter else None
        rl_kwargs = engine_tools._get_rate_limit_kwargs(engine, self._def)
        method = sc.get("method", "GET").upper()
        path_tpl = sc.get("path", "")
        headers = {"User-Agent": self._ua} if self._ua else {}
        total_size = 0
        info = []
        pn = int(sc.get("page_start", 1))
        has_pagination = "{page}" in path_tpl
        items_key = sc.get("response", {}).get("items_key", "data")
        size_field = sc.get("response", {}).get("size_field", "size")
        seeders_field = sc.get("response", {}).get("seeders_field", "seeders")
        total_count_field = sc.get("response", {}).get("total_count_field", "")
        total_count = 0
        while True:
            url = urljoin(self._base_url_str + "/", path_tpl.format(userid=self.userid or "", page=pn))
            if method == "POST":
                body = sc.get("body") or {}
                proxy_url = self._proxies.get("http") if self._proxies else None
                res = HttpClient(
                    config=HttpClientConfig(proxy_url=proxy_url),
                    rate_limiter=rate_limiter_engine,
                ).post(
                    url=url,
                    data=JsonUtils.dumps(body),
                    headers=headers,
                    cookies=self._cookie if self._cookie else None,
                    **rl_kwargs,
                )
            else:
                res = self._fetch_html(url)
            if not res:
                break
            try:
                data = JsonUtils.loads(res) if isinstance(res, str) else res
            except Exception:
                break
            items = self._get_nested(data, items_key.split(".")) if isinstance(data, dict) else []
            if not isinstance(items, list):
                items = []
            for _total, item in enumerate(items, start=1):
                if isinstance(item, dict):
                    raw_size = self._get_nested(item, size_field.split("."))
                    if isinstance(raw_size, str) and not raw_size.isdigit():
                        size_val = StringUtils.num_filesize(raw_size)
                    else:
                        size_val = int(raw_size or 0)
                    seeders = int(self._get_nested(item, seeders_field.split(".")) or 0)
                else:
                    size_val = StringUtils.num_filesize(str(item))
                    seeders = 0
                total_size += size_val
                info.append([seeders, size_val])
            if total_count_field and isinstance(data, dict):
                tc = self._get_nested(data, total_count_field.split("."))
                total_count = int(tc or 0)
            if not has_pagination or len(items) == 0:
                break
            if total_count > 0 and len(info) >= total_count:
                break
            pn += 1
        self.seeding = total_count if total_count > 0 else len(info)
        self.seeding_size = total_size
        self.seeding_info = JsonUtils.dumps(info)

    @staticmethod
    def _get_nested(obj: Any, keys: list) -> Any:
        for key in keys:
            if isinstance(obj, dict):
                obj = obj.get(key)
            elif isinstance(obj, list):
                try:
                    obj = obj[int(key)]
                except (ValueError, IndexError):
                    return None
            else:
                return None
        return obj

    def _fetch_html(self, url: str, referer: str | None = None, use_ajax_headers: bool = True) -> str | None:
        headers = dict(self._headers) if self._headers else {}
        headers.setdefault("User-Agent", self._ua)
        if use_ajax_headers:
            headers.update(
                {
                    "Accept": "*/*",
                    "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8,ja;q=0.7",
                    "X-Requested-With": "XMLHttpRequest",
                    "Sec-Fetch-Dest": "empty",
                    "Sec-Fetch-Mode": "cors",
                    "Sec-Fetch-Site": "same-origin",
                }
            )
        else:
            headers.update(
                {
                    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
                    "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8,ja;q=0.7",
                    "Sec-Fetch-Dest": "document",
                    "Sec-Fetch-Mode": "navigate",
                    "Sec-Fetch-Site": "same-origin",
                }
            )
        headers.pop("referer", None)
        if referer:
            headers["Referer"] = referer
        elif "Referer" not in headers:
            headers.setdefault("Referer", self._base_url_str)
        proxy_url = self._proxies.get("http") if self._proxies else None
        engine = self._site_engine
        rate_limiter = getattr(engine, "site_limiter", None)
        rate_limiter_engine = rate_limiter.engine if rate_limiter else None
        rl_kwargs = engine_tools._get_rate_limit_kwargs(engine, self._def)

        def _request(with_browser=None) -> str | None:
            try:
                res = HttpClient(
                    config=HttpClientConfig(proxy_url=proxy_url, browser=with_browser),
                    rate_limiter=rate_limiter_engine,
                ).get(
                    url=url,
                    headers=headers,
                    auth=CookieAuth(self._cookie) if self._cookie else None,
                    **rl_kwargs,
                )
                return res.text
            except Exception as exc:
                log.debug(f"_fetch_html {self.site_name} 请求失败: {url} ({exc})")
                return None

        text = _request()
        # 直连失败/疑似仍处于挑战页时，自动降级 nexus-chrome 渲染再取一次
        if text is None or is_challenge(text):
            site_key = str(getattr(self._def, "id", "") or "")
            if site_key:
                try:
                    text = _request(
                        build_browser_mode(
                            site_info={"chrome": True, "ua": self._ua, "browser_render": True},
                            site_key=site_key,
                            proxy_url=proxy_url,
                            render_html=True,
                        )
                    )
                except Exception:
                    text = None
        return text


def _html_config_factory(
    url: str,
    site_name: str,
    site_cookie: str,
    site_engine,
    html_text: str | None = None,
    site_headers: dict | None = None,
    ua: str = "",
    emulate: bool = False,
    proxy: bool = False,
    session: Any = None,
    api_key: str | None = None,
    bearer_token: str | None = None,
) -> ConfigHtmlUserInfo | None:
    engine = site_engine
    site_def = engine.get_by_url(url)
    if not site_def:
        return None
    return ConfigHtmlUserInfo(
        site_def,
        site_name,
        url,
        site_cookie,
        site_engine=engine,
        site_headers=site_headers,
        ua=ua,
        emulate=emulate,
        proxy=proxy,
        session=session,
        json_data=html_text,
        api_key=api_key,
        bearer_token=bearer_token,
    )


# 注册工厂函数由 lifespan 调用
