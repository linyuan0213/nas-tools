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
        out.append(line)
    return "\n".join(out)


def main() -> None:
    content = sys.stdin.read()
    sys.stdout.write(markdown_to_telegram_html(content))


if __name__ == "__main__":
    main()
