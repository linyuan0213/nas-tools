"""
API 站点搜索器

根据 SiteDefinition.api.endpoints.search 配置，
调用站点 API 进行搜索并返回标准化结果。

支持：
- mode_mapping: 媒体类型 → 请求参数映射（含多分类 fan-out）
- filters: 字段值后处理（regex/split/replace 等）
- transform: 命名的值转换函数
- 模板变量：{keyword} {page} {page_1}
"""

import re
from typing import Any
from urllib.parse import parse_qs, urlparse

import log
from app.domain.mediatypes import MediaType
from app.infrastructure.http.client import HttpClient
from app.infrastructure.http.config import HttpClientConfig
from app.sites import engine_tools
from app.sites.engine import SiteDefinition
from app.sites.searchers import _TRANSFORMS
from app.utils.config_tools import get_proxies
from app.utils.json_utils import JsonUtils


class ApiSiteSearcher:
    """
    API 站点搜索器
    """

    def __init__(self, site_def: SiteDefinition, site_engine, user_config: dict | None = None):
        self._site = site_def
        self._user_config = user_config or {}
        self._engine = site_engine
        self._auth_tokens: dict[str, str] = {}
        self.last_error: str = ""
        self._resolve_auth_tokens()

    def search(
        self,
        keyword: str = "",
        page: int = 0,
        mtype: MediaType | None = None,
        page_size: int | None = None,
    ) -> list[dict[str, Any]]:
        if not self._site.api:
            return []
        keyword = keyword or ""
        self.last_error = ""
        search_config = self._site.api.endpoints.get("search", {})
        if not search_config:
            return []
        body_template = dict(search_config.get("body") or {})
        params_template = dict(search_config.get("params") or {})
        mode_mapping = search_config.get("mode_mapping", {})
        mtype_override = {}
        mtype_name = self._mtype_name(mtype)
        if mtype_name and mode_mapping:
            mapped = mode_mapping.get(mtype_name)
            if mapped is not None:
                if isinstance(mapped, list):
                    return self._fanout_search(
                        keyword, page, search_config, body_template, params_template, mapped, page_size
                    )
                elif isinstance(mapped, dict):
                    mtype_override = mapped
                else:
                    mtype_override = {"mode": str(mapped)}
        template_vars = {"keyword": keyword, "page": str(page), "page_1": str(int(page) + 1)}
        body = self._render_template(body_template, **template_vars)
        body.update({k: (v.format(**template_vars) if isinstance(v, str) else v) for k, v in mtype_override.items()})
        return self._execute_request(search_config, body, template_vars, page_size=page_size)

    def _fanout_search(self, keyword, page, search_config, body_template, params_template, categories, page_size=None):
        all_results = []
        template_vars = {"keyword": keyword, "page": str(page), "page_1": str(int(page) + 1)}
        seen = set()
        for cat_config in categories:
            fanout_body = {**body_template}
            fanout_body.update(cat_config)
            body = self._render_template(fanout_body, **template_vars)
            for result in self._execute_request(search_config, body, template_vars, page_size=page_size):
                key = "".join(
                    str(result.get(k) or "") for k in ("title", "enclosure", "size")
                )
                if key not in seen:
                    seen.add(key)
                    all_results.append(result)
        return all_results

    @staticmethod
    def _apply_page_size(container: dict, page_size: int | None) -> None:
        """按站点实际参数名覆盖每页数量（兼容 page_size/pageSize/size/limit 及 pageParam.pageSize 嵌套）"""
        if not page_size:
            return
        for key in (
            "page_size",
            "pageSize",
            "pagesize",
            "size",
            "per_page",
            "perpage",
            "limit",
            "count",
        ):
            if key in container:
                container[key] = int(page_size)
                return
        for group in ("pageParam", "pagination", "paging"):
            nested = container.get(group)
            if isinstance(nested, dict):
                for key in ("pageSize", "page_size", "size"):
                    if key in nested:
                        nested[key] = int(page_size)
                        return

    def _execute_request(self, search_config, body, template_vars, page_size=None):
        base_url = (self._site.api.base_url or "").rstrip("/") if self._site.api else ""
        method = search_config.get("method", "GET").upper()
        path = search_config.get("path", "").lstrip("/")
        url = f"{base_url}/{path}"
        # 空数组参数（如 categories: []）表示不过滤，发送前剔除——
        # 部分站点 API 对显式空数组返回 500（如 hddolby），缺省该参数才是"全部分类"
        body = {k: v for k, v in body.items() if not (isinstance(v, list) and len(v) == 0)}
        self._apply_page_size(body, page_size)
        headers = self._engine._build_headers(self._site, self._user_config)
        proxy = get_proxies() if self._user_config.get("proxy") else None
        proxy_url = proxy.get("http") if proxy else None
        rate_limiter = getattr(self._engine, "site_limiter", None)
        rate_limiter_engine = rate_limiter.engine if rate_limiter else None
        rl_kwargs = engine_tools._get_rate_limit_kwargs(self._engine, self._site)
        try:
            client = HttpClient(
                config=HttpClientConfig(proxy_url=proxy_url),
                rate_limiter=rate_limiter_engine,
            )
            if method == "POST":
                content_type = search_config.get("content_type", "application/json;charset=utf-8")
                post_headers = {**headers, "Content-Type": content_type}
                if content_type == "application/x-www-form-urlencoded":
                    res = client.post(url=url, data=body, headers=post_headers, **rl_kwargs)
                else:
                    res = client.post(
                        url=url,
                        data=JsonUtils.dumps(body, separators=(",", ":")),
                        headers=post_headers,
                        **rl_kwargs,
                    )
            else:
                params = dict(search_config.get("params") or {})
                params = self._render_template(params, **template_vars)
                self._apply_page_size(params, page_size)
                res = client.get(url=url, params=params, headers=headers, **rl_kwargs)
            if not res.is_success:
                self.last_error = f"HTTP {res.status_code}"
                log.warn(f"[ApiSiteSearcher]{self._site.name} HTTP {res.status_code}, url={url}")
                return []
            resp_data = res.json()
        except Exception as e:
            self.last_error = f"{type(e).__name__}"
            log.warn(f"[ApiSiteSearcher]{self._site.name} 搜索失败, url={url}, error={e}")
            return []
        result = self._parse_response(resp_data, search_config)
        log.warn(f"[ApiSiteSearcher]{self._site.name} 返回 {len(result)} 条结果, url={url}")
        if len(result) == 0:
            log.warn(f"[ApiSiteSearcher]{self._site.name} raw resp: {str(resp_data)[:200]}")
        return result

    def _resolve_auth_tokens(self):
        if not self._site.api:
            return
        auth_type = self._site.api.auth.get("type", "")
        if auth_type == "passkey":
            token = self._engine._resolve_auth_token(self._site, self._user_config, "passkey")
            if token:
                self._auth_tokens["passkey"] = token
        if auth_type == "csrf":
            token = self._engine._resolve_auth_token(self._site, self._user_config, "csrf")
            if token:
                self._auth_tokens["csrf_token"] = token
        apikey = self._user_config.get("api_key", "")
        if apikey:
            self._auth_tokens["apikey"] = apikey
        cookie = self._user_config.get("cookie", "")
        if cookie:
            self._auth_tokens["cookie"] = cookie
        bearer_token = self._user_config.get("bearer_token", "")
        if bearer_token:
            self._auth_tokens["bearer_token"] = bearer_token
        domain = (
            self._user_config.get("domain") or self._site.domain or (self._site.api.base_url if self._site.api else "")
        )
        if domain:
            parsed = urlparse(domain)
            domain_no_scheme = parsed.netloc if parsed.scheme else domain
            self._auth_tokens["domain"] = domain_no_scheme.rstrip("/")
            self._auth_tokens["base_url"] = (
                self._site.api.base_url or self._user_config.get("domain") or domain
            ).rstrip("/")

    def _render_template(self, template, **kwargs) -> dict:
        if not template:
            return {}
        result = {}
        for key, value in template.items():
            if isinstance(value, str):
                try:
                    formatted = value.format(**kwargs)
                    if formatted.isdigit() and "{" in value:
                        result[key] = int(formatted)
                    else:
                        result[key] = formatted
                except KeyError:
                    result[key] = value
            elif isinstance(value, dict):
                result[key] = self._render_template(value, **kwargs)
            elif isinstance(value, list):
                result[key] = [
                    self._render_template(v, **kwargs)
                    if isinstance(v, dict)
                    else v.format(**kwargs)
                    if isinstance(v, str)
                    else v
                    for v in value
                ]
            else:
                result[key] = value
        return result

    def _parse_response(self, data, search_config):
        response_config = search_config.get("response", {})
        items_key = response_config.get("items_key", "data")
        mapping = response_config.get("item_mapping", {})
        items = self._get_nested(data, items_key.split(".")) or []
        if not isinstance(items, list):
            items = []
        torrents_key = response_config.get("torrents_key", "")
        if torrents_key and isinstance(items, list):
            flattened = []
            for group in items:
                sub = group.get(torrents_key, []) if isinstance(group, dict) else []
                if isinstance(sub, list):
                    flattened.extend(sub)
            items = flattened
        results = []
        for item in items:
            result = {}
            for field, config in mapping.items():
                result[field] = self._map_field(item, config)
            self._post_process_labels(result, item)
            results.append(result)
            log.info(
                f"[ApiSiteSearcher]{self._site.name} item: title={result.get('title')!r}, "
                f"description={result.get('description')!r}"
            )
        return results

    def _post_process_labels(self, result, raw_item):
        if "labelsNew" in raw_item:
            new_labels = raw_item.get("labelsNew") or []
            old_label = raw_item.get("labels", "0")
            label_map = {
                "1": "DIY",
                "2": "国配",
                "4": "中字",
                "3": "DIY|国配",
                "5": "DIY|中字",
                "6": "国配|中字",
                "7": "DIY|国配|中字",
            }
            parts = []
            if old_label and str(old_label) != "0":
                parts.append(label_map.get(str(old_label), ""))
            if isinstance(new_labels, list):
                parts.extend(str(v) for v in new_labels)
            elif new_labels:
                parts.append(str(new_labels))
            if parts:
                result["labels"] = "|".join(parts)

    @staticmethod
    def _get_nested(obj, keys):
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

    def _map_field(self, item, config):
        if isinstance(config, dict):
            ftype = config.get("type")
            if ftype == "mapping":
                source_val = self._get_nested(item, config.get("source", "").split("."))
                return config.get("map", {}).get(str(source_val), 1.0)
            if ftype == "api":
                return None
            if ftype == "constant":
                return config.get("value")
            if ftype == "template":
                template = config.get("value", "")
                field_vals = dict(self._auth_tokens) if hasattr(self, "_auth_tokens") else {}
                for fk, fsource in (config.get("fields") or {}).items():
                    val = field_vals.get(fsource) or self._get_nested(item, fsource.split("."))
                    field_vals[fk] = str(val or "")
                try:
                    return template.format(**field_vals)
                except KeyError:
                    return template
            source = config.get("source", "")
            if source:
                val = self._get_nested(item, source.split("."))
                filters = config.get("filters")
                if filters:
                    val = self._apply_filters(val, filters)
                transform = config.get("transform")
                if transform and transform in _TRANSFORMS:
                    val = _TRANSFORMS[transform](val, config)
                return val
            return config
        return str(config) if config else None

    @staticmethod
    def _apply_filters(value, filters):
        if value is None:
            return ""
        for f in filters:
            name = f.get("name", "")
            args = f.get("args", [])
            if name == "regex" or name == "re_search":
                pattern = args[0] if args else r".*"
                group = int(args[1]) if len(args) > 1 else 0
                match = re.findall(pattern, str(value))
                value = match[group] if match and len(match) > group else ""
            elif name == "split":
                delim = args[0] if args else ","
                idx = int(args[1]) if len(args) > 1 else 0
                parts = str(value).split(delim)
                value = parts[idx] if idx < len(parts) else ""
            elif name == "replace":
                old = args[0] if args else ""
                new = args[1] if len(args) > 1 else ""
                value = str(value).replace(old, new)
            elif name == "strip":
                value = str(value).strip()
            elif name == "appendleft":
                value = str(args[0]) + str(value) if args else str(value)
            elif name == "querystring":
                key = args[0] if args else ""
                try:
                    parsed = urlparse(str(value))
                    qs = parse_qs(parsed.query)
                    value = qs.get(key, [""])[0]
                except Exception:
                    value = ""
        return value

    @staticmethod
    def _mtype_name(mtype):
        if mtype is None:
            return None
        if hasattr(mtype, "name"):
            return mtype.name
        return str(mtype)
