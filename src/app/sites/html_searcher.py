"""
HTML 站点搜索器

通过 lxml HTML 解析 + CSS/XPath 选择器进行站点搜索。
不再依赖 TorrentSpider，是一个自包含的 HTML 抓取实现。

支持两种模式：
- flat（默认）：直接按 list selector 找行，逐行提取字段
- nested（FireFly）：两层结构，外层 container 提供共享字段
"""

import re
from copy import deepcopy
from typing import Any
from urllib.parse import quote

from lxml import etree

import log
from app.domain.media_type_utils import MediaTypeMapper
from app.domain.mediatypes import MediaType
from app.infrastructure.http import CookieAuth, HttpClient, HttpClientConfig
from app.sites import engine_tools
from app.sites.api_searcher import ApiSiteSearcher
from app.sites.engine import SiteDefinition
from app.sites.searchers import _TRANSFORMS, _css_to_xpath, _resolve_jinja
from app.utils.browser_mode import build_browser_mode
from app.utils.config_tools import get_proxies


class HtmlSiteSearcher:
    """
    HTML 站点搜索器
    """

    def __init__(self, site_def: SiteDefinition, site_engine, user_config: dict | None = None):
        self._site = site_def
        self._user_config = user_config or {}
        self._site_engine = site_engine
        self.last_error: str = ""

    def search(
        self,
        keyword: str = "",
        page: int = 0,
        mtype: MediaType | None = None,
        page_size: int | None = None,
    ) -> list[dict[str, Any]]:
        if not self._site.html:
            return []
        self.last_error = ""
        is_browse = not keyword
        url = self._build_url(keyword, page, mtype, page_size)
        if not url:
            return []

        html_text = self._fetch_html(url)
        if not html_text:
            return []

        return self._parse_html(html_text, is_browse=is_browse)

    @staticmethod
    def _cfg_get(cfg, key, default=None):
        if isinstance(cfg, dict):
            return cfg.get(key, default)
        return getattr(cfg, key, default) if hasattr(cfg, key) else default

    def _domain(self) -> str:
        return (self._user_config.get("domain") or self._site.domain or "").rstrip("/")

    def _build_url(self, keyword: str, page: int, mtype: MediaType | None, page_size: int | None = None) -> str | None:
        cfg = self._site.html
        if not (isinstance(cfg, dict) or hasattr(cfg, "search")):
            return None

        template_vars = {
            "keyword": keyword or "",
            "page": str(page),
            "page_1": str(int(page) + 1),
        }

        browse_cfg = self._cfg_get(cfg, "browse")
        if not keyword and browse_cfg:
            browse_path = self._cfg_get(browse_cfg, "path", "")
            start = int(self._cfg_get(browse_cfg, "start", 1) or 1)
            browse_vars = {**template_vars, "page": str(int(page) + start)}
            browse_path = (browse_path or "").format(**browse_vars)
            domain = self._domain()
            path_with_slash = f"/{browse_path.lstrip('/')}" if browse_path else ""
            return f"{domain}{path_with_slash}"

        search_cfg = self._cfg_get(cfg, "search", {})
        if not search_cfg:
            return None

        paths = self._cfg_get(search_cfg, "paths", [{"path": "", "method": "get"}]) or []
        path = ""
        for p in paths:
            if isinstance(p, dict):
                path = p.get("path", "")
                break

        path = path.format(**template_vars)

        domain = self._domain()
        params = dict(self._cfg_get(search_cfg, "params", {}) or {})
        params_filled = {}
        for k, v in params.items():
            if isinstance(v, str):
                try:
                    params_filled[k] = v.format(**template_vars)
                except KeyError:
                    params_filled[k] = v
            else:
                params_filled[k] = v

        if mtype:
            for pk in ("cat", "category", "cat_id"):
                if pk in params_filled:
                    params_filled[pk] = MediaTypeMapper.to_site_cat(mtype)

        # 每页数量：站点参数中存在 page_size/limit/per_page 等键时覆盖为前端选择值
        if page_size:
            for size_key in ("page_size", "pagesize", "per_page", "perpage", "limit"):
                if size_key in params_filled:
                    params_filled[size_key] = int(page_size)

        qs = "&".join(f"{k}={quote(str(v))}" for k, v in params_filled.items() if v)
        path_with_slash = f"/{path.lstrip('/')}" if path else ""
        url = f"{domain}{path_with_slash}"
        if qs:
            url += f"{'&' if '?' in url else '?'}{qs}"
        if not keyword:
            url = re.sub(r"(search|keyword)=[^&]*&?", "", url).rstrip("&").rstrip("?")
            if page >= 0:
                url += f"{'&' if '?' in url else '?'}page={int(page) + 1}"
        return url

    def _fetch_html(self, url):
        cookie = self._user_config.get("cookie", "")
        headers = {}
        ua = self._user_config.get("ua", "")
        if ua:
            headers["User-Agent"] = ua
        proxies = get_proxies() if self._user_config.get("proxy") else None
        proxy_url = proxies.get("http") if proxies else None
        engine = self._site_engine
        rate_limiter = getattr(engine, "site_limiter", None)
        rate_limiter_engine = rate_limiter.engine if rate_limiter else None
        rl_kwargs = engine_tools._get_rate_limit_kwargs(engine, self._site)
        browser = build_browser_mode(
            site_info={
                "chrome": self._user_config.get("chrome"),
                "ua": ua,
                "browser_render": self._user_config.get("browser_render"),
            },
            site_key=self._user_config.get("domain") or self._site.domain or "",
            proxy_url=proxy_url,
            render_html=bool(self._user_config.get("browser_render")),
        )
        try:
            res = HttpClient(
                config=HttpClientConfig(proxy_url=proxy_url, browser=browser),
                rate_limiter=rate_limiter_engine,
            ).get(url=url, headers=headers, auth=CookieAuth(cookie) if cookie else None, **rl_kwargs)
            if not res.is_success:
                self.last_error = f"HTTP {res.status_code}"
                log.warn(f"[HtmlSiteSearcher]{self._site.name} HTTP {res.status_code}, url={url}")
                return None
        except Exception as e:
            self.last_error = f"{type(e).__name__}"
            log.warn(f"[HtmlSiteSearcher]{self._site.name} 请求失败: {e}")
            return None
        encoding = self._site.encoding or None
        if encoding:
            return res.content.decode(encoding)
        return res.text

    def _parse_html(self, html_text, is_browse=False):
        html_doc = etree.HTML(html_text)
        cfg = self._site.html

        parser_type = self._cfg_get(cfg, "parser_type", "flat")

        if parser_type == "nested":
            return self._parse_nested(html_doc, cfg)
        return self._parse_flat(html_doc, cfg, is_browse=is_browse)

    def _parse_flat(self, html_doc, cfg, is_browse=False):
        torrents_cfg = self._cfg_get(cfg, "torrents", {})

        if is_browse and self._cfg_get(torrents_cfg, "browse_list"):
            list_cfg = self._cfg_get(torrents_cfg, "browse_list", {})
            fields_cfg = self._cfg_get(torrents_cfg, "browse_fields", {})
        else:
            list_cfg = self._cfg_get(torrents_cfg, "list", {})
            fields_cfg = self._cfg_get(torrents_cfg, "fields", {})

        list_selector = self._cfg_get(list_cfg, "selector", "")
        if not list_selector:
            return []

        xpath = _css_to_xpath(list_selector)
        try:
            rows = html_doc.xpath(xpath)
        except Exception:
            rows = []
        if not rows and ":has(" not in list_selector:
            try:
                rows = html_doc.cssselect(list_selector)
            except Exception:
                rows = []

        results = []
        for row in rows:
            item = self._extract_fields(row, fields_cfg)
            if item and item.get("title"):
                self._fix_size(item)
                self._normalize_html_result(item)
                results.append(item)
                log.info(
                    f"[HtmlSiteSearcher]{self._site.name} item: title={item.get('title')!r}, "
                    f"size={item.get('size')!r}, seeders={item.get('seeders')!r}, "
                    f"description={item.get('description')!r}"
                )
        return results

    def _normalize_html_result(self, item):
        domain = self._domain()
        for old_key, new_key in [("download", "enclosure"), ("details", "page_url")]:
            if old_key in item and new_key not in item:
                item[new_key] = item.pop(old_key)
        for url_field in ("enclosure", "page_url"):
            val = item.get(url_field, "")
            if val and isinstance(val, str) and not val.startswith("http") and not val.startswith("magnet"):
                if val.startswith("/"):
                    val = f"{domain}{val}"
                else:
                    val = f"{domain}/{val}"
                item[url_field] = val

    def _parse_nested(self, html_doc, cfg):
        torrents_cfg = self._cfg_get(cfg, "torrents", {})
        domain = self._domain()

        container_xpath = self._cfg_get(torrents_cfg, "container_xpath") or '//table[contains(@class, "gm_table")]'
        row_xpath = self._cfg_get(torrents_cfg, "row_xpath") or './/tr[@id="gm_tr_item"]'
        container_fields_cfg = self._cfg_get(torrents_cfg, "container_fields", {}) or {}
        fields_cfg = self._cfg_get(torrents_cfg, "fields", {}) or {}

        containers = html_doc.xpath(container_xpath)
        torrents = []

        template_vars = {"domain": domain}

        for container in containers:
            ct = deepcopy(container)
            container_vals = {}
            for _fname, _fcfg in container_fields_cfg.items():
                container_vals[_fname] = self._extract_nested_value(ct, _fcfg, template_vars, container_vals)
            template_vars.update(container_vals)

            rows = ct.xpath(row_xpath)
            for row in rows:
                rt = deepcopy(row)
                field_vals = dict(container_vals)
                for fname, fcfg in fields_cfg.items():
                    field_vals[fname] = self._extract_nested_value(rt, fcfg, template_vars, field_vals)

                item = {}
                for fname, _ in fields_cfg.items():
                    item[fname] = field_vals.get(fname)

                for cf_name, cf_val in container_vals.items():
                    item[cf_name] = cf_val

                item.setdefault("uploadvolumefactor", 1.0)
                item.setdefault("grabs", "")
                item.setdefault("downloadvolumefactor", 1.0)

                if item.get("title"):
                    self._fix_size(item)
                    self._normalize_html_result(item)
                    torrents.append(item)
                    log.info(
                        f"[HtmlSiteSearcher]{self._site.name} item: title={item.get('title')!r}, "
                        f"description={item.get('description')!r}"
                    )

        return torrents

    @staticmethod
    def _fix_size(item):
        size = item.get("size")
        if size is None:
            return
        if isinstance(size, (int, float)):
            return
        if isinstance(size, str):
            # 同时支持十进制单位 (GB/MB/KB) 和二进制单位 (GiB/MiB/KiB)
            m = re.match(r"([\d,.]+)\s*([KMGT]?i?B)", str(size), re.IGNORECASE)
            if m:
                val = float(m.group(1).replace(",", ""))
                unit = m.group(2).upper()[0]
                multipliers = {"B": 1, "K": 1024, "M": 1024**2, "G": 1024**3, "T": 1024**4}
                item["size"] = int(val * multipliers.get(unit, 1))
            else:
                try:
                    item["size"] = int(float(str(size).replace(",", "")))
                except (ValueError, TypeError):
                    item["size"] = 0

    def _extract_nested_value(self, element, fcfg, template_vars, field_vals):
        if not isinstance(fcfg, dict):
            return fcfg

        template = fcfg.get("template", "")
        if template:
            tpl_vars = {**template_vars, **field_vals}
            return template.format(**tpl_vars)

        xpath = fcfg.get("xpath", "")
        if not xpath:
            return fcfg.get("default", "")

        els = element.xpath(xpath)
        if not els:
            return fcfg.get("default", "")

        val = None
        if isinstance(els, list):
            if isinstance(els[0], str):
                val = els
            elif hasattr(els[0], "attrib"):
                val = els[0] if len(els) == 1 else els

        if isinstance(val, list) and val and isinstance(val[0], str):
            join_delim = fcfg.get("join", "")
            val = join_delim.join(v.strip() for v in val) if join_delim else val[0]
        elif val is not None and not isinstance(val, list) and hasattr(val, "text"):
            val = (val.text or "").strip()

        replace_map = fcfg.get("replace")
        if replace_map and isinstance(val, str):
            for old, new in (replace_map if isinstance(replace_map, dict) else {}).items():
                val = val.replace(old, new.format(**template_vars))

        filters = fcfg.get("filters")
        if filters and val is not None:
            val = self._apply_html_filters(str(val) if not isinstance(val, str) else val, filters)

        transform = fcfg.get("transform")
        if transform and transform in _TRANSFORMS:
            val = _TRANSFORMS[transform](val)

        if_present = fcfg.get("if_present")
        if if_present is not None:
            val = if_present if val else fcfg.get("default", 1.0)

        return val if val is not None else fcfg.get("default", "")

    def _extract_fields(self, element, fields_cfg):
        first_pass = {}
        for fname, fcfg in fields_cfg.items():
            if not isinstance(fcfg, dict):
                continue
            val = self._extract_field_value(element, fcfg)
            first_pass[fname] = val

        result = {}
        for fname, fcfg in fields_cfg.items():
            if not isinstance(fcfg, dict):
                result[fname] = fcfg
                continue
            text_tpl = fcfg.get("text", "")
            if text_tpl:
                result[fname] = _resolve_jinja(text_tpl, first_pass)
                if fname == "title":
                    t2 = fcfg.get("attribute", "")
                    if t2:
                        raw = self._extract_field_value(
                            element, {"selector": fcfg.get("selector", ""), "attribute": t2}
                        )
                        if raw:
                            result[fname] = raw
                    if result[fname] is None:
                        result[fname] = first_pass.get(fname, "")
            else:
                result[fname] = first_pass.get(fname, "")
        if not result.get("title") and not result.get("title_default"):
            return None
        return result

    def _extract_field_value(self, element, fcfg):
        selector = fcfg.get("xpath") or fcfg.get("selector", "")

        val = None
        if selector:
            if selector.startswith(("//", ".")):
                xpath = selector
            else:
                xpath = _css_to_xpath(selector)
            try:
                els = element.xpath(xpath)
            except Exception:
                els = []
            if not els and not selector.startswith("//") and not selector.startswith("."):
                try:
                    els = element.cssselect(selector)
                except Exception:
                    els = []

            if els:
                attr = fcfg.get("attribute", "")
                contents = fcfg.get("contents", 0)
                remove_sel = fcfg.get("remove", "")

                if attr and hasattr(els[0], "attrib") and attr in els[0].attrib:
                    val = els[0].attrib[attr]
                elif hasattr(els[0], "text"):
                    if len(els) > 1 and not attr:
                        # 多元素且无 attribute：提取所有元素文本并拼接
                        parts = []
                        for el in els:
                            txt = "".join(e for e in el.xpath(".//text()") if e).strip()
                            if txt:
                                parts.append(txt)
                        join_delim = fcfg.get("join", "|")
                        val = join_delim.join(parts)
                    else:
                        if remove_sel:
                            try:
                                for rm_el in els[0].xpath(remove_sel):
                                    if rm_el.text:
                                        els[0].text = (els[0].text or "").replace(rm_el.text, "")
                            except Exception as e:  # noqa: BLE001
                                log.debug(f"[html_searcher]忽略异常: {e}")
                        val = "".join(e for e in els[0].xpath(".//text()") if e).strip()
                        if not val:
                            val = (els[0].text or "").strip()
                        if not val:
                            val = (els[0].text_content() or "").strip() if hasattr(els[0], "text_content") else ""
                        if contents and isinstance(contents, int):
                            lines = val.split("\n")
                            val = lines[contents] if contents < len(lines) else val
                elif isinstance(els, list) and els and isinstance(els[0], str):
                    val = els[0]
                else:
                    val = str(els[0]) if els else None

        case = fcfg.get("case")
        if case:
            for css_class, mapped_val in case.items():
                if css_class == "*":
                    val = mapped_val
                    break
                try:
                    # 支持属性选择器，如 span[alt='Free']
                    attr_m = re.match(r"(\w+)\[(\w+)=['\"](.+?)['\"]\]", css_class)
                    if attr_m:
                        tag, attr, value = attr_m.groups()
                        found = element.xpath(f".//{tag}[@{attr}='{value}']")
                        if found:
                            val = mapped_val
                            break
                        continue

                    # 支持文本包含选择器，如 span:contains('Free')
                    contains_m = re.match(r"(\w*):contains\(['\"](.+?)['\"]\)", css_class)
                    if contains_m:
                        tag, text = contains_m.groups()
                        xpath_expr = (
                            f".//{tag}[contains(text(), '{text}')]" if tag else f".//*[contains(text(), '{text}')]"
                        )
                        found = element.xpath(xpath_expr)
                        if found:
                            val = mapped_val
                            break
                        continue

                    cls_xpath = f".//{css_class.replace('.', '[@class]')}"
                    if element.xpath(cls_xpath):
                        val = mapped_val
                        break
                    attr_xpath = f".//*[@class='{css_class}']"
                    if element.xpath(attr_xpath):
                        val = mapped_val
                        break
                except Exception as e:  # noqa: BLE001
                    log.debug(f"[html_searcher]忽略异常: {e}")
                try:
                    if css_class.startswith("img."):
                        cls = css_class[4:]
                        found = element.xpath(f".//img[contains(@class, '{cls}')]")
                        if found:
                            val = mapped_val
                            break
                except Exception as e:  # noqa: BLE001
                    log.debug(f"[html_searcher]忽略异常: {e}")

        filters = fcfg.get("filters", [])
        if filters and val is not None:
            val = self._apply_html_filters(str(val) if not isinstance(val, str) else val, filters)

        default_val = fcfg.get("default_value", "")
        if val is None and default_val:
            val = _resolve_jinja(default_val, {})

        return val if val is not None else None

    @staticmethod
    def _apply_html_filters(value, filters):
        return ApiSiteSearcher._apply_filters(value, filters)
