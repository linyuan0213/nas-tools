"""identity DI builder 装配测试（ADR-015 显式工厂注册表）"""

from unittest.mock import MagicMock

from app.di.builders.identity_builder import build_identity
from app.di.models import BusinessFacades
from app.media.identity import (
    get_alias_index,
    get_edition_graph,
    get_episode_remapper,
    get_identity_builder,
    get_identity_resolver,
    get_target_matcher,
    set_alias_index,
    set_edition_graph,
    set_episode_remapper,
    set_identity_builder,
    set_identity_resolver,
    set_target_matcher,
)


def _reset_slots() -> None:
    """复位模块级单例槽位，避免用例间相互污染。"""
    set_alias_index(None)
    set_edition_graph(None)
    set_identity_builder(None)
    set_episode_remapper(None)
    set_target_matcher(None)
    set_identity_resolver(None)


def _facades() -> BusinessFacades:
    media_service = MagicMock()
    media_service._lookup = MagicMock()
    return BusinessFacades(
        media_service=media_service,
        media_server=MagicMock(),
        tmdb_client=MagicMock(),
        agent_service=MagicMock(),
        media_recognizer=MagicMock(),
        search_intent_agent=MagicMock(),
        download_monitor=MagicMock(),
    )


class TestBuildIdentity:
    def test_wires_shared_dependencies(self):
        _reset_slots()
        facades = _facades()
        try:
            objs = build_identity(facades)

            # 共享依赖：resolver/builder/graph/matcher 关联同一 AliasIndex / EditionGraph
            assert objs.identity_resolver.index is objs.alias_index
            assert objs.identity_resolver.graph is objs.edition_graph
            assert objs.identity_resolver.builder is objs.identity_builder
            assert objs.identity_resolver.media is facades.media_service
            assert objs.identity_builder._index is objs.alias_index
            assert objs.identity_builder._tmdb_detail is not None
            assert objs.identity_builder._tmdb_detail.client is facades.tmdb_client
            assert objs.edition_graph._index is objs.alias_index
            assert objs.target_matcher._graph is objs.edition_graph
            assert objs.target_matcher._index is objs.alias_index
            assert objs.episode_remapper._mapper is not None
            assert objs.episode_remapper._mapper._tmdb is facades.media_service._lookup
        finally:
            _reset_slots()

    def test_getters_delegate_to_injected_instances(self):
        _reset_slots()
        facades = _facades()
        try:
            objs = build_identity(facades)

            assert get_alias_index() is objs.alias_index
            assert get_edition_graph() is objs.edition_graph
            assert get_identity_builder() is objs.identity_builder
            assert get_episode_remapper() is objs.episode_remapper
            assert get_target_matcher() is objs.target_matcher
            assert get_identity_resolver() is objs.identity_resolver
        finally:
            _reset_slots()

    def test_getters_fallback_without_di(self):
        """未装配 DI 时 get_*() 仍可惰性创建（测试/独立使用不受影响）"""
        _reset_slots()
        try:
            assert get_alias_index() is not None
            assert get_edition_graph() is not None
            assert get_identity_builder() is not None
            assert get_target_matcher() is not None
            assert get_episode_remapper() is not None
        finally:
            _reset_slots()
