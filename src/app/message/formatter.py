"""Agent 回答的渠道感知 Markdown 转换

ChatAgent 产出通用 GFM Markdown，但第三方消息工具的 Markdown 方言各不相同：
- Telegram：legacy Markdown（*粗体*、_斜体_、`代码`、[链接](url)），不支持表格 / ## / **
- Slack：mrkdwn（*粗体*），不支持表格
- 微信 / 企业微信 / Bark 等：基本纯文本

此处统一做 GFM → 渠道方言转换；未覆盖渠道一律降级为纯文本（保留内容，去掉语法）。
"""

import re

_FENCE_RE = re.compile(r"```")


def _strip_fences(text: str) -> str:
    """移除代码围栏标记（```），保留代码内容"""
    return _FENCE_RE.sub("", text)


def _table_to_lines(text: str) -> str:
    """把 GFM 表格块转换为 '键：值' 行（Telegram/Slack 均不支持表格）"""
    lines = text.splitlines()
    out: list[str] = []
    in_table = False
    for line in lines:
        if line.strip().startswith("|") and line.strip().endswith("|"):
            cells = [c.strip() for c in line.strip().strip("|").split("|")]
            # 分隔行（|---|）跳过
            if all(re.fullmatch(r":?-{2,}:?", c) for c in cells if c):
                in_table = True
                continue
            if in_table:
                out.append("  ".join(cells))
            continue
        in_table = False
        out.append(line)
    return "\n".join(out)


def to_telegram(text: str) -> str:
    """GFM → Telegram legacy Markdown"""
    text = _table_to_lines(text)
    text = _strip_fences(text)
    # 顺序敏感：先斜体（单星号，受 ** 保护）→ 再粗体 → 最后标题转粗体
    text = re.sub(r"(?<!\*)\*([^*\n]+)\*(?!\*)", r"_\1_", text)
    text = re.sub(r"\*\*(.+?)\*\*", r"*\1*", text)
    text = re.sub(r"^#{1,6}\s+(.+)$", lambda m: f"*{m.group(1).strip()}*", text, flags=re.M)
    return text.strip()


def to_slack(text: str) -> str:
    """GFM → Slack mrkdwn"""
    text = _table_to_lines(text)
    text = _strip_fences(text)
    text = re.sub(r"^#{1,6}\s+(.+)$", r"*\1*", text, flags=re.M)
    text = re.sub(r"\*\*(.+?)\*\*", r"*\1*", text)
    return text.strip()


def to_plain(text: str) -> str:
    """GFM → 纯文本（微信/Bark 等无 Markdown 渠道）"""
    text = _table_to_lines(text)
    text = _strip_fences(text)
    text = re.sub(r"^#{1,6}\s+", "", text, flags=re.M)
    text = re.sub(r"\*\*(.+?)\*\*", r"\1", text)
    text = re.sub(r"(?<!\*)\*([^*\n]+)\*(?!\*)", r"\1", text)
    text = re.sub(r"`([^`\n]+)`", r"\1", text)
    return text.strip()


def dialect_for_channel(channel) -> str:
    """渠道类型 → 方言（未知渠道回退纯文本）"""
    cname = getattr(channel, "value", str(channel)).lower()
    if "telegram" in cname:
        return "telegram"
    if "slack" in cname:
        return "slack"
    return "plain"


def format_agent_message(text: str, dialect: str = "plain") -> str:
    """按渠道方言格式化 Agent 回答；未知方言回退纯文本"""
    if not text:
        return text
    if dialect == "telegram":
        return to_telegram(text)
    if dialect == "slack":
        return to_slack(text)
    return to_plain(text)
