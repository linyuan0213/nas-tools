"""
配置驱动的 API 站点用户信息解析器

替代硬编码的 MteamUserInfo/YemaPTUserInfo/RousiUserInfo 等，
通过 site JSON 中的 user_info 配置驱动数据提取。
"""

import time

import log
from app.infrastructure.http.client import HttpClient
from app.infrastructure.http.config import HttpClientConfig
from app.sites import engine_tools
from app.sites.engine import SiteDefinition
from app.utils.config_tools import get_proxies
from app.utils.json_utils import JsonUtils
from app.utils.string_utils import StringUtils


class ConfigApiUserInfo:
    """
    配置驱动的 API 用户信息解析器

    从 SiteDefinition.user_info 读取端点配置，
    调用 API 获取 profile / seeding / messages 数据。
    """

    order = 10

    def __init__(
        self,
        site_def: SiteDefinition,
        site_name,
        url,
        site_cookie,
        site_engine,
        site_headers=None,
        ua="",
        emulate=False,
        proxy=False,
        session=None,
        json_data=None,
        api_key=None,
        bearer_token=None,
    ):
        self.site_name = site_name
        self.site_url = url
        self._def = site_def
        self._cookie = site_cookie
        self._headers = site_headers or {}
        self._ua = ua
        self._emulate = emulate
        self._proxy = proxy
        self._session = session
        self._json_data = json_data
        self._proxies = get_proxies() if proxy else None
        self._site_engine = site_engine
        self._api_key = api_key
        self._bearer_token = bearer_token

        self.username = None
        self.userid = None
        self.user_level = None
        self.join_at = None
        self.bonus = 0.0
        self.upload = 0
        self.download = 0
        self.ratio = 0.0
        self.seeding = 0
        self.seeding_size = 0
        self.seeding_info = "[]"
        self.leeching = 0
        self.leeching_size = 0
        self.message_unread = 0
        self.message_unread_contents = []
        self.err_msg = None
        self.site_favicon = None

    @classmethod
    def match(cls, _html_text):
        return False

    @property
    def schema(self):
        return "ConfigApi"

    def site_schema(self):
        return "ConfigApi"

    def parse(self):
        cfg = self._def.user_info if isinstance(self._def.user_info, dict) else {}
        if not cfg:
            self.err_msg = "站点未配置 user_info"
            return
        self._parse_profile(cfg, prefetched=self._json_data)
        self._parse_seeding(cfg)
        self._parse_messages(cfg)

    def _parse_profile(self, cfg, prefetched=None):
        profile_cfg = cfg.get("profile")
        if not profile_cfg:
            return
        resp = prefetched or self._api_call(profile_cfg)
        if resp is None:
            return
        mapping = profile_cfg.get("response", {}).get("field_mapping", {})
        for field_name, field_cfg in mapping.items():
            val = self._resolve_json_path(resp, field_cfg)
            if val is not None:
                setattr(self, field_name, val)

        log.debug(
            f"[ConfigApiUserInfo]{self.site_name} profile: "
            f"upload={self.upload} download={self.download} seeding={self.seeding} "
            f"bonus={self.bonus} username={self.username}"
        )

        if self.upload and self.download:
            self.ratio = round(self.upload / self.download, 2) if self.download else 0

    def _parse_seeding(self, cfg):
        seeding_cfg = cfg.get("seeding")
        if not seeding_cfg:
            log.debug(f"[ConfigApiUserInfo]{self.site_name} 无独立 seeding 配置")
            return
        pagination = seeding_cfg.get("pagination", {})
        pagination_type = pagination.get("type", "page_param")

        page = 1
        total_pages = 1
        total_size = 0
        seeding_info = []

        while page <= total_pages:
            body = dict(seeding_cfg.get("body") or {})
            extra_vars = {"userid": str(self.userid) if self.userid else ""}
            body = self._render_body(body, page=page, **extra_vars)
            resp = self._api_call(seeding_cfg, body)
            if resp is None:
                log.warn(f"[ConfigApiUserInfo]{self.site_name} seeding API 失败")
                break
            if pagination_type == "page_param":
                resp_total = int(
                    self._resolve_json_path(
                        resp,
                        {"source": pagination.get("total_pages_key", "totalPages")},
                        str(1),
                    )
                    or 1
                )
                if page == 1:
                    total_pages = resp_total

            items_key = seeding_cfg.get("response", {}).get("items_key", "data")
            seeders_field = seeding_cfg.get("response", {}).get("seeders_field", "seeders")
            size_field = seeding_cfg.get("response", {}).get("size_field", "size")
            response_type = seeding_cfg.get("response", {}).get("response_type", "list")
            if response_type == "single":
                obj = self._get_nested(resp, items_key.split("."))
                if obj and isinstance(obj, dict):
                    count = int(self._get_nested(obj, seeders_field.split(".")) or 0)
                    size = int(self._get_nested(obj, size_field.split(".")) or 0)
                    self.seeding = count
                    self.seeding_size = size
                break
            items = self._get_nested(resp, items_key.split(".")) or []
            if not isinstance(items, list):
                items = []
            if not items:
                break

            for item in items:
                seeders = int(self._get_nested(item, seeders_field.split(".")) or 0)
                size = int(self._get_nested(item, size_field.split(".")) or 0)
                if size > 0:
                    self.seeding += 1
                    total_size += size
                    seeding_info.append([seeders, size])

            page += 1
            time.sleep(2)

        self.seeding_size = total_size
        self.seeding_info = JsonUtils.dumps(seeding_info)

    def _parse_messages(self, cfg):
        msg_cfg = cfg.get("messages")
        if not msg_cfg:
            return
        list_cfg = msg_cfg.get("list")
        if not list_cfg:
            return
        resp = self._api_call(list_cfg)
        if resp is None:
            return
        items_key = msg_cfg.get("response", {}).get("items_key", "data")
        items = self._get_nested(resp, items_key.split(".")) or []
        if not isinstance(items, list):
            items = []
        self.message_unread = len(items)
        self.message_unread_contents = []
        item_mapping = msg_cfg.get("response", {}).get("item_mapping", {})
        for item in items:
            head = self._resolve_json_path(item, {"source": item_mapping.get("head", {}).get("source", "")}) or ""
            date = self._resolve_json_path(item, {"source": item_mapping.get("date", {}).get("source", "")}) or ""
            content = self._resolve_json_path(item, {"source": item_mapping.get("content", {}).get("source", "")}) or ""
            self.message_unread_contents.append((str(head), str(date), str(content)))

        read_cfg = msg_cfg.get("read")
        if read_cfg:
            self._api_call(read_cfg)

    def _api_call(self, endpoint_cfg, body=None):
        method = endpoint_cfg.get("method", "GET").upper()
        base = self._def.api.base_url if self._def.api else ""
        path = endpoint_cfg.get("path", "").lstrip("/")
        url = f"{base.rstrip('/')}/{path}" if path else base.rstrip("/")
        log.debug(f"[ConfigApiUserInfo]{self.site_name} _api_call url={url}")
        engine = self._site_engine
        headers, auth = engine._build_auth(
            self._def,
            {
                "cookie": self._cookie,
                "ua": self._ua,
                "proxy": self._proxy,
                "headers": self._headers,
                "api_key": self._api_key,
                "bearer_token": self._bearer_token,
            },
        )

        proxy_url = self._proxies.get("http") if self._proxies else None
        rate_limiter = getattr(engine, "site_limiter", None)
        rate_limiter_engine = rate_limiter.engine if rate_limiter else None
        rl_kwargs = engine_tools._get_rate_limit_kwargs(engine, self._def)
        client = HttpClient(config=HttpClientConfig(proxy_url=proxy_url), rate_limiter=rate_limiter_engine)
        try:
            if method == "POST":
                data = JsonUtils.dumps(body or {}, separators=(",", ":"))
                if not body or (isinstance(body, dict) and not body):
                    data = None
                    headers.pop("Content-Type", None)
                headers.setdefault("Referer", base)
                headers.setdefault("Origin", base)
                res = client.post(url=url, data=data, headers=headers, auth=auth, **rl_kwargs)
            else:
                params = dict(endpoint_cfg.get("params") or {})
                params = (
                    {k: v.format(page="1") if isinstance(v, str) else v for k, v in params.items()} if params else None
                )
                headers.pop("Content-Type", None)
                res = client.get(url=url, params=params, headers=headers, auth=auth, **rl_kwargs)
            return res.json()
        except Exception:
            log.warn(f"[ConfigApiUserInfo]{self.site_name} API call fail")
            return None

    def _render_body(self, body, **kwargs):
        if not body:
            return {}
        result = {}
        for k, v in body.items():
            if isinstance(v, str):
                try:
                    formatted = v.format(**kwargs)
                    if formatted.isdigit():
                        result[k] = int(formatted)
                    elif formatted.replace(".", "", 1).isdigit():
                        result[k] = float(formatted)
                    else:
                        result[k] = formatted
                except KeyError:
                    result[k] = v
            elif isinstance(v, dict):
                result[k] = self._render_body(v, **kwargs)
            else:
                result[k] = v
        return result

    @staticmethod
    def _resolve_json_path(data, field_cfg, default=None):
        if not field_cfg:
            return default
        source = field_cfg.get("source", "")
        if not source:
            return field_cfg.get("value", default)
        val = ConfigApiUserInfo._get_nested(data, source.split("."))
        if val is None:
            return default
        ftype = field_cfg.get("type", "")
        if ftype == "int":
            try:
                return int(val)
            except (ValueError, TypeError):
                return default
        if ftype == "float":
            try:
                return float(val)
            except (ValueError, TypeError):
                return default
        if ftype == "str":
            return str(val)
        transform = field_cfg.get("transform")
        if transform == "map_value":
            return (field_cfg.get("map") or {}).get(str(val), str(val))
        if transform == "timestamp_to_date":
            return StringUtils.timestamp_to_date(val)
        return val

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


def _api_factory(
    url,
    site_name,
    site_cookie,
    site_engine,
    html_text=None,
    site_headers=None,
    ua="",
    emulate=False,
    proxy=False,
    session=None,
    api_key=None,
    bearer_token=None,
    browser_persistent=False,
):
    engine = site_engine
    site_def, resp = engine.prefetch_user_profile(
        url,
        site_cookie,
        site_headers=site_headers,
        ua=ua,
        proxy=proxy,
        session=session,
        api_key=api_key,
        bearer_token=bearer_token,
    )
    if not site_def or not site_def.user_info or not site_def.user_info.get("profile"):
        return None
    return ConfigApiUserInfo(
        site_def,
        site_name,
        url,
        site_cookie,
        site_engine=engine,
        site_headers=site_headers,
        ua=ua,
        proxy=proxy,
        session=session,
        json_data=resp,
        api_key=api_key,
        bearer_token=bearer_token,
    )


def _register_factory():
    # 注册工厂函数由 lifespan 调用
    pass


_register_factory()
