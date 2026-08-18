"""识别词管理 agent 工具测试"""

from typing import cast

from app.agent.tools.context import ToolContext
from app.agent.tools.handlers.words import words_add, words_delete, words_list, words_toggle


class _WordsService:
    def __init__(self, groups=None):
        self.groups = groups or []
        self.added = []
        self.toggled = []
        self.deleted = []

    def get_all_word_groups(self):
        return self.groups

    def add_or_edit_word(self, **kwargs):
        self.added.append(kwargs)

    def toggle_words(self, ids_info, flag):
        self.toggled.append((ids_info, flag))

    def delete_words_by_ids(self, ids_info):
        self.deleted.append(ids_info)

    def delete_word_group(self, gid):
        self.deleted.append(gid)

    def add_word_group(self, tmdb_id, tmdb_type):
        self.added.append({"tmdb_id": tmdb_id, "tmdb_type": tmdb_type})


def _ctx(words=None):
    return cast(
        ToolContext,
        ToolContext(
            search_orchestrator=None,
            searcher=None,
            download_service=None,
            downloader_core=None,
            subscribe_service=None,
            media_service=None,
            media_info_service=None,
            filetransfer_service=None,
            scheduler_service=None,
            system_info_service=None,
            event_bus=None,
            words_service=words,
        ),
    )


def _data(result) -> dict:
    assert isinstance(result.data, dict)
    return result.data


class TestWordsList:
    def test_words_list(self):
        svc = _WordsService([{"id": "-1", "name": "通用", "words": [{"id": 1, "replaced": "EZTV", "type": "1"}]}])
        result = words_list(_ctx(words=svc))
        assert result.success
        assert _data(result)["total"] == 1
        assert _data(result)["items"][0]["name"] == "通用"


class TestWordsAdd:
    def test_requires_confirm(self):
        result = words_add(_ctx(words=_WordsService()), word_type=2, replaced="剧场版")
        assert result.need_confirm

    def test_add_word(self):
        svc = _WordsService()
        result = words_add(_ctx(words=svc), word_type=2, replaced="剧场版", replace="", confirmed=True)
        assert result.success
        assert svc.added[-1]["replaced"] == "剧场版"
        assert svc.added[-1]["wtype"] == "2"

    def test_invalid_type(self):
        result = words_add(_ctx(words=_WordsService()), word_type=9, replaced="x", confirmed=True)
        assert not result.success
        assert "类型" in result.error

    def test_empty_replaced(self):
        result = words_add(_ctx(words=_WordsService()), word_type=1, replaced="  ", confirmed=True)
        assert not result.success


class TestWordsToggle:
    def test_requires_confirm(self):
        result = words_toggle(_ctx(words=_WordsService()), word_ids=[1, 2], enabled=False)
        assert result.need_confirm

    def test_toggle(self):
        svc = _WordsService()
        result = words_toggle(_ctx(words=svc), word_ids=[1], enabled=False, confirmed=True)
        assert result.success
        assert svc.toggled == [(["1"], "off")]


class TestWordsDelete:
    def test_requires_confirm(self):
        result = words_delete(_ctx(words=_WordsService()), word_ids=[1])
        assert result.need_confirm

    def test_delete_words(self):
        svc = _WordsService()
        result = words_delete(_ctx(words=svc), word_ids=[1, 2], confirmed=True)
        assert result.success
        assert svc.deleted == [["1", "2"]]

    def test_delete_group(self):
        svc = _WordsService()
        result = words_delete(_ctx(words=svc), group_id=5, confirmed=True)
        assert result.success
        assert svc.deleted == [5]

    def test_no_target(self):
        result = words_delete(_ctx(words=_WordsService()), confirmed=True)
        assert not result.success
