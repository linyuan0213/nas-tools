"""SiteEngine 单元测试."""

import json
from unittest.mock import MagicMock

from lxml import etree

import app.sites.engine as engine_mod
from app.sites.engine import (
    SiteApiConfig,
    SiteDefinition,
    SiteEngine,
    TorrentAttrFetchError,
    _extract_detail_labels,
)


class TestSiteEngine:
    def test_get_by_url_uses_domain_index(self):
        engine = SiteEngine(definitions_dir="/nonexistent")
        site = SiteDefinition(id="t1", name="Test", domain="example.com", domain_aliases=["alias.org"])
        engine.register(site)

        assert engine.get_by_url("https://example.com/torrent/1") is site
        assert engine.get_by_url("https://alias.org/torrent/1") is site
        assert engine.get_by_url("https://unknown.com/torrent/1") is None

    def test_get_by_domain(self):
        engine = SiteEngine(definitions_dir="/nonexistent")
        site = SiteDefinition(id="t1", name="Test", domain="example.com")
        engine.register(site)
        assert engine.get_by_domain("example.com") is site
        assert engine.get_by_domain("EXAMPLE.COM") is site
        assert engine.get_by_domain("unknown.com") is None

    def test_get_by_name(self):
        engine = SiteEngine(definitions_dir="/nonexistent")
        site = SiteDefinition(id="t1", name="TestSite")
        engine.register(site)
        assert engine.get_by_name("TestSite") is site
        assert engine.get_by_name("testsite") is site
        assert engine.get_by_name("t1") is site
        assert engine.get_by_name("T1") is site
        assert engine.get_by_name("unknown") is None
        assert engine.get_by_name("") is None

    def test_extract_detail_labels_with_dict_fields(self):
        site = MagicMock()
        site.html = MagicMock()
        site.html.torrents = {"fields": {"labels": {"selector": "span.tag"}}}
        doc = etree.fromstring("<div><span class='tag'>A</span><span class='tag'>B</span></div>")
        assert _extract_detail_labels(doc, site) == "A|B"

    def test_extract_detail_labels_without_fields(self):
        site = MagicMock()
        site.html = MagicMock()
        site.html.torrents = {}
        doc = etree.fromstring("<div><span class='tag'>A</span></div>")
        assert _extract_detail_labels(doc, site) == "A"


class _FakeClient:
    """返回预置 JSON 文本的假 HttpClient"""

    text = "{}"

    def __init__(self, *args, **kwargs):
        pass

    def post(self, **kwargs):
        return type("Resp", (), {"text": self.text})

    def get(self, **kwargs):
        return type("Resp", (), {"text": self.text})


def _make_mteam_like_engine(monkeypatch, payload: str, torrent_attr: dict):
    site = SiteDefinition(id="mteam", name="M-Team", domain="kp.m-team.cc", domain_aliases=["api.m-team.io"])
    site.api = SiteApiConfig(
        base_url="https://api.m-team.io", auth={"type": "api_key", "header_name": "x-api-key"}, endpoints={}
    )
    site.torrent_attr = {
        "method": "POST",
        "path": "/api/torrent/detail",
        "body": {"id": "{tid}"},
        "response": torrent_attr,
    }
    engine = SiteEngine(definitions_dir="/nonexistent")
    engine.register(site)
    fake = _FakeClient()
    fake.text = payload
    monkeypatch.setattr(engine_mod, "HttpClient", lambda *a, **k: fake)
    return engine


def _mteam_attr_config(with_window: bool = True) -> dict:
    cfg = {
        "free_key": "data.status.discount",
        "free_value": "FREE",
        "2xfree_key": "data.status.discount",
        "2xfree_value": "FREE_2X",
        "site_free_key": "data.status.promotionRule.discount",
        "site_free_value": "FREE",
        "site_2xfree_key": "data.status.promotionRule.discount",
        "site_2xfree_value": "FREE_2X",
    }
    if with_window:
        cfg.update(
            {
                "site_free_start_key": "data.status.promotionRule.startTime",
                "site_free_end_key": "data.status.promotionRule.endTime",
                "site_2xfree_start_key": "data.status.promotionRule.startTime",
                "site_2xfree_end_key": "data.status.promotionRule.endTime",
            }
        )
    return cfg


def _promo_payload(
    badge: str = "PERCENT_50", start: str = "2020-01-01 00:00:00", end: str = "2099-01-01 00:00:00"
) -> str:
    return json.dumps(
        {
            "data": {
                "status": {
                    "discount": badge,
                    "discountEndTime": None,
                    "promotionRule": {"discount": "FREE", "startTime": start, "endTime": end},
                }
            }
        }
    )


class TestApiSiteWideFreeAttr:
    """站点级活动（全站免费）时种子属性的免费补判"""

    def _resolve(self, monkeypatch, payload, torrent_attr=None):
        engine = _make_mteam_like_engine(monkeypatch, payload, torrent_attr or _mteam_attr_config())
        return engine.resolve_torrent_attr(torrent_url="https://kp.m-team.cc/detail/123", api_key="test-key")

    def test_site_wide_free_active_marks_percent_torrent_free(self, monkeypatch):
        # 全站 FREE 活动有效期内，即使种子徽标为 PERCENT_50 也应视为免费
        ret = self._resolve(monkeypatch, _promo_payload(badge="PERCENT_50"))
        assert ret["free"] is True
        assert ret["2xfree"] is False

    def test_site_wide_free_expired_not_free(self, monkeypatch):
        ret = self._resolve(monkeypatch, _promo_payload(badge="PERCENT_50", end="2020-01-01 00:00:00"))
        assert ret["free"] is False

    def test_site_wide_free_not_started_not_free(self, monkeypatch):
        ret = self._resolve(monkeypatch, _promo_payload(badge="PERCENT_50", start="2099-01-01 00:00:00"))
        assert ret["free"] is False

    def test_no_promotion_rule_not_free(self, monkeypatch):
        ret = self._resolve(
            monkeypatch,
            '{"data": {"status": {"discount": "PERCENT_50", "discountEndTime": null}}}',
        )
        assert ret["free"] is False

    def test_badge_free_still_free_without_window_config(self, monkeypatch):
        # 未配置时间窗时只按规则值匹配（兼容无时间字段的站点配置）
        ret = self._resolve(
            monkeypatch,
            _promo_payload(badge="FREE", end="2099-01-01 00:00:00"),
            torrent_attr=_mteam_attr_config(with_window=False),
        )
        assert ret["free"] is True

    def test_site_2xfree_active_sets_2xfree(self, monkeypatch):
        payload = json_dumps_site_discount("FREE_2X")
        ret = self._resolve(monkeypatch, payload)
        assert ret["free"] is True
        assert ret["2xfree"] is True

    def test_legacy_config_without_site_keys_unaffected(self, monkeypatch):
        # 未启用 site_* 配置的站点行为不变
        ret = self._resolve(
            monkeypatch,
            _promo_payload(badge="PERCENT_50"),
            torrent_attr={
                "free_key": "data.status.discount",
                "free_value": "FREE",
                "2xfree_key": "data.status.discount",
                "2xfree_value": "FREE_2X",
            },
        )
        assert ret["free"] is False
        assert ret["2xfree"] is False


def json_dumps_site_discount(rule_discount: str) -> str:
    return json.dumps(
        {
            "data": {
                "status": {
                    "discount": "NORMAL",
                    "discountEndTime": None,
                    "promotionRule": {
                        "discount": rule_discount,
                        "startTime": "2020-01-01 00:00:00",
                        "endTime": "2099-01-01 00:00:00",
                    },
                }
            }
        }
    )


class TestGetTidByUrlHostDigits:
    """域名含数字不得抢占种子 id（如 u2.dmhy.org 的 2）"""

    def test_u2_style_url_extracts_query_id(self):
        from app.sites.engine import SiteEngine, get_tid_by_url

        engine = SiteEngine(definitions_dir="/nonexistent")
        site = SiteDefinition(id="u2", name="幼儿园", domain="u2.dmhy.org", tid_pattern=r"\d+",
                              detail_page_url="/details.php?id={tid}")
        engine.register(site)
        assert get_tid_by_url("https://u2.dmhy.org/details.php?id=66055", site_engine=engine) == "66055"

    def test_host_digit_not_picked_for_plain_digits_pattern(self):
        from app.sites.engine import SiteEngine, get_tid_by_url

        engine = SiteEngine(definitions_dir="/nonexistent")
        site = SiteDefinition(id="t", name="站", domain="my2pt.example.com", tid_pattern=r"\d+")
        engine.register(site)
        # 无 id= 参数：取路径/查询里的最后一个数字
        assert get_tid_by_url("https://my2pt.example.com/details?id=12345", site_engine=engine) == "12345"


class TestHtmlPubdateExtract:
    """详情页 PUBDATE 提取：刷流时间规则以种子页面日期为准"""

    def _engine(self, monkeypatch, html_text, conf=None):
        from types import SimpleNamespace

        engine = SiteEngine(definitions_dir="/nonexistent")
        site = SiteDefinition(id="u2", name="幼儿园", domain="u2.dmhy.org", detail_page_url="/details.php?id={tid}")
        default_conf = {
            "PUBDATE": ["//td[contains(., '发布时间')]//time/@title"],
            "PEER_COUNT": ["//div[@id='peercount']/b[1]"],
        }
        site.html = SimpleNamespace(conf=conf or default_conf, torrents=[])  # type: ignore[attr-defined]
        engine.register(site)
        monkeypatch.setattr(
            engine, "_fetch_page_ex", lambda *a, **k: (html_text, "https://u2.dmhy.org/details.php?id=1")
        )
        return engine

    def test_pubdate_attr_extracted(self, monkeypatch):
        html = ("<html><body><a href='logout.php'>退出</a>"
                "<td class='rowfollow'>发布时间: <time title='2026-09-07 12:34:56'>2026-09-07</time></td>"
                "<div id='peercount'><b>1个做种者</b></div></body></html>")
        engine = self._engine(monkeypatch, html)
        stats = engine.html_selector_stats("https://u2.dmhy.org/details.php?id=1", {})
        assert stats.get("pubdate") == "2026-09-07 12:34:56"
        # resolve_torrent_attr 也带 pubdate
        monkeypatch.setattr(engine, "_fetch_page", lambda *a, **k: html)
        ret = engine.resolve_torrent_attr("https://u2.dmhy.org/details.php?id=1", cookie="c")
        assert ret.get("pubdate") == "2026-09-07 12:34:56"


class TestHtmlSelectorStats:
    """html_selector_stats：HTML 详情页选择器命中统计与登录页检测."""

    def _engine(self, monkeypatch, html_text, conf=None):
        from types import SimpleNamespace

        engine = SiteEngine(definitions_dir="/nonexistent")
        site = SiteDefinition(id="t1", name="站点", domain="example.com", detail_page_url="/d/{tid}")
        default_conf = {"FREE": ["//b[@class='free']"], "PEER_COUNT": ["//span[@id='seeders']/span[1]"]}
        site.html = SimpleNamespace(conf=conf or default_conf, torrents=[])  # type: ignore[attr-defined]
        engine.register(site)
        monkeypatch.setattr(engine, "_fetch_page_ex", lambda *a, **k: (html_text, "https://example.com/d/1"))
        return engine

    def test_login_page_detected(self, monkeypatch):
        """登录页（takelogin 表单）→ auth=True，不算选择器失效"""
        engine = self._engine(monkeypatch, "<html><body><form action='takelogin.php'></form></body></html>")
        ret = engine.html_selector_stats("https://example.com/d/1", {})
        assert ret.get("auth") is True

    def test_normal_page_selector_hits(self, monkeypatch):
        """正常详情页：各选择器命中数正确统计"""
        html = ("<html><body><a href='logout.php'>退出</a>"
                "<b class='free'>免费</b><span id='seeders'><span>12</span></span></body></html>")
        engine = self._engine(monkeypatch, html)
        ret = engine.html_selector_stats("https://example.com/d/1", {})
        assert ret.get("fetched") is True
        assert ret["selectors"]["FREE"] == 1
        assert ret["selectors"]["PEER_COUNT"] == 1
        assert ret["peer_value"] == 12


class TestApiFreeValueZero:
    """free_value 为 0（数值判免费，如朱雀 downloadRate==0）不得因真值判断漏判"""

    def test_free_when_value_zero(self, monkeypatch):
        torrent_attr = {"method": "GET", "path": "/api/torrent/info", "params": {"id": "{tid}"},
                        "response": {"free_key": "data.torrent.downloadRate", "free_value": 0}}
        site = SiteDefinition(
            id="tnode", name="朱雀", domain="zhuque.in", detail_page_url="/torrent/info/{tid}",
            api=SiteApiConfig(
                base_url="https://zhuque.in", auth={"type": "api_key", "header_name": "x-api-key"}, endpoints={}
            ),
        )
        site.torrent_attr = torrent_attr
        engine = SiteEngine(definitions_dir="/nonexistent")
        engine.register(site)
        fake = _FakeClient()
        fake.text = '{"code":0,"data":{"torrent":{"downloadRate":0,"seeding":1}}}'
        monkeypatch.setattr(engine_mod, "HttpClient", lambda *a, **k: fake)
        ret = engine.resolve_torrent_attr("https://zhuque.in/torrent/info/54638", cookie="c")
        assert ret["free"] is True

    def test_not_free_when_value_one(self, monkeypatch):
        torrent_attr = {"method": "GET", "path": "/api/torrent/info", "params": {"id": "{tid}"},
                        "response": {"free_key": "data.torrent.downloadRate", "free_value": 0}}
        site = SiteDefinition(
            id="tnode2", name="朱雀", domain="zhuque2.in", detail_page_url="/torrent/info/{tid}",
            api=SiteApiConfig(
                base_url="https://zhuque2.in", auth={"type": "api_key", "header_name": "x-api-key"}, endpoints={}
            ),
        )
        site.torrent_attr = torrent_attr
        engine = SiteEngine(definitions_dir="/nonexistent")
        engine.register(site)
        fake = _FakeClient()
        fake.text = '{"code":0,"data":{"torrent":{"downloadRate":1,"seeding":1}}}'
        monkeypatch.setattr(engine_mod, "HttpClient", lambda *a, **k: fake)
        ret = engine.resolve_torrent_attr("https://zhuque2.in/torrent/info/1", cookie="c")
        assert ret["free"] is False


class TestApiAttrFailClosed:
    """API 站点种子属性解析失败时必须收敛（抛 TorrentAttrFetchError），不得按"非免费"误判删种"""

    def test_business_error_response_raises(self, monkeypatch):
        """业务错误 JSON（无 data，如限流/非法客户端）→ 属性未知"""
        import pytest

        engine = _make_mteam_like_engine(monkeypatch, '{"code": 1, "message": "非法用戶端"}', _mteam_attr_config())
        with pytest.raises(TorrentAttrFetchError):
            engine.resolve_torrent_attr(torrent_url="https://kp.m-team.cc/detail/123", api_key="test-key")

    def test_null_data_response_raises(self, monkeypatch):
        """data 为 null（业务失败）→ 属性未知"""
        import pytest

        engine = _make_mteam_like_engine(monkeypatch, '{"code": 1, "data": None}', _mteam_attr_config())
        with pytest.raises(TorrentAttrFetchError):
            engine.resolve_torrent_attr(torrent_url="https://kp.m-team.cc/detail/123", api_key="test-key")

    def test_non_json_response_raises(self, monkeypatch):
        """非 JSON（302 HTML 错误页等）→ 属性未知"""
        import pytest

        engine = _make_mteam_like_engine(monkeypatch, "<html><body>302 Found</body></html>", _mteam_attr_config())
        with pytest.raises(TorrentAttrFetchError):
            engine.resolve_torrent_attr(torrent_url="https://kp.m-team.cc/detail/123", api_key="test-key")

    def test_unmatched_site_raises(self):
        """URL 未匹配任何站点 → 属性未知（原为返回 free=False 默认值导致误删）"""
        import pytest

        engine = SiteEngine(definitions_dir="/nonexistent")
        with pytest.raises(TorrentAttrFetchError):
            engine.resolve_torrent_attr(torrent_url="https://unknown.example/detail/1")

    def test_tid_extract_failure_raises(self, monkeypatch):
        """无法从 URL 提取 TID（如无数字的签名链接）→ 属性未知"""
        import pytest

        engine = _make_mteam_like_engine(monkeypatch, _promo_payload(badge="FREE"), _mteam_attr_config())
        with pytest.raises(TorrentAttrFetchError):
            engine.resolve_torrent_attr(torrent_url="https://kp.m-team.cc/rss/dlx?sign=abcdef", api_key="test-key")

    def test_success_normal_discount_not_free(self, monkeypatch):
        """正常响应但 discount=NORMAL → 正确判定非免费（不误抛异常）"""
        ret = self._resolve_ok(monkeypatch, '{"code": 0, "data": {"status": {"discount": "NORMAL"}}}')
        assert ret["free"] is False

    def _resolve_ok(self, monkeypatch, payload):
        engine = _make_mteam_like_engine(monkeypatch, payload, _mteam_attr_config())
        return engine.resolve_torrent_attr(torrent_url="https://kp.m-team.cc/detail/123", api_key="test-key")


class TestSiteRuleTimeParse:
    """站点级活动时间窗解析：兼容 ISO 与 epoch 秒/毫秒."""

    def test_parse_iso_string(self):
        from datetime import datetime, timezone

        from app.sites.engine import SiteEngine

        dt = SiteEngine._parse_rule_time("2026-09-01T00:00:00+08:00")
        assert dt.tzinfo is not None
        assert dt == datetime(2026, 8, 31, 16, 0, tzinfo=timezone.utc)

    def test_parse_epoch_ms(self):
        from app.sites.engine import SiteEngine

        # 2026-09-01 00:00:00 UTC 的毫秒时间戳
        ms = 1780272000000
        dt = SiteEngine._parse_rule_time(ms)
        assert int(dt.timestamp()) == ms // 1000

    def test_parse_epoch_numeric_string(self):
        from app.sites.engine import SiteEngine

        dt = SiteEngine._parse_rule_time("1780272000")
        assert int(dt.timestamp()) == 1780272000
