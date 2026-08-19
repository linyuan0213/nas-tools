"""ApiSiteSearcher 请求体处理测试"""

from unittest.mock import MagicMock, patch

from app.sites.api_searcher import ApiSiteSearcher


class TestStripEmptyLists:
    """空数组参数（categories: []）发送前剔除——避免部分 API 对显式空数组返回 500"""

    def _searcher(self) -> ApiSiteSearcher:
        site = MagicMock()
        site.domain = "x.example.com"
        site.api.base_url = "https://x.example.com"
        site.api.auth = {"type": "api_key", "header_name": "x-api-key", "user_agent": ""}
        site.api.endpoints = {"search": {"method": "POST", "path": "/search", "body": {}}}
        site.name = "TestAPI"
        engine = MagicMock()
        engine._build_headers.return_value = {"x-api-key": "k"}
        return ApiSiteSearcher(site, engine, {"api_key": "k"})

    def test_empty_categories_omitted(self):
        s = self._searcher()
        with patch("app.sites.api_searcher.HttpClient") as client_cls:
            client_cls.return_value.post.return_value.is_success = True
            client_cls.return_value.post.return_value.json.return_value = {"data": []}
            s._execute_request(
                {"method": "POST", "path": "/search", "content_type": "application/json"},
                {"keyword": "", "categories": [], "visible": 1},
                {"keyword": "", "page": "0"},
            )
        kwargs = client_cls.return_value.post.call_args.kwargs
        body = kwargs["data"]
        assert "categories" not in body
        assert "keyword" in body

    def test_nonempty_categories_kept(self):
        s = self._searcher()
        with patch("app.sites.api_searcher.HttpClient") as client_cls:
            client_cls.return_value.post.return_value.is_success = True
            client_cls.return_value.post.return_value.json.return_value = {"data": []}
            s._execute_request(
                {"method": "POST", "path": "/search", "content_type": "application/json"},
                {"keyword": "Lost", "categories": [401], "visible": 1},
                {"keyword": "Lost", "page": "0"},
            )
        kwargs = client_cls.return_value.post.call_args.kwargs
        body = kwargs["data"]
        assert '"categories":[401]' in body
