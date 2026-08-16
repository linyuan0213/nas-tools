"""GitHub Release 通知 → Telegram HTML 转换（changelog 是 GitHub markdown，Telegram HTML 不解析 markdown）.

供 .github/workflows/build.yml 的 "Prepare Telegram notification" 步骤调用：
  python3 scripts/release_notify.py < input.md > output.html

转换规则：
  ## / ### 标题      → <b>标题</b>
  - 列表             → •
  **加粗**           → <b>加粗</b>
  *斜体*             → <i>斜体</i>
  `代码`             → <code>代码</code>
  [文字](链接)        → <a href="链接">文字</a>
  原始 & < > 先转义（quote=True 含 " ' → &quot; &apos;），插入的标签不受影响
"""

from __future__ import annotations

import html
import re
import sys


def markdown_to_telegram_html(content: str) -> str:
    """GitHub markdown → Telegram 兼容 HTML（Telegram 不解析 markdown）."""
    content = html.escape(content)  # 先转义原始 & < > " '，后插入的标签不受影响
    # 双反引号（嵌套代码标记）先归一为单反引号，避免后续错位
    content = re.sub(r"``([^`]+)``", r"\1", content)
    lines = content.split("\n")
    out: list[str] = []
    for line in lines:
        line = line.rstrip()
        # 标题（## / ###）→ 粗体
        m = re.match(r"^(#{1,3})\s+(.*)$", line)
        if m:
            out.append(f"<b>{m.group(2)}</b>")
            continue
        # 列表项
        if re.match(r"^\s*[-*]\s+", line):
            line = re.sub(r"^\s*[-*]\s+", "• ", line)
        # 行内 **加粗**
        line = re.sub(r"\*\*(.+?)\*\*", r"<b>\1</b>", line)
        # 行内 *斜体*（不误伤已转的 **）
        line = re.sub(r"(?<!\*)\*([^*]+)\*(?!\*)", r"<i>\1</i>", line)
        # 行内 `代码` → <code>
        line = re.sub(r"`([^`]+)`", r"<code>\1</code>", line)
        # [文字](链接)
        line = re.sub(r"\[([^\]]+)\]\(([^)\s]+)\)", r'<a href="\2">\1</a>', line)
        # 防御：把残留的孤立反引号转义，避免 Telegram 解析异常
        line = line.replace("`", "&#96;")
        # 防御：任何非合法标签的残留 < > 转义（防止错位产生未闭合标签）
        line = _escape_stray_angle_brackets(line)
        out.append(line)
    return "\n".join(out)


_TELEGRAM_TAGS = (
    "</",
    "<b>",
    "</b>",
    "<i>",
    "</i>",
    "<code>",
    "</code>",
    "<a ",
    "</a>",
    "<strong>",
    "</strong>",
    "<em>",
    "</em>",
    "<u>",
    "</u>",
    "<s>",
    "</s>",
)


def _escape_stray_angle_brackets(line: str) -> str:
    """把不是合法 Telegram HTML 标签的残留 < > 转义（防未闭合标签导致 400）."""
    result = []
    i = 0
    while i < len(line):
        if line[i] != "<":
            result.append(line[i])
            i += 1
            continue
        tail = line[i : i + 20].lower()
        if any(tail.startswith(tag) for tag in _TELEGRAM_TAGS):
            result.append(line[i])
            i += 1
            continue
        # 残留的 <（非合法标签）转义
        result.append("&lt;")
        i += 1
    return "".join(result)


def main() -> None:
    content = sys.stdin.read()
    sys.stdout.write(markdown_to_telegram_html(content))


if __name__ == "__main__":
    main()
