"""GitHub changelog → Telegram HTML 转换测试（发布通知 markdown 渲染修复）."""

from scripts.release_notify import markdown_to_telegram_html


class TestMarkdownToTelegramHtml:
    def test_heading_bold(self):
        assert markdown_to_telegram_html("## v4.6.3 (2026-08-16)") == "<b>v4.6.3 (2026-08-16)</b>"
        assert markdown_to_telegram_html("### 修复") == "<b>修复</b>"

    def test_list_item_bullet(self):
        out = markdown_to_telegram_html("- **中文名缺失**：兜底提取")
        assert out == "• <b>中文名缺失</b>：兜底提取"

    def test_bold_and_italic(self):
        out = markdown_to_telegram_html("**加粗** 和 *斜体*")
        assert out == "<b>加粗</b> 和 <i>斜体</i>"

    def test_code(self):
        out = markdown_to_telegram_html("key 增加 `TMDB_CACHE_VERSION`")
        assert out == "key 增加 <code>TMDB_CACHE_VERSION</code>"

    def test_link(self):
        out = markdown_to_telegram_html("[查看 Release](https://github.com/x/releases/tag/v4.6.3)")
        assert out == '<a href="https://github.com/x/releases/tag/v4.6.3">查看 Release</a>'

    def test_escape_special_chars_before_tags(self):
        """原始 & < > " 转义，但转换插入的 <b>/<a> 标签不被转义"""
        out = markdown_to_telegram_html('**A&B** 且 3<4 的 "引号"')
        assert "<b>A&amp;B</b>" in out
        assert "3&lt;4" in out
        assert "&quot;引号&quot;" in out

    def test_single_asterisk_not_broken(self):
        """*斜体* 不误伤已转的 **加粗**"""
        out = markdown_to_telegram_html("**a** 和 *b*")
        assert out == "<b>a</b> 和 <i>b</i>"

    def test_full_changelog_like(self):
        changelog = """## v4.6.3 (2026-08-16)

### 修复
- **订阅进度**：重订阅从订阅起点推导断点（支持中途订阅），`current_ep` 随转移推进
- **发布通知**：changelog markdown 转 Telegram HTML，不再显示原始 `**` 符号

🔗 详情见 [Release](https://github.com/linyuan0213/nexus-media/releases)"""
        out = markdown_to_telegram_html(changelog)
        assert "<b>v4.6.3 (2026-08-16)</b>" in out
        assert "<b>修复</b>" in out
        assert "• <b>订阅进度</b>：重订阅从订阅起点推导断点" in out
        assert "<code>current_ep</code>" in out
        assert '<a href="https://github.com/linyuan0213/nexus-media/releases">Release</a>' in out
