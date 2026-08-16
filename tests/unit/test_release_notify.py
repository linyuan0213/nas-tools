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

    def test_nested_backtick_and_pre_literal(self):
        """嵌套反引号（`` `代码` ``）与 <pre> 字面量：不错位、不产生裸 HTML 标签（修复 Telegram pre 未闭合 400）"""
        changelog = "- **发布通知**：不再在 `<pre>` 内显示原始符号，代码 `` `current_ep` `` 等宽"
        out = markdown_to_telegram_html(changelog)
        # <pre> 字面量被转义，不产生裸 <pre> 标签
        assert "<pre>" not in out
        assert "&lt;pre&gt;" in out
        # 嵌套反引号不产生错位 <code>
        assert "`<code>" not in out

    def test_stray_angle_bracket_escaped(self):
        """残留的孤立 <（非合法标签）被转义，防止未闭合标签触发 Telegram 400"""
        out = markdown_to_telegram_html("**A** 文本<残留 和 >符号")
        assert "<b>A</b>" in out
        assert "&lt;残留" in out
