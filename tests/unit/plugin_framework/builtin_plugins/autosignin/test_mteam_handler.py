"""M-Team 签到 handler 纯逻辑单测（URL/签名/响应判定，不依赖网络与 Redis）."""

import json
from typing import cast
from unittest.mock import MagicMock

from app.plugin_framework.builtin_plugins.autosignin.backend.handlers.mteam import MTeam
from app.plugin_framework.context import PluginContext


class _FakeResponse:
    def __init__(self, text):
        self.text = text


def _handler():
    return MTeam(plugin_ctx=cast(PluginContext, MagicMock()))


def test_build_sign_vector_matches_real_request():
    # 用户抓包真实请求：timestamp/sgin 由内置密钥生成
    sig = MTeam._build_sign("POST", "/api/member/updateLastBrowse", 1788666941029, "HLkPcWmycL57mfJt")
    assert sig == "Fl4kdsfOTdR+zQmlZZQQS86GiYA="


def test_response_code_string_zero_is_success():
    res = _FakeResponse(json.dumps({"code": "0", "message": "SUCCESS"}))
    result = _handler()._check_response(res, "M-Team")
    assert result.ok is True


def test_response_code_number_zero_is_success():
    res = _FakeResponse(json.dumps({"code": 0, "message": "success"}))
    result = _handler()._check_response(res, "M-Team")
    assert result.ok is True


def test_response_code_one_is_failure():
    res = _FakeResponse(json.dumps({"code": "1", "message": "FAIL"}))
    result = _handler()._check_response(res, "M-Team")
    assert result.ok is False


def test_api_base_prefers_cc_domain():
    class Api:
        base_url = "https://api.m-team.cc"

    class SiteDef:
        domain = "kp.m-team.cc"
        api = Api()

    assert _handler()._resolve_api_base(SiteDef()) == "https://api.m-team.cc"
    assert _handler()._resolve_api_base(None) == "https://api.m-team.cc"


def test_response_401_auth_expired_returns_clear_message():
    """JWT 过期(401)：返回明确提示而非接口原文，且不触发自动重登路径"""
    handler = _handler()
    res = _FakeResponse('{"code":401,"message":"Full authentication is required to access this resource","data":null}')
    result = handler._check_response(res, "M-Team")
    assert result.ok is False
    assert "登录态已过期" in result.msg
