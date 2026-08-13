"""人机验证（Cloudflare / 雷池等）等待助手 — 供 Agent 浏览器工具与 autosignin 插件共用

nexus-chrome 导航后后台自动跑挑战，本助手负责轮询页面直到挑战页特征消失。
特征口径与 nexus-chrome 服务端（src/challenge/*）保持一致，仅匹配强特征，
避免普通页面正文文案（"正在"/"请稍候"/"challenge"/"由 Cloudflare 提供"页脚等）误判
导致长时间空轮询。
"""

import re
import time

# Cloudflare / 雷池强特征：仅页面级 DOM/URL/标题签名，正文出现这些词的普通页面极少
CHALLENGE_INDICATORS = re.compile(
    r"cf-chl|cf_chl|_cf_chl_opt|cf-browser|challenge-form|"
    r"Checking your browser|Just a moment|Ray ID|slg-bg|slg-box",
    re.IGNORECASE,
)

# 雷池（SafeLine）等 WAF：仅页面标题命中才算（与 nexus-chrome leichi.py 口径一致）
CHALLENGE_TITLES = ("雷池", "安全拦截", "访问验证")

CHALLENGE_WAIT_TIMEOUT = 60
CHALLENGE_POLL_INTERVAL = 2

_TITLE_RE = re.compile(r"<title[^>]*>(.*?)</title>", re.IGNORECASE | re.DOTALL)


def _is_challenge(html_text: str) -> bool:
    """判定页面是否仍处于挑战页（强特征 + 标题级特征）"""
    if not html_text:
        return False
    if CHALLENGE_INDICATORS.search(html_text):
        return True
    match = _TITLE_RE.search(html_text)
    title = match.group(1).strip() if match else ""
    return any(keyword in title for keyword in CHALLENGE_TITLES)


def wait_challenge_clear(session, initial_html: str = "", timeout: int = CHALLENGE_WAIT_TIMEOUT) -> str:
    """等待人机验证通过：挑战页特征消失即视为通过；返回最终页面 HTML"""
    html_text = initial_html
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if _is_challenge(html_text):
            time.sleep(CHALLENGE_POLL_INTERVAL)
            html_text = session.html()
            continue
        return html_text
    return html_text
