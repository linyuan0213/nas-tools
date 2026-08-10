"""MediaRecognizer → BaseParser 适配器

agent 层实现 media 层定义的 BaseParser 端口（依赖倒置）：
media 层不再 import agent 层，由 Builder 注入本适配器。
"""

from app.agent.agents.media_recognizer import MediaRecognizer, MediaResult
from app.domain.mediatypes import MediaType
from app.media.parser.base import BaseParser, ParserResult


class MediaRecognizerParser(BaseParser):
    """基于 LLM 的解析器 — 包装 MediaRecognizer 并实现 BaseParser 端口"""

    is_llm: bool = True

    def __init__(self, recognizer: MediaRecognizer):
        self._recognizer = recognizer

    @property
    def ready(self) -> bool:
        return self._recognizer.ready

    def parse(self, title: str, subtitle: str = "") -> ParserResult | None:
        result = self._recognizer.recognize(title)
        if not result:
            return None
        return self._convert(result, title)

    def parse_batch(self, titles: list[str]) -> list[ParserResult | None]:
        results = self._recognizer.recognize_batch(titles)
        return [self._convert(r, t) for r, t in zip(results, titles, strict=False)]

    def _convert(self, result: MediaResult | None, org_title: str = "") -> ParserResult | None:
        if not result:
            return None
        return ParserResult(
            title_en=result.title_en,
            title_cn=result.title_cn,
            year=str(result.year) if result.year else None,
            season=result.season,
            end_season=result.end_season,
            episode=result.episode,
            end_episode=result.end_episode,
            resource_pix=result.resolution,
            video_encode=result.video_codec,
            audio_encode=result.audio_codec,
            resource_team=result.release_group,
            type=self._map_type(result.type),
            confidence=0.9,
            org_string=org_title or None,
        )

    @staticmethod
    def _map_type(type_str: str | None) -> MediaType | None:
        if type_str == "anime":
            return MediaType.ANIME
        if type_str == "tv":
            return MediaType.TV
        if type_str == "movie":
            return MediaType.MOVIE
        return None
