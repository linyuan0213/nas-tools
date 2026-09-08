"""站点解析健康自检服务单元测试."""

from types import SimpleNamespace

from app.services.site_parse_health_service import SiteParseHealthService
from app.sites.engine import SiteDefinition, TorrentAttrFetchError


class _FakeEngine:
    """按 URL 返回站点定义（HTML conf）的假 SiteEngine."""

    def __init__(self, conf: dict | None, is_html: bool = True):
        self._conf = conf
        self._is_html = is_html
        self._selector_stats: dict[str, int] = {}

    def get_by_url(self, url):
        site = SiteDefinition(id="t1", name="站点", domain="example.com", detail_page_url="/d/{tid}")
        if self._is_html:
            site.html = SimpleNamespace(conf=self._conf)  # type: ignore[attr-defined]
        else:
            site.torrent_attr = {"method": "POST", "path": "/api/detail", "response": {}}
        return site

    def html_selector_stats(self, url, user_config):
        sel = self._selector_stats
        return {
            "fetched": True,
            "selectors": sel,
            "peer_value": 1,
            "free": sel.get("FREE", 0) > 0 or sel.get("2XFREE", 0) > 0,
            "hr": sel.get("HR", 0) > 0,
        }


class _FakeCache:
    def __init__(self, engine: _FakeEngine):
        self._site_engine = engine
        self._brush_sites = [
            {
                "id": 1,
                "name": "站点",
                "cookie": "c",
                "api_key": "k",
                "bearer_token": "",
                "ua": "UA",
                "headers": "{}",
                "proxy": False,
                "brush_enable": 1,
                "rss_enable": 1,
                "rssurl": "https://example.com/rss.php",
            }
        ]


class _FakeRepo:
    def __init__(self):
        self.upserted: list[tuple[int, str, dict]] = []

    def upsert(self, site_id, check_date, data):
        self.upserted.append((site_id, check_date, data))

    def latest(self, site_id):
        return None

    def latest_all(self):
        return []

    def history(self, site_id, limit=30):
        return []


class _SimpleSiteConf:
    """HTML 站默认走 html_selector_stats，不需要真实 siteconf；占位即可."""

    def check_torrent_attr(self, **kwargs):
        return None


RSS_XML = """<?xml version="1.0"?>
<rss><channel>
  <item><title>A</title><link>https://example.com/details.php?id=1</link></item>
  <item><title>B</title><link>https://example.com/details.php?id=2</link></item>
  <item><title>C</title><link>https://example.com/details.php?id=3</link></item>
  <item><title>D</title><link>https://example.com/details.php?id=4</link></item>
  <item><title>E</title><link>https://example.com/details.php?id=5</link></item>
  <item><title>F</title><link>https://other.example/feed</link></item>
</channel></rss>"""


def _make_service(engine: _FakeEngine, attr_return, attr_raise: bool = False):
    cache = _FakeCache(engine)
    repo = _FakeRepo()

    class _FakeSiteConf:
        def check_torrent_attr(self, **kwargs):
            if attr_raise:
                raise TorrentAttrFetchError("测试失败")
            return attr_return

    svc = SiteParseHealthService(
        site_cache=cache,  # type: ignore[arg-type]
        siteconf=_FakeSiteConf(),  # type: ignore[arg-type]
        repo=repo,  # type: ignore[arg-type]
        sample_size=5,
    )
    svc._fetch_rss = lambda site_info: (RSS_XML, False, False)  # type: ignore[method-assign]
    return svc, repo


def test_ok_when_selectors_hit():
    conf = {"FREE": ["//b"], "PEER_COUNT": ["//span[@id='seeders']/span[1]"]}
    engine = _FakeEngine(conf)
    engine._selector_stats = {"FREE": 1, "PEER_COUNT": 3}
    svc, repo = _make_service(engine, {"free": True, "peer_count": 1})
    result = svc.check_site(svc._cache._brush_sites[0])
    assert result["status"] == "ok"
    assert result["sample_count"] == 5
    assert result["attr_ok"] == 5


def test_degraded_when_selector_never_hits():
    conf = {"FREE": ["//b"], "PEER_COUNT": ["//span[@id='seeders']/span[1]"]}
    engine = _FakeEngine(conf)
    # PEER_COUNT 一次都不命中 → 降级（观众改版这类静默失效场景）
    engine._selector_stats = {"FREE": 1, "PEER_COUNT": 0}
    svc, repo = _make_service(engine, {"free": False, "peer_count": 0})
    result = svc.check_site(svc._cache._brush_sites[0])
    assert result["status"] == "degraded"
    assert any("PEER_COUNT" in i for i in result["issues"])


def test_free_selector_zero_hit_not_degraded():
    """FREE/2XFREE/HR 按种子实际徽标而定，随机样本零命中属正常，不判降级"""
    conf = {"FREE": ["//b"], "2XFREE": ["//b2"], "PEER_COUNT": ["//span[@id='seeders']/span[1]"]}
    engine = _FakeEngine(conf)
    engine._selector_stats = {"FREE": 0, "2XFREE": 0, "PEER_COUNT": 5}
    svc, repo = _make_service(engine, {"free": False, "peer_count": 3})
    result = svc.check_site(svc._cache._brush_sites[0])
    assert result["status"] == "ok"


def test_invalid_when_all_attr_fetch_fail():
    # API 站点（非 HTML）：走 check_torrent_attr，全部抛错 → invalid
    engine = _FakeEngine(None, is_html=False)
    engine._selector_stats = {}
    svc, repo = _make_service(engine, {}, attr_raise=True)
    result = svc.check_site(svc._cache._brush_sites[0])
    assert result["status"] == "invalid"
    assert result["attr_fail"] == 5


def test_skipped_when_no_sample_links():
    engine = _FakeEngine({"FREE": ["//b"]})
    engine._selector_stats = {}
    svc, repo = _make_service(engine, {"free": True})
    svc._fetch_rss = lambda site_info: ("<rss><channel></channel></rss>", False, False)  # type: ignore[method-assign]
    result = svc.check_site(svc._cache._brush_sites[0])
    assert result["status"] == "skipped"
    assert repo.upserted and repo.upserted[0][2]["status"] == "skipped"


def test_skipped_when_rss_rate_limited():
    """RSS 限流 → 跳过（skipped），不判任何异常"""
    engine = _FakeEngine({"FREE": ["//b"]})
    engine._selector_stats = {}
    svc, repo = _make_service(engine, {"free": True})
    svc._fetch_rss = lambda site_info: ("请调整RSS请求间隔时间至少为2分钟", False, True)  # type: ignore[method-assign]
    result = svc.check_site(svc._cache._brush_sites[0])
    assert result["status"] == "skipped"
    assert result["sample_count"] == 0


def test_skipped_when_all_detail_pages_rate_limited():
    """详情页全部被限流 → 跳过（skipped），不算 invalid"""
    engine = _FakeEngine({"FREE": ["//b"]})
    engine._selector_stats = {}
    svc, repo = _make_service(engine, {"free": True})
    # API 站 + 探针全部标记 limited
    engine_api = _FakeEngine(None, is_html=False)
    engine_api._selector_stats = {}
    svc2, _ = _make_service(engine_api, {}, attr_raise=False)
    svc2._probe = lambda site_info, url: {"ok": False, "auth": False, "limited": True}  # type: ignore[method-assign]
    result = svc2.check_site(svc2._cache._brush_sites[0])
    assert result["status"] == "skipped"
    assert result["attr_fail"] == 0


def test_auth_error_when_rss_is_login_page():
    """RSS 被重定向/渲染为登录页 → auth_error，不进入结构降级判定"""
    engine = _FakeEngine({"FREE": ["//b"]})
    engine._selector_stats = {}
    svc, repo = _make_service(engine, {"free": True})
    svc._fetch_rss = lambda site_info: ("<html><body><form action='takelogin.php'></form></body></html>", True, False)  # type: ignore[method-assign]
    result = svc.check_site(svc._cache._brush_sites[0])
    assert result["status"] == "auth_error"
    assert result["sample_count"] == 0


def test_first_abnormal_no_notify_until_second_day():
    """首次异常只记录不推送（防抖）；昨日异常+今日异常 → 推送"""
    from types import SimpleNamespace as _NS

    class _Msg:
        def __init__(self):
            self.sent = []

        def send_site_parse_health_message(self, title=None, text=None):
            self.sent.append(title)

    class _PrevRepo(_FakeRepo):
        def __init__(self, prev_status, prev_date):
            super().__init__()
            self._prev = prev_status
            self._prev_date = prev_date

        def latest(self, site_id):  # type: ignore[override]
            if self._prev is None:
                return None
            return _NS(status=self._prev, check_date=self._prev_date, detail=None)

    # 场景1：首次异常（无历史）→ 不推送
    engine = _FakeEngine({"FREE": ["//b"], "PEER_COUNT": ["//span[@id='seeders']/span[1]"]})
    engine._selector_stats = {"FREE": 0, "PEER_COUNT": 0}
    cache = _FakeCache(engine)
    msg = _Msg()
    repo1 = _PrevRepo(None, "")
    svc1 = SiteParseHealthService(
        site_cache=cache,  # type: ignore[arg-type]
        siteconf=_SimpleSiteConf(),  # type: ignore[arg-type]
        repo=repo1,  # type: ignore[arg-type]
        message=msg,  # type: ignore[arg-type]
        sample_size=5,
    )
    svc1._fetch_rss = lambda site_info: (RSS_XML, False, False)  # type: ignore[method-assign]
    svc1.check_site(svc1._cache._brush_sites[0])
    assert msg.sent == []

    # 场景2：昨日 degraded + 今日 degraded → 推送
    engine2 = _FakeEngine({"FREE": ["//b"], "PEER_COUNT": ["//span[@id='seeders']/span[1]"]})
    engine2._selector_stats = {"FREE": 0, "PEER_COUNT": 0}
    cache2 = _FakeCache(engine2)
    repo2 = _PrevRepo("degraded", "2026-09-06")
    msg2 = _Msg()
    svc2 = SiteParseHealthService(
        site_cache=cache2,  # type: ignore[arg-type]
        siteconf=_SimpleSiteConf(),  # type: ignore[arg-type]
        repo=repo2,  # type: ignore[arg-type]
        message=msg2,  # type: ignore[arg-type]
        sample_size=5,
    )
    svc2._fetch_rss = lambda site_info: (RSS_XML, False, False)  # type: ignore[method-assign]
    svc2.check_site(svc2._cache._brush_sites[0])
    assert len(msg2.sent) == 1


def test_auth_error_when_all_detail_pages_login():
    """详情页全部登录态（选择器探测返回 auth）→ auth_error"""
    engine = _FakeEngine({"FREE": ["//b"], "PEER_COUNT": ["//span[@id='seeders']/span[1]"]})
    engine._selector_stats = {"FREE": 0, "PEER_COUNT": 0}
    svc, repo = _make_service(engine, {"free": True, "peer_count": 1})
    # html_selector_stats 返回 auth 标记：全部样本登录页
    svc._probe = lambda site_info, url: {"ok": False, "auth": True, "selector_stats": None}  # type: ignore[method-assign]
    result = svc.check_site(svc._cache._brush_sites[0])
    assert result["status"] == "auth_error"


def test_check_all_skips_site_without_parse_config():
    class _NoConfEngine:
        def __init__(self):
            site = SiteDefinition(id="t1", name="站点", domain="example.com")
            self._def = site

        def get_by_url(self, url):
            return self._def

        def get_by_name(self, name):
            return self._def

        def html_selector_stats(self, url, user_config):
            return {"fetched": False}

    class _NoConfCache:
        def __init__(self):
            self._site_engine = _NoConfEngine()
            self._brush_sites = [
                {
                    "id": 1,
                    "name": "站点",
                    "cookie": "",
                    "api_key": "",
                    "bearer_token": "",
                    "ua": "UA",
                    "headers": "{}",
                    "proxy": False,
                    "brush_enable": 1,
                    "rss_enable": 1,
                    "rssurl": "https://example.com/rss.php",
                }
            ]

    class _NoConfSiteConf:
        def check_torrent_attr(self, **kwargs):
            return {}

    class _NoConfRepo(_FakeRepo):
        pass

    svc = SiteParseHealthService(
        site_cache=_NoConfCache(),  # type: ignore[arg-type]
        siteconf=_NoConfSiteConf(),  # type: ignore[arg-type]
        repo=_NoConfRepo(),  # type: ignore[arg-type]
    )
    results = svc.check_all()
    assert results == []


def test_abnormal_continues_silent_until_interval():
    """异常持续：距上次告警 <7 天时静默不重复推送"""
    import json as _json
    from types import SimpleNamespace as _NS

    class _Msg:
        def __init__(self):
            self.sent = []

        def send_site_parse_health_message(self, title=None, text=None):
            self.sent.append(title)

    class _PrevRepo(_FakeRepo):
        def __init__(self, detail):
            super().__init__()
            self._detail = detail

        def latest(self, site_id):  # type: ignore[override]
            return _NS(status="degraded", check_date="2026-09-06", detail=self._detail)

    engine = _FakeEngine({"FREE": ["//b"], "PEER_COUNT": ["//span[@id='seeders']/span[1]"]})
    engine._selector_stats = {"FREE": 0, "PEER_COUNT": 0}
    # 上次告警 1 天前（仍在 7 天窗口内）→ 静默
    repo = _PrevRepo(_json.dumps({"last_alert_date": "2026-09-06"}))
    msg = _Msg()
    svc = SiteParseHealthService(
        site_cache=_FakeCache(engine),  # type: ignore[arg-type]
        siteconf=_SimpleSiteConf(),  # type: ignore[arg-type]
        repo=repo,  # type: ignore[arg-type]
        message=msg,  # type: ignore[arg-type]
        sample_size=5,
    )
    svc._fetch_rss = lambda site_info: (RSS_XML, False, False)  # type: ignore[method-assign]
    svc.check_site(svc._cache._brush_sites[0])
    assert msg.sent == []

    # 上次告警 8 天前（超出间隔）→ 复读推送
    repo8 = _PrevRepo(_json.dumps({"last_alert_date": "2026-08-30"}))
    msg8 = _Msg()
    svc8 = SiteParseHealthService(
        site_cache=_FakeCache(engine),  # type: ignore[arg-type]
        siteconf=_SimpleSiteConf(),  # type: ignore[arg-type]
        repo=repo8,  # type: ignore[arg-type]
        message=msg8,  # type: ignore[arg-type]
        sample_size=5,
    )
    svc8._fetch_rss = lambda site_info: (RSS_XML, False, False)  # type: ignore[method-assign]
    svc8.check_site(svc8._cache._brush_sites[0])
    assert len(msg8.sent) == 1


def test_degraded_when_api_field_missing():
    """API 站配置字段（如 peer_count）在响应中不存在 → degraded 提示接口字段缺失"""
    engine = _FakeEngine(None, is_html=False)
    engine._selector_stats = {}
    svc, repo = _make_service(engine, {"free": False, "peer_count": 0})
    # 探针返回：ok，但 api.peer_count 恒缺失
    svc._probe = lambda site_info, url: {  # type: ignore[method-assign]
        "ok": True,
        "free": False,
        "peer_count": 0,
        "selector_stats": {"selectors": {"api.free": 1, "api.peer_count": 0}},
    }
    result = svc.check_site(svc._cache._brush_sites[0])
    assert result["status"] == "degraded"
    assert any("peer_count" in i for i in result["issues"])
