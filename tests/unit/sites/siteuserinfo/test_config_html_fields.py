"""ConfigHtml 字段解析回归测试（空 selector regex 提取 / type=html 用户名解析）."""

import json
from types import SimpleNamespace
from unittest.mock import MagicMock

from app.sites.siteuserinfo.config_html import ConfigHtmlUserInfo


class _MockInstance(ConfigHtmlUserInfo):
    def __init__(self):
        self._index_html = ""
        self._base_url_str = "https://x.test"
        self._def = None
        self._fetch_html = MagicMock(return_value=None)
        self.userid = None
        self.username = None
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


def _extract(doc, html, cfg):
    ins = _MockInstance()
    return ins._extract_field(doc, html, cfg)


class TestExtractField:
    def test_empty_selector_regex_extracts_from_html(self):
        """空 selector + extract=regex：直接在整页 HTML 上跑正则（audiences join_at 场景）"""
        html = (
            '<div class="ud-hero__meta"><span><i class="far fa-calendar-plus">'
            '</i>加入日期：2024-04-05 16:55:17 (2年5月前)</span></div>'
        )
        cfg = {
            "selector": "",
            "extract": "regex",
            "pattern": r"加入日期[\s\S]*?(\d{4}-\d{2}-\d{2}[ T]\d{2}:\d{2}:\d{2})",
        }
        assert _extract(None, html, cfg) == "2024-04-05 16:55:17"

    def test_empty_selector_text_returns_none(self):
        """空 selector + 非 regex 提取 → None（保持原行为）"""
        assert _extract(None, "<html></html>", {"selector": "", "extract": "text"}) is None


class TestConfigHtmlParse:
    def test_html_fields_branch_extracts_username(self):
        """type=html + fields 分支：_parse_base_info 解析用户名（hhanclub 场景）"""
        ins = _MockInstance()
        ins._index_html = '<html><body><a href="userdetails.php?id=19504"><b>linyuan213</b></a></body></html>'
        ins._def = SimpleNamespace(
            user_info={"type": "html", "page": "userdetails.php?id={userid}", "fields": {}}
        )
        ins.parse()  # type: ignore[arg-type]
        assert ins.username == "linyuan213"

    def test_audiences_config_has_page_and_join_at_regex(self):
        """audiences.json：user_info 配置含 page 与 join_at 整页正则"""
        with open("config/sites/html/audiences.json", encoding="utf-8") as f:
            cfg = json.load(f)
        ui = cfg["user_info"]
        assert ui.get("page") == "userdetails.php?id={userid}"
        assert "加入日期" in ui["fields"]["join_at"]["pattern"]
        assert ui["fields"]["join_at"]["extract"] == "regex"

    def test_hhanclub_config_fields_missing_username_is_covered_by_base_info(self):
        """hhanclub.json：fields 无 username 时由 _parse_base_info 兜底"""
        with open("config/sites/html/hhanclub.json", encoding="utf-8") as f:
            cfg = json.load(f)
        assert "username" not in cfg["user_info"]["fields"]
