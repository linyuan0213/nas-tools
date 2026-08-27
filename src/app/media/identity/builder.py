"""
身份索引构建器（ADR-014 P1）

从 TMDB/BGM 详情构建 Work 并灌入 AliasIndex。
首次访问构建（冷路径），之后命中索引（热路径零网络）。
"""

import log
from app.domain.mediatypes import MediaType
from app.media.external.bangumi import Bangumi
from app.media.identity.index import AliasIndex, get_alias_index
from app.media.identity.models import (
    ALIAS_ROMANIZATION,
    ALIAS_TRANSLATION,
    Alias,
    Work,
)
from app.media.lookup.tmdb_client import TmdbClient
from app.media.lookup.tmdb_detail import TmdbDetail
from app.utils import StringUtils


class IdentityIndexBuilder:
    def __init__(self, index: AliasIndex | None = None, tmdb_detail: TmdbDetail | None = None):
        self._index = index or get_alias_index()
        self._tmdb_detail = tmdb_detail
        self._bangumi = Bangumi()

    @property
    def tmdb_detail(self) -> TmdbDetail:
        if self._tmdb_detail is None:
            self._tmdb_detail = TmdbDetail(TmdbClient())
        return self._tmdb_detail

    # ---------- TMDB ----------

    def ensure_tmdb_work(self, tmdb_id: int, mtype: MediaType) -> Work | None:
        """确保 TMDB 作品已索引：命中直接返回，未命中拉详情构建"""
        cached = self._index.get_work("tmdb", tmdb_id)
        if cached:
            return cached
        try:
            info = self.tmdb_detail.get_detail(tmdb_id, mtype, append_to_response="alternative_titles,translations")
        except Exception as e:
            log.warn(f"[IdentityBuilder]TMDB详情拉取失败: {mtype.value}/{tmdb_id}, {e}")
            return None
        if not info:
            return None
        work = self._build_tmdb_work(tmdb_id, mtype, info)
        self._index.put_work(work)
        log.debug(f"[IdentityBuilder]TMDB作品已索引: {work.work_id} 别名 {len(work.aliases)} 条")
        return work

    @staticmethod
    def _build_tmdb_work(tmdb_id: int, mtype: MediaType, info: dict) -> Work:
        name = info.get("name") or info.get("title") or ""
        original = info.get("original_name") or info.get("original_title") or ""
        date = info.get("first_air_date") or info.get("release_date") or ""
        year = int(date[:4]) if date[:4].isdigit() else None
        is_ja = info.get("original_language") == "ja"

        aliases: list[Alias] = []
        for item in (info.get("alternative_titles") or {}).get("results") or []:
            title = item.get("title")
            if title:
                kind = ALIAS_ROMANIZATION if is_ja and not StringUtils.is_chinese(title) else ALIAS_TRANSLATION
                aliases.append(Alias(text=title, kind=kind, source="tmdb:alternative_titles"))
        for item in (info.get("translations") or {}).get("translations") or []:
            data = item.get("data") or {}
            title = data.get("name") or data.get("title")
            if title:
                lang = item.get("iso_639_1") or "unknown"
                kind = ALIAS_ROMANIZATION if is_ja and not StringUtils.is_chinese(title) else ALIAS_TRANSLATION
                aliases.append(Alias(text=title, lang=lang, kind=kind, source="tmdb:translations"))

        media_type = "anime" if mtype == MediaType.ANIME else mtype.value
        return Work(
            source="tmdb",
            work_id=tmdb_id,
            media_type=media_type,
            year=year,
            official_titles=[n for n in (name, original) if n],
            aliases=aliases,
        )

    # ---------- Bangumi ----------

    def ensure_bgm_work(self, bid: int) -> Work | None:
        cached = self._index.get_work("bgm", bid)
        if cached:
            return cached
        try:
            info = self._bangumi.detail(bid)
        except Exception as e:
            log.warn(f"[IdentityBuilder]BGM详情拉取失败: {bid}, {e}")
            return None
        if not info:
            return None
        name_cn = info.get("name_cn") or ""
        name = info.get("name") or ""
        date = str(info.get("date") or "")
        year = int(date[:4]) if date[:4].isdigit() else None
        aliases = []
        if name_cn:
            aliases.append(Alias(text=name_cn, lang="zh-Hans", kind=ALIAS_TRANSLATION, source="bgm"))
        if name and not StringUtils.is_chinese(name):
            aliases.append(Alias(text=name, kind=ALIAS_ROMANIZATION, source="bgm"))
        work = Work(
            source="bgm",
            work_id=bid,
            media_type="anime",
            year=year,
            official_titles=[n for n in (name_cn, name) if n],
            aliases=aliases,
        )
        self._index.put_work(work)
        log.debug(f"[IdentityBuilder]BGM作品已索引: {bid}")
        return work

    # ---------- 便捷方法 ----------

    def get_work_names(self, source: str, work_id: int, mtype: MediaType = MediaType.TV) -> list[str] | None:
        """兼容 get_all_names 语义：构建/命中后返回名称列表"""
        if source == "tmdb":
            work = self.ensure_tmdb_work(work_id, mtype)
        elif source == "bgm":
            work = self.ensure_bgm_work(work_id)
        else:
            return None
        return work.all_name_strings() if work else None


_builder: IdentityIndexBuilder | None = None


def get_identity_builder() -> IdentityIndexBuilder:
    global _builder
    if _builder is None:
        _builder = IdentityIndexBuilder()
    return _builder


def set_identity_builder(builder: IdentityIndexBuilder | None) -> None:
    """DI 装配入口：注入 builder 显式构建的实例；None 复位（测试隔离）。"""
    global _builder
    _builder = builder
