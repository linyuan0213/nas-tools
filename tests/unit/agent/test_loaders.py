"""知识 Loader 单元测试（docs/消息模板/媒体库）"""

from unittest.mock import MagicMock

from app.agent.rag.loaders import MediaLibraryLoader, MessageTemplateLoader


class _FakeMediaLibraryService:
    def __init__(self, counts: dict, items: list[dict]):
        self._counts = counts
        self._items = items

    def get_media_count(self):
        return self._counts

    def get_latest(self, num=20):
        return self._items[:num]


class TestMediaLibraryLoader:
    def test_load_statistics_and_items(self):
        svc = _FakeMediaLibraryService(
            counts={"Movie": 120, "TV": 45, "Anime": 8},
            items=[
                {"id": "1", "name": "流浪地球", "type": "movie", "year": "2019"},
                {"id": "2", "name": "漫长的季节", "type": "tv"},
                {"id": "3", "type": "movie"},  # 无标题，跳过
            ],
        )
        loader = MediaLibraryLoader(svc, latest_num=100)
        sources = {src: text for src, text in loader.load()}
        assert "media_library/statistics" in sources
        assert "电影 120 部" in sources["media_library/statistics"]
        assert "media_library/item/流浪地球" in sources
        assert "年份：2019" in sources["media_library/item/流浪地球"]
        assert "media_library/item/漫长的季节" in sources
        assert "media_library/item/" not in [k for k in sources if "item/3" in k]

    def test_none_service_yields_nothing(self):
        loader = MediaLibraryLoader(None)
        assert list(loader.load()) == []

    def test_service_errors_graceful(self):
        svc = MagicMock()
        svc.get_media_count.side_effect = RuntimeError("媒体服务器未配置")
        svc.get_latest.side_effect = RuntimeError("媒体服务器未配置")
        loader = MediaLibraryLoader(svc)
        assert list(loader.load()) == []


class TestMessageTemplateLoader:
    def test_load_has_title_and_text(self):
        loader = MessageTemplateLoader()
        items = dict(loader.load())
        assert "message_template/download_start" in items
        assert "标题模板" in items["message_template/download_start"]
