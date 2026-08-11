"""渠道感知 Markdown 格式化器单元测试"""

from app.domain.enums import SearchType
from app.message.formatter import (
    dialect_for_channel,
    format_agent_message,
    to_plain,
    to_slack,
    to_telegram,
)

_SAMPLE = """## 系统状态

| 项目 | 状态 |
|------|------|
| CPU | 30% |
| 内存 | 326 MB |

**注意**：磁盘剩余 *较少*，`/data` 已用 90%。

- 选项一
- 选项二
"""


class TestToTelegram:
    def test_table_collapsed(self):
        out = to_telegram(_SAMPLE)
        assert "|" not in out
        assert "CPU  30%" in out or "CPU 30%" in out

    def test_bold_and_italic_converted(self):
        out = to_telegram(_SAMPLE)
        assert "*注意*" in out
        assert "_较少_" in out

    def test_heading_to_bold(self):
        out = to_telegram("## 系统状态")
        assert out == "*系统状态*"

    def test_code_fence_removed(self):
        out = to_telegram("```python\nprint(1)\n```")
        assert "```" not in out
        assert "print(1)" in out


class TestToSlack:
    def test_bold_mrkdwn(self):
        out = to_slack(_SAMPLE)
        assert "*注意*" in out
        assert "|" not in out


class TestToPlain:
    def test_strips_all_markdown(self):
        out = to_plain(_SAMPLE)
        assert "*" not in out.replace("*注意*", "")
        assert "#" not in out
        assert "`" not in out
        assert "CPU  30%" in out or "CPU 30%" in out


class TestFormatAndDialect:
    def test_dialect_for_channel(self):
        assert dialect_for_channel(SearchType.TG) == "telegram"
        assert dialect_for_channel(SearchType.SLACK) == "slack"
        assert dialect_for_channel(SearchType.WX) == "plain"
        assert dialect_for_channel(SearchType.WEB) == "plain"

    def test_unknown_dialect_plain(self):
        out = format_agent_message("**加粗**", "unknown")
        assert out == "加粗"

    def test_empty_text(self):
        assert format_agent_message("", "telegram") == ""
