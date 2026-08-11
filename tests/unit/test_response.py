"""WebResponse 单元测试."""

from app.utils.response import WebResponse, fail, success


class TestWebResponse:
    def test_success_with_data(self):
        result = WebResponse.success(data={"id": 1})
        assert result["code"] == 0
        assert result["data"] == {"id": 1}

    def test_success_without_data(self):
        result = WebResponse.success()
        assert result["code"] == 0
        assert "data" not in result

    def test_success_with_extra_kwargs(self):
        result = WebResponse.success(msg="ok", total=10)
        assert result["code"] == 0
        assert result["msg"] == "ok"
        assert result["total"] == 10

    def test_fail_default(self):
        result = WebResponse.fail()
        assert result["code"] == 10004  # ErrorCode.OPERATION_FAILED
        assert result["message"] == "操作失败"

    def test_fail_with_code_and_msg(self):
        result = WebResponse.fail(code=404, msg="not found")
        assert result["code"] == 404
        assert result["message"] == "not found"

    def test_fail_with_extra_kwargs(self):
        result = WebResponse.fail(code=500, msg="error", detail="trace")
        assert result["detail"] == "trace"

    def test_top_level_success(self):
        assert success(data="x") == {"code": 0, "data": "x", "message": ""}

    def test_top_level_fail(self):
        assert fail(code=2, msg="bad") == {"code": 2, "message": "bad"}
