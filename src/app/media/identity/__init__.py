"""媒体身份解析元数据层（ADR-014）"""

from app.media.identity.builder import IdentityIndexBuilder, get_identity_builder, set_identity_builder
from app.media.identity.graph import EditionGraph, get_edition_graph, set_edition_graph
from app.media.identity.index import AliasIndex, get_alias_index, set_alias_index
from app.media.identity.matcher import MatchResult, TargetMatcher, get_target_matcher, set_target_matcher
from app.media.identity.models import (
    ALIAS_FAN,
    ALIAS_OFFICIAL,
    ALIAS_ROMANIZATION,
    ALIAS_TRANSLATION,
    Alias,
    AliasEntry,
    EditionEdge,
    Franchise,
    Work,
    normalize_text,
)
from app.media.identity.remapper import EpisodeRemapper, get_episode_remapper, set_episode_remapper
from app.media.identity.resolver import (
    IdentityResolver,
    ResolveResult,
    extract_edition_markers,
    get_identity_resolver,
    set_identity_resolver,
)

__all__ = [
    "ALIAS_FAN",
    "ALIAS_OFFICIAL",
    "ALIAS_ROMANIZATION",
    "ALIAS_TRANSLATION",
    "Alias",
    "AliasEntry",
    "AliasIndex",
    "EditionEdge",
    "EditionGraph",
    "EpisodeRemapper",
    "Franchise",
    "IdentityIndexBuilder",
    "IdentityResolver",
    "MatchResult",
    "ResolveResult",
    "TargetMatcher",
    "Work",
    "extract_edition_markers",
    "get_alias_index",
    "get_edition_graph",
    "get_episode_remapper",
    "get_identity_builder",
    "get_identity_resolver",
    "get_target_matcher",
    "normalize_text",
    "set_alias_index",
    "set_edition_graph",
    "set_episode_remapper",
    "set_identity_builder",
    "set_identity_resolver",
    "set_target_matcher",
]
