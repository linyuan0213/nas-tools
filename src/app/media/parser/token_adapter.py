from app.media.parser.base import BaseParser, ParserResult
from app.media.parser.unified import UnifiedParser


class TokenAdapter(BaseParser):
    """Tokens 正则解析适配器 — 影视文件名解析

    .. deprecated:: 已弃用，内部已改用 UnifiedParser
    """

    def __init__(self) -> None:
        self._parser = UnifiedParser()

    def parse(self, title: str, subtitle: str = "") -> ParserResult | None:
        result = self._parser.parse(title, subtitle)
        if result:
            result.confidence = 0.65
        return result
