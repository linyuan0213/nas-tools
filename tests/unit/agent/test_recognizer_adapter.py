"""MediaRecognizerParser 适配器单元测试"""

from app.agent.agents.media_recognizer import MediaRecognizer, MediaResult
from app.agent.agents.recognizer_adapter import MediaRecognizerParser
from app.domain.mediatypes import MediaType


class _FakeRecognizer(MediaRecognizer):
    def __init__(self, ready: bool = True, result: MediaResult | None = None):
        self._ready = ready
        self._result = result

    @property
    def ready(self) -> bool:
        return self._ready

    def recognize(self, filename: str):
        return self._result

    def recognize_batch(self, filenames: list[str], batch_size: int = 0):
        return [self._result for _ in filenames]


class TestMediaRecognizerParser:
    def test_is_llm_marker(self):
        parser = MediaRecognizerParser(_FakeRecognizer())
        assert parser.is_llm is True

    def test_ready_delegates(self):
        assert MediaRecognizerParser(_FakeRecognizer(ready=True)).ready
        assert not MediaRecognizerParser(_FakeRecognizer(ready=False)).ready

    def test_parse_converts(self):
        result = MediaResult(title_cn="流浪地球", title_en="The Wandering Earth", year=2019, type="movie")
        parser = MediaRecognizerParser(_FakeRecognizer(result=result))
        parsed = parser.parse("流浪地球.2019.1080p")
        assert parsed is not None
        assert parsed.title_cn == "流浪地球"
        assert parsed.year == "2019"
        assert parsed.type == MediaType.MOVIE

    def test_parse_none_result(self):
        parser = MediaRecognizerParser(_FakeRecognizer(result=None))
        assert parser.parse("xxx") is None

    def test_parse_batch(self):
        result = MediaResult(title_cn="剧集", type="tv", season=2)
        parser = MediaRecognizerParser(_FakeRecognizer(result=result))
        results = parser.parse_batch(["a", "b"])
        assert len(results) == 2
        assert all(r is not None and r.type == MediaType.TV and r.season == 2 for r in results)

    def test_type_mapping(self):
        assert MediaRecognizerParser._map_type("anime") == MediaType.ANIME
        assert MediaRecognizerParser._map_type("unknown") is None
        assert MediaRecognizerParser._map_type(None) is None
