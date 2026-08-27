"""媒体身份解析 Builder — 显式装配 ADR-014 identity 组件。

在 build_app_context 时按拓扑顺序构建，并把构建好的实例注入各模块级
单例槽位（set_*()），使 get_*() 访问器解析到 DI 构建的实例（未装配时
仍回退惰性创建，保持测试/独立使用不受影响）。
"""

import log
from app.di.models import BusinessFacades, IdentityObjects
from app.media.external.bangumi import Bangumi
from app.media.identity.builder import IdentityIndexBuilder, set_identity_builder
from app.media.identity.graph import EditionGraph, set_edition_graph
from app.media.identity.index import AliasIndex, set_alias_index
from app.media.identity.matcher import TargetMatcher, set_target_matcher
from app.media.identity.remapper import EpisodeRemapper, set_episode_remapper
from app.media.identity.resolver import IdentityResolver, set_identity_resolver
from app.media.lookup.tmdb_detail import TmdbDetail
from app.media.parser.episode_mapper import EpisodeMapper


def build_identity(facades: BusinessFacades) -> IdentityObjects:
    """显式装配 identity 组件，共享注入 AliasIndex / TMDB 客户端 / Bangumi。"""
    alias_index = AliasIndex()
    bangumi = Bangumi()
    edition_graph = EditionGraph(index=alias_index, bangumi=bangumi)
    tmdb_detail = TmdbDetail(client=facades.tmdb_client)
    identity_builder = IdentityIndexBuilder(index=alias_index, tmdb_detail=tmdb_detail)
    episode_remapper = EpisodeRemapper(episode_mapper=EpisodeMapper(facades.media_service._lookup))
    target_matcher = TargetMatcher(graph=edition_graph, index=alias_index)
    identity_resolver = IdentityResolver(
        media_service=facades.media_service,
        index=alias_index,
        graph=edition_graph,
        builder=identity_builder,
    )

    # 注入模块级单例槽位：get_*() 访问器自此解析 DI 构建的实例
    set_alias_index(alias_index)
    set_edition_graph(edition_graph)
    set_identity_builder(identity_builder)
    set_episode_remapper(episode_remapper)
    set_target_matcher(target_matcher)
    set_identity_resolver(identity_resolver)

    log.info("[DI]媒体身份解析组件构建完成")
    return IdentityObjects(
        alias_index=alias_index,
        edition_graph=edition_graph,
        identity_resolver=identity_resolver,
        target_matcher=target_matcher,
        identity_builder=identity_builder,
        episode_remapper=episode_remapper,
    )
