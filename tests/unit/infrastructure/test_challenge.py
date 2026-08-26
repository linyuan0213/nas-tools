"""人机验证挑战特征判定测试（app.infrastructure.chrome.challenge）."""

from app.infrastructure.chrome.challenge import (
    _is_challenge,
    has_pending_turnstile,
)

# Cloudflare 整页拦截（interstitial）页面特征
CF_INTERSTITIAL_HTML = """
<html><head><title>Just a moment...</title></head>
<body><form id="challenge-form" action="/?__cf_chl_f_tk=abc" method="POST">
<script>window._cf_chl_opt={cvId:'2'};</script>
<div class="cf-browser-verification cf-im-under-attack"></div>
<span>Ray ID: 123abc</span></form></body></html>
"""

# 观众签到页：正常页面内嵌 Turnstile 组件（cf-chl-widget-* 为组件生成的元素 id）
AUDIENCES_ATTENDANCE_HTML = """
<!DOCTYPE html PUBLIC "-//W3C//DTD XHTML 1.0 Transitional//EN"
 "http://www.w3.org/TR/xhtml1/DTD/xhtml1-transitional.dtd">
<html xmlns="http://www.w3.org/1999/xhtml"><head><title>Audiences :: 签到 - Powered by NexusPHP</title>
<script src="https://challenges.cloudflare.com/turnstile/v0/api.js" defer></script></head>
<body><p>验证通过后将自动完成签到</p>
<form method="post"><input type="hidden" name="cf-token" id="cf-token" value="">
<div class="cf-turnstile" data-sitekey="0x4AAAAAABfcR5" data-callback="cfCallback">
<div><input type="hidden" name="cf-turnstile-response" id="cf-chl-widget-kot05_response"></div>
</div></form></body></html>
"""


class TestChallengeDetection:
    def test_interstitial_page_is_challenge(self):
        assert _is_challenge(CF_INTERSTITIAL_HTML)

    def test_embedded_turnstile_page_is_not_challenge(self):
        """内嵌 Turnstile 的正常页面不得误判为挑战页（观众签到误报回归）"""
        assert not _is_challenge(AUDIENCES_ATTENDANCE_HTML)

    def test_normal_page_is_not_challenge(self):
        assert not _is_challenge("<html><head><title>首页</title></head><body>正常内容</body></html>")

    def test_safeline_title_is_challenge(self):
        assert _is_challenge("<html><head><title>雷池 - 安全拦截</title></head><body></body></html>")

    def test_empty_html_is_not_challenge(self):
        assert not _is_challenge("")


class TestPendingTurnstile:
    def test_embedded_turnstile_detected(self):
        assert has_pending_turnstile(AUDIENCES_ATTENDANCE_HTML)

    def test_no_turnstile(self):
        assert not has_pending_turnstile("<html><body>普通页面</body></html>")

    def test_empty_html(self):
        assert not has_pending_turnstile("")
