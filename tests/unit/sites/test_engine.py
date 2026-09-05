"""SiteEngine 单元测试."""

import json
from unittest.mock import MagicMock

from lxml import etree

import app.sites.engine as engine_mod
from app.sites.engine import SiteApiConfig, SiteDefinition, SiteEngine, _extract_detail_labels


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
            '{"data": {"status": {"discount": "PERCENT_50", "discountEndTime": None}}}',
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
