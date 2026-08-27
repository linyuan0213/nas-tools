"""MediaService.identify_batch 键一致性回归测试。

去重键（步骤2）与组装键（步骤4）必须使用同一 _norm_name 归一化，
否则英文标题（大小写/分隔符变化）lookup 结果无法映射回条目。
"""

from unittest.mock import MagicMock

from app.domain.mediatypes import MediaType
from app.media.lookup.base import LookupResult
from app.media.parser.base import ParserResult
from app.media.parser.regex import RegexParser
from app.media.service import MediaService


def _noop_apply_words(title: str, subtitle: str) -> tuple[str, str]:
    return title, subtitle


def _noop_post_process(parsed, title: str, subtitle: str) -> ParserResult | None:
    return parsed


def _service(lookup_result, parser=None):
    svc = MediaService.__new__(MediaService)
    svc._llm_parser = MagicMock(ready=False)
    svc._parser = parser or RegexParser()
    svc._lookup = MagicMock()
    svc._lookup.lookup.return_value = lookup_result
    svc._apply_words = _noop_apply_words  # type: ignore[assignment]
    svc._post_process = _noop_post_process  # type: ignore[assignment]
    svc._episode_mapping_enabled = False
    return svc


class TestIdentifyBatchKeyConsistency:
    def test_english_title_maps_back(self):
        """英文标题：去重/组装键归一化一致 → lookup 结果正确映射（回归 _norm_name bug）"""
        svc = _service(LookupResult(tmdb_id=872585, title="奥本海默", media_type=MediaType.MOVIE))

        results = svc.identify_batch([{"title": "Oppenheimer 2023 2160p UHD BluRay"}])

        info = results[0]
        assert info.tmdb_id == 872585
        assert info.title == "奥本海默"

    def test_dotted_english_title_maps_back(self):
        """点号分隔英文标题：归一化后 key 一致 → 正常映射"""
        svc = _service(LookupResult(tmdb_id=693134, title="沙丘2", media_type=MediaType.MOVIE))

        results = svc.identify_batch([{"title": "Dune.Part.Two.2024.1080p.BluRay"}])

        assert results[0].tmdb_id == 693134

    def test_chinese_title_maps_back(self):
        """中文标题回归：大小写无关归一化不影响中文名映射"""
        svc = _service(LookupResult(tmdb_id=842675, title="流浪地球2", media_type=MediaType.MOVIE))

        results = svc.identify_batch([{"title": "流浪地球2 2023 4K HDR"}])

        assert results[0].tmdb_id == 842675

    def test_missing_lookup_keeps_zero(self):
        """lookup 未命中 → tmdb_id 保持 0（组装不产生误配）"""
        svc = _service(None)

        results = svc.identify_batch([{"title": "完全不存在的作品标题 XYZ 1080p"}])

        assert results[0].tmdb_id == 0
