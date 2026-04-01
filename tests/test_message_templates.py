#!/usr/bin/env python3
"""
消息通知模板功能测试
"""
import pytest
import sys
import os
import time
import re

# 添加项目根目录到路径
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from jinja2 import Environment, BaseLoader
from app.utils import StringUtils


# 模拟过滤器函数（从 app/message/message.py 复制）
def _filesize_filter(value):
    """Jinja2 filter: 格式化文件大小"""
    if value is None:
        return ''
    return StringUtils.str_filesize(value) if value else ''


def _datetime_filter(value, format_str='%Y-%m-%d %H:%M:%S'):
    """Jinja2 filter: 格式化日期时间"""
    if not value:
        return ''
    if isinstance(value, (int, float)):
        return time.strftime(format_str, time.localtime(value))
    if isinstance(value, str):
        try:
            timestamp = float(value)
            return time.strftime(format_str, time.localtime(timestamp))
        except (ValueError, TypeError):
            return value
    return str(value)


def _default_filter(value, default_value=''):
    """Jinja2 filter: 默认值处理"""
    if value is None or value == '':
        return default_value
    return value


def _yesno_filter(value, yes='是', no='否'):
    """Jinja2 filter: 布尔值转换为是/否"""
    if value is True:
        return yes
    elif value is False:
        return no
    return no


def _truncatestr_filter(value, length=100, suffix='...'):
    """Jinja2 filter: 截断字符串"""
    if not value:
        return ''
    value = str(value)
    if len(value) <= length:
        return value
    return value[:length - len(suffix)] + suffix


def _striptags_filter(value):
    """Jinja2 filter: 去除HTML标签"""
    if not value:
        return ''
    return re.sub(r'<[^>]+>', '', str(value))


@pytest.fixture
def template_env():
    """创建带自定义过滤器的 Jinja2 环境"""
    env = Environment(loader=BaseLoader())
    env.filters['filesize'] = _filesize_filter
    env.filters['datetime'] = _datetime_filter
    env.filters['default'] = _default_filter
    env.filters['yesno'] = _yesno_filter
    env.filters['truncatestr'] = _truncatestr_filter
    env.filters['striptags'] = _striptags_filter
    return env


class MockMediaItem:
    """模拟下载项对象"""
    def __init__(self):
        self.title = "测试剧集"
        self.year = "2024"
        self.site = "测试站点"
        self.size = 1051234567  # 约 1002.76M
        self.seeders = 12
        self.peers = 3
        self.org_string = "Test.Show.2024.S01E05.2160p.WEB-DL.DDP5.1.H.264"
        self.description = "<p>这是一个测试种子的描述信息</p>"
        self.hit_and_run = False
        self.user_name = "admin"
        self.page_url = "https://testsite.com/torrent/123"
        self.vote_average = 8.5
        self.begin_season = 1
        self.end_season = None
        self.begin_episode = 5
        self.end_episode = None
        self.resource_type = "WEB-DL"
        self.resource_pix = "2160p"

    def get_title_ep_string(self):
        return f"{self.title} ({self.year}) S{self.begin_season:02d}E{self.begin_episode:02d}"

    def get_star_string(self):
        return f"★★★★☆ ({self.vote_average})"

    def get_resource_type_string(self):
        return f"{self.resource_type} {self.resource_pix}"

    def get_volume_factor_string(self):
        return "免费"

    def get_season_string(self):
        return f"S{self.begin_season:02d}"

    def get_episode_string(self):
        return f"E{self.begin_episode:02d}"

    def get_title_string(self):
        return f"{self.title} ({self.year})"


@pytest.fixture
def mock_item():
    """提供模拟的媒体项"""
    return MockMediaItem()


# ============ 过滤器测试 ============

def test_filesize_filter():
    """测试文件大小过滤器"""
    # 注意：实际值取决于 StringUtils.str_filesize 的实现（使用 1024 或 1000）
    result = _filesize_filter(1051234567)
    assert "M" in result  # 验证是 MB 格式
    assert result.startswith("1002")
    # 0 是 falsy 值，过滤器返回空字符串（符合设计）
    assert _filesize_filter(0) == ""
    assert _filesize_filter(None) == ""


def test_datetime_filter():
    """测试日期时间过滤器"""
    timestamp = 1711459200  # 2024-03-26 12:00:00
    result = _datetime_filter(timestamp, '%Y-%m-%d')
    assert result == "2024-03-26"


def test_default_filter():
    """测试默认值过滤器"""
    assert _default_filter(None, "未知") == "未知"
    assert _default_filter("", "未知") == "未知"
    assert _default_filter("有值", "未知") == "有值"


def test_yesno_filter():
    """测试是/否过滤器"""
    assert _yesno_filter(True, "是", "否") == "是"
    assert _yesno_filter(False, "是", "否") == "否"
    assert _yesno_filter(None, "是", "否") == "否"


def test_truncatestr_filter():
    """测试字符串截断过滤器"""
    long_str = "这是一个很长的字符串需要被截断"
    result = _truncatestr_filter(long_str, 10, "...")
    assert len(result) == 10
    assert result.endswith("...")


def test_striptags_filter():
    """测试去除HTML标签过滤器"""
    html = "<p>这是<b>测试</b></p>"
    assert _striptags_filter(html) == "这是测试"


# ============ 模板测试 ============

def test_download_start_template_rich(template_env, mock_item):
    """测试下载开始模板（富文本格式）"""
    template_str = """🎬 {{ item.get_title_ep_string() }} 开始下载 ⬇️
🌐 站点：{{ item.site|default('未知') }} ｜ 💾 大小：{{ item.size|filesize }}
📦 质量：{{ item.get_resource_type_string()|default('未知') }}

🧲 种子：{{ item.org_string|truncatestr(50) }}
🌱 做种：{{ item.seeders }} ｜ ⚡️ 促销：{{ item.get_volume_factor_string() }} ｜ 🚨 H&R：{{ item.hit_and_run|yesno('是','否') }}"""

    template = template_env.from_string(template_str)
    result = template.render(item=mock_item)

    assert "🎬 测试剧集 (2024) S01E05 开始下载" in result
    assert "🌐 站点：测试站点" in result
    assert "💾 大小：" in result and "M" in result  # 验证大小格式
    assert "📦 质量：WEB-DL 2160p" in result
    assert "🧲 种子：" in result
    assert "🚨 H&R：否" in result


def test_download_start_template_simplified(template_env, mock_item):
    """测试下载开始模板（使用简化变量）"""
    # 准备简化变量（模拟 send_download_message 中的处理）
    description_clean = re.sub(r'<[^>]+>', '', mock_item.description)
    size_str = StringUtils.str_filesize(mock_item.size)

    variables = {
        "item": mock_item,
        "title": mock_item.title,
        "year": mock_item.year,
        "season": mock_item.get_season_string(),
        "episode": mock_item.get_episode_string(),
        "site": mock_item.site,
        "size": mock_item.size,
        "size_str": size_str,
        "seeders": mock_item.seeders,
        "peers": mock_item.peers,
        "org_string": mock_item.org_string,
        "description": description_clean,
        "resource_type": mock_item.get_resource_type_string(),
        "volume_factor": mock_item.get_volume_factor_string(),
        "hit_and_run": mock_item.hit_and_run,
        "user_name": mock_item.user_name,
        "title_ep_string": mock_item.get_title_ep_string(),
    }

    template_str = """🎬 {{ title_ep_string|default(item.get_title_ep_string()) }} 开始下载 ⬇️
🌐 站点：{{ site|default(item.site)|default('未知') }} ｜ 💾 大小：{{ size_str|default(item.size|filesize) }}
📦 质量：{{ resource_type|default(item.get_resource_type_string())|default('未知') }}

🧲 种子：{{ org_string|default(item.org_string)|truncatestr(50) }}
🌱 做种：{{ seeders|default(item.seeders)|default(0) }} ｜ ⚡️ 促销：{{ volume_factor|default(item.get_volume_factor_string())|default('未知') }} ｜ 🚨 H&R：{{ hit_and_run|default(item.hit_and_run)|yesno('是','否') }}"""

    template = template_env.from_string(template_str)
    result = template.render(**variables)

    assert "🎬 测试剧集 (2024) S01E05 开始下载" in result
    assert "🌐 站点：测试站点" in result
    assert "📦 质量：WEB-DL 2160p" in result
    assert "🚨 H&R：否" in result


def test_transfer_finished_template(template_env, mock_item):
    """测试入库完成模板"""
    template_str = """✅ {{ media_info.get_title_string() }} 已入库
⭐ {{ media_info.get_star_string() }}
📺 类型：电视剧
📦 质量：{{ media_info.get_resource_type_string()|default('未知') }}
💾 大小：{{ media_info.size|filesize }}"""

    template = template_env.from_string(template_str)
    result = template.render(media_info=mock_item)

    assert "✅ 测试剧集 (2024) 已入库" in result
    assert "⭐ ★★★★☆ (8.5)" in result
    assert "💾 大小：" in result and "M" in result  # 验证大小格式


def test_rss_success_template(template_env, mock_item):
    """测试订阅成功模板"""
    template_str = """📌 {{ media_info.get_title_string() }} 已添加订阅
⭐ {{ media_info.get_star_string() }}
📺 类型：电视剧
📅 年份：{{ media_info.year|default('未知') }}"""

    template = template_env.from_string(template_str)
    result = template.render(media_info=mock_item)

    assert "📌 测试剧集 (2024) 已添加订阅" in result
    assert "⭐ ★★★★☆ (8.5)" in result
    assert "📅 年份：2024" in result


def test_template_with_missing_values(template_env):
    """测试模板处理缺失值的情况"""
    template_str = """站点：{{ site|default('未知站点') }}
大小：{{ size|filesize|default('未知大小') }}
H&R：{{ hit_and_run|yesno('是','否') }}"""

    template = template_env.from_string(template_str)
    result = template.render(site=None, size=0, hit_and_run=None)

    assert "站点：未知站点" in result
    assert "H&R：否" in result
