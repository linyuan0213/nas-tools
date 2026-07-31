from app.media.parser.base import BaseParser, ParserResult
from app.media.parser.unified import UnifiedParser


class RegexParser(BaseParser):
    """基于规则的本地解析器 — 使用 UnifiedParser 统一解析"""

    def __init__(self) -> None:
        self._parser = UnifiedParser()

    def parse(self, title: str, subtitle: str = "") -> ParserResult | None:
        return self._parser.parse(title, subtitle)
