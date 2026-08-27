"""NexusPHP 站点做种统计解析单元测试（含 keepfrds 配置回归）."""

import json
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from app.sites.siteuserinfo import nexus_php
from app.sites.siteuserinfo.config_html import ConfigHtmlUserInfo


class _MockInstance(ConfigHtmlUserInfo):
    def __init__(self):
        self._index_html = ""
        self.userid = None
        self.seeding = 0
        self.seeding_size = 0
        self.seeding_info = "[]"
        self._base_url_str = "https://pt.keepfrds.com"
        self._def = None
        self._fetch_html = MagicMock(return_value=None)


def _keepfrds_def():
    """加载真实 keepfrds.json 的 user_info 配置。"""
    with open("config/sites/html/keepfrds.json", encoding="utf-8") as f:
        cfg = json.load(f)
    return SimpleNamespace(user_info=cfg.get("user_info"))


def _seeding_page():
    return """
    <table class="torrents">
      <tr><td class="colhead">类型</td><td>标题</td><td>魔力</td><td>时间</td>
          <td>大小</td><td>做种</td><td>下载</td><td>完成</td><td>发布者</td></tr>
      <tr><td></td><td>Title A</td><td>0</td><td>1年</td><td>8.08GiB</td><td>47</td><td>0</td>
          <td>678</td><td>匿名</td></tr>
      <tr><td></td><td>Title B</td><td>0</td><td>2年</td><td>2.00GiB</td><td>5</td><td>0</td>
          <td>10</td><td>匿名</td></tr>
    </table>
    """


class TestNexusPhpSeeding:
    def test_keepfrds_config_has_seeding_page(self):
        ui = _keepfrds_def().user_info
        assert ui and ui.get("seeding", {}).get("page") == "torrents.php?option-torrents=3&userid={userid}"

    def test_parse_seeding_with_keepfrds_config(self):
        ins = _MockInstance()
        ins.userid = "41240"
        ins._def = _keepfrds_def()

        def fake_fetch(url, referer=None, use_ajax_headers=False):
            if "userdetails" in url:
                return None
            if "torrents.php" in url:
                return _seeding_page()
            return None

        ins._fetch_html = fake_fetch
        nexus_php._parse_seeding(ins)  # type: ignore[arg-type]

        assert ins.seeding == 2
        # 8.08GiB + 2.00GiB
        assert ins.seeding_size == pytest.approx(
            nexus_php.StringUtils.num_filesize("8.08GiB") + nexus_php.StringUtils.num_filesize("2GiB"),
            rel=1e-6,
        )

    def test_parse_seeding_no_rows(self):
        ins = _MockInstance()
        ins.userid = "41240"
        ins._def = _keepfrds_def()
        ins._fetch_html = MagicMock(return_value="<html><body>无做种</body></html>")
        nexus_php._parse_seeding(ins)  # type: ignore[arg-type]
        assert ins.seeding == 0
        assert ins.seeding_size == 0
