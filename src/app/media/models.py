from typing import Any

import cn2an
import regex as re
from pydantic import BaseModel, Field

import log
from app.core.constants import ANIME_GENREIDS
from app.db.repositories.category_repo_adapter import CategoryConfigRepositoryAdapter
from app.domain.mediatypes import MediaType
from app.infrastructure.image_proxy import ImageProxy
from app.media.category_matcher import get_category
from app.media.image_resolver import MediaImageResolver
from app.utils import StringUtils


class MediaInfo(BaseModel):
    """统一的媒体信息模型 — 替代 MetaBase + MediaInfoModel"""

    model_config = {"extra": "allow"}

    # ---- 识别相关 ----
    fileflag: bool = False
    org_string: str | None = None
    rev_string: str | None = None
    subtitle: str | None = None
    type: MediaType | None = None

    # ---- 名称 ----
    cn_name: str | None = None
    en_name: str | None = None
    _name: str | None = None

    # ---- 解析器内部属性 ----
    _source: str = ""
    _effect: list = []
    _stop_name_flag: bool = False
    _stop_cnname_flag: bool = False
    _last_token: str = ""
    _last_token_type: str = ""
    _continue_flag: bool = True
    _unknown_name_str: str = ""

    # ---- 季/集 ----
    total_seasons: int = 0
    begin_season: int | None = None
    end_season: int | None = None
    total_episodes: int = 0
    begin_episode: int | None = None
    end_episode: int | None = None
    part: str | None = None
    # 种子原始季/集（remap 后保留重映射前的值）
    seeds_season: int | None = None
    seeds_episode: int | None = None
    seeds_end_episode: int | None = None

    # ---- 资源信息 ----
    resource_type: str | None = None
    resource_effect: str | None = None
    resource_pix: str | None = None
    resource_team: str | None = None
    customization: str | None = None
    video_encode: str | None = None
    audio_encode: str | None = None

    # ---- 分类 ----
    category: str = ""

    # ---- TMDB/IMDB/豆瓣 ID ----
    tmdb_id: int | str = 0
    imdb_id: str = ""
    tvdb_id: int = 0
    douban_id: int | str = 0

    # ---- 媒体信息 ----
    keyword: str | None = None
    title: str | None = None
    original_language: str | None = None
    original_title: str | None = None
    release_date: str | None = None
    networks: list[str] | None = None
    runtime: int = 0
    year: str | None = None

    # ---- 图片 ----
    backdrop_path: str | None = None
    poster_path: str | None = None
    fanart_backdrop: str | None = None
    fanart_poster: str | None = None

    # ---- 评分/概述 ----
    vote_average: float = 0.0
    overview: str | None = None

    # ---- TMDB 完整信息 ----
    tmdb_info: dict[str, Any] = Field(default_factory=dict)

    # ---- 本地状态 ----
    fav: str = "0"
    rss_sites: list[str] = Field(default_factory=list)
    search_sites: list[str] = Field(default_factory=list)

    # ---- 种子附加信息 ----
    site: str | None = None
    site_order: int = 0
    user_name: str | None = None
    enclosure: str | None = None
    res_order: int = 0
    filter_rule: str | None = None
    over_edition: bool | None = None
    size: int = 0
    seeders: int = 0
    peers: int = 0
    page_url: str | None = None
    upload_volume_factor: float | None = None
    download_volume_factor: float | None = None
    hit_and_run: bool | None = None
    rssid: int | None = None
    save_path: str | None = None
    download_setting: Any | None = None
    ignored_words: list[str] | None = None
    replaced_words: list[str] | None = None
    offset_words: list[str] | None = None
    labels: Any | None = None
    description: str | None = None
    note: dict[str, Any] = Field(default_factory=dict)

    # ---- 便捷方法 ----
    def get_name(self) -> str:
        if self.cn_name and StringUtils.is_all_chinese(self.cn_name):
            return self.cn_name
        elif self.en_name:
            return self.en_name
        elif self.cn_name:
            return self.cn_name
        return ""

    def get_title_string(self) -> str:
        if self.title:
            return f"{self.title} ({self.year})" if self.year else self.title
        elif self.get_name():
            return f"{self.get_name()} ({self.year})" if self.year else self.get_name()
        return ""

    def get_season_string(self) -> str:
        if self.begin_season is not None:
            b = self.begin_season
            e = self.end_season
            if e is None or (isinstance(b, int) and isinstance(e, int) and e == b):
                return "S{}".format(str(b).rjust(2, "0"))
            return "S{}-S{}".format(str(b).rjust(2, "0"), str(e).rjust(2, "0"))
        if self.type == MediaType.MOVIE:
            return ""
        return "S01"

    def get_season_item(self) -> str:
        if self.begin_season is not None:
            return "S{}".format(str(self.begin_season).rjust(2, "0"))
        if self.type == MediaType.MOVIE:
            return ""
        return "S01"

    def get_season_seq(self) -> str:
        if self.begin_season is not None:
            return str(self.begin_season)
        if self.type == MediaType.MOVIE:
            return ""
        return "1"

    def get_season_list(self) -> list:
        if self.begin_season is None:
            if self.type == MediaType.MOVIE:
                return []
            return [1]
        if self.end_season is not None:
            return list(range(self.begin_season, self.end_season + 1))
        return [self.begin_season]

    def set_season(self, sea):
        if not sea:
            return
        if isinstance(sea, list):
            if len(sea) == 1 and str(sea[0]).isdigit():
                self.begin_season = int(sea[0])
                self.end_season = None
            elif len(sea) > 1 and str(sea[0]).isdigit() and str(sea[-1]).isdigit():
                self.begin_season = int(sea[0])
                self.end_season = int(sea[-1])
        elif str(sea).isdigit():
            self.begin_season = int(sea)
            self.end_season = None

    def set_episode(self, ep):
        if not ep:
            return
        if isinstance(ep, list):
            if len(ep) == 1 and str(ep[0]).isdigit():
                self.begin_episode = int(ep[0])
                self.end_episode = None
            elif len(ep) > 1 and str(ep[0]).isdigit() and str(ep[-1]).isdigit():
                self.begin_episode = int(ep[0])
                self.end_episode = int(ep[-1])
        elif str(ep).isdigit():
            self.begin_episode = int(ep)
            self.end_episode = None

    def get_episode_string(self) -> str:
        if self.begin_episode is not None:
            b = self.begin_episode
            e = self.end_episode
            if e is None or (isinstance(b, int) and isinstance(e, int) and e == b):
                return "E{}".format(str(b).rjust(2, "0"))
            return "E{}-E{}".format(str(b).rjust(2, "0"), str(e).rjust(2, "0"))
        return ""

    def get_episode_items(self) -> str:
        """返回集的并列表达方式，用于支持单文件多集"""
        return "E{}".format("E".join(str(episode).rjust(2, "0") for episode in self.get_episode_list()))

    def get_episode_list(self) -> list:
        if self.begin_episode is None:
            return []
        if self.end_episode is not None:
            return list(range(self.begin_episode, self.end_episode + 1))
        return [self.begin_episode]

    def get_episode_seqs(self) -> str:
        episodes = self.get_episode_list()
        if not episodes:
            return ""
        if len(episodes) == 1:
            return str(episodes[0])
        return f"{episodes[0]}-{episodes[-1]}"

    def get_episode_seq(self) -> str:
        """兼容旧接口 — 同 get_episode_seqs"""
        return self.get_episode_seqs()

    def get_season_episode_string(self) -> str:
        if self.type == MediaType.MOVIE:
            return ""
        season = self.get_season_string()
        episode = self.get_episode_string()
        if season and episode:
            return f"{season} {episode}"
        elif season:
            return season
        elif episode:
            return episode
        return ""

    def get_resource_type_string(self) -> str:
        parts = []
        if self.resource_type:
            parts.append(self.resource_type)
        if self.resource_effect:
            parts.append(self.resource_effect)
        if self.resource_pix:
            parts.append(self.resource_pix)
        return " ".join(parts)

    def get_edtion_string(self) -> str:
        """返回资源类型字符串（不含分辨率）— 保持旧版拼写"""
        parts = []
        if self.resource_type:
            parts.append(self.resource_type)
        if self.resource_effect:
            parts.append(self.resource_effect)
        return " ".join(parts)

    def get_resource_team_string(self) -> str:
        return self.resource_team or ""

    def get_video_encode_string(self) -> str:
        return self.video_encode or ""

    def get_audio_encode_string(self) -> str:
        return self.audio_encode or ""

    def get_stars(self) -> str:
        if not self.vote_average:
            return ""
        score = round(float(self.vote_average))
        full = min(int(score), 10)
        return "★" * full + "☆" * (10 - full)

    def get_vote_string(self) -> str:
        if self.vote_average:
            return f"评分：{round(float(self.vote_average), 1)}"
        return ""

    def get_type_string(self) -> str:
        return f"类型：{self.type.value}" if self.type else ""

    def get_overview_string(self, max_len: int = 140) -> str:
        if not hasattr(self, "overview"):
            return ""
        overview = str(self.overview).strip()
        placeholder = " ..."
        max_len = max(len(placeholder), max_len - len(placeholder))
        return (overview[:max_len] + placeholder) if len(overview) > max_len else overview

    def get_star_string(self) -> str:
        if self.vote_average:
            return f"评分：{self.get_stars()} ({round(float(self.vote_average), 1)})"
        return ""

    def get_title_vote_string(self) -> str:
        if not self.vote_average:
            return self.get_title_string()
        return f"{self.get_title_string()}\n{self.get_star_string()}"

    def get_title_ep_string(self) -> str:
        string = self.get_title_string()
        if self.get_episode_list():
            return f"{string} {self.get_season_episode_string()}"
        if self.get_season_list():
            return f"{string} {self.get_season_string()}"
        return string

    @staticmethod
    def get_free_string(upload_volume_factor=None, download_volume_factor=None) -> str:
        uv = upload_volume_factor
        dv = download_volume_factor
        if uv is None or dv is None:
            return "未知"
        free_strs = {
            "1.0 1.0": "普通",
            "1.0 0.0": "免费",
            "2.0 1.0": "2X",
            "2.0 0.0": "2X免费",
            "1.0 0.5": "50%",
            "2.0 0.5": "2X 50%",
            "1.0 0.7": "70%",
            "1.0 0.3": "30%",
        }
        return free_strs.get(f"{uv:.1f} {dv:.1f}", "未知")

    def get_volume_factor_string(self) -> str:
        return self.get_free_string(self.upload_volume_factor, self.download_volume_factor)

    def is_in_season(self, season) -> bool:
        if self.end_season is not None:
            meta_season = list(range(self.begin_season or 1, self.end_season + 1))
        else:
            meta_season = [self.begin_season] if self.begin_season is not None else [1]
        if isinstance(season, list):
            return set(meta_season).issuperset(set(season))
        return (
            self.begin_season is not None
            and self.end_season is not None
            and self.begin_season <= int(season) <= self.end_season
            if self.end_season is not None
            else int(season) in meta_season
        )

    def is_in_episode(self, episode) -> bool:
        if self.end_episode is not None:
            meta_episode = list(range(self.begin_episode or 1, self.end_episode + 1))
        else:
            meta_episode = [self.begin_episode] if self.begin_episode is not None else []
        if isinstance(episode, list):
            return set(meta_episode).issuperset(set(episode))
        return (
            self.begin_episode is not None
            and self.end_episode is not None
            and self.begin_episode <= int(episode) <= self.end_episode
            if self.end_episode is not None
            else int(episode) in meta_episode
        )

    def set_torrent_info(
        self,
        site=None,
        site_order=0,
        enclosure=None,
        res_order=0,
        filter_rule=None,
        size=0,
        seeders=0,
        peers=0,
        description=None,
        page_url=None,
        upload_volume_factor=None,
        download_volume_factor=None,
        rssid=None,
        hit_and_run=None,
        imdbid=None,
        over_edition=None,
        labels=None,
    ):
        if site:
            self.site = site
        if site_order:
            self.site_order = site_order
        if enclosure:
            self.enclosure = enclosure
        if res_order:
            self.res_order = res_order
        if filter_rule:
            self.filter_rule = filter_rule
        if size:
            self.size = size
        if seeders:
            self.seeders = seeders
        if peers:
            self.peers = peers
        if description:
            self.description = description
        if page_url:
            self.page_url = page_url
        if upload_volume_factor is not None:
            self.upload_volume_factor = upload_volume_factor
        if download_volume_factor is not None:
            self.download_volume_factor = download_volume_factor
        if rssid:
            self.rssid = rssid
        if hit_and_run is not None:
            self.hit_and_run = hit_and_run
        if imdbid is not None:
            self.imdb_id = imdbid
        if over_edition is not None:
            self.over_edition = over_edition
        if labels is not None:
            self.labels = labels

    def set_download_info(self, download_setting=None, save_path=None):
        if download_setting:
            self.download_setting = download_setting
        if save_path:
            self.save_path = save_path

    def set_tmdb_info(self, info):
        if not info:
            return
        adapter = CategoryConfigRepositoryAdapter()
        entities = adapter.get_all()
        rule_map: dict[str, dict[str, dict[str, str]]] = {"movie": {}, "tv": {}, "anime": {}}
        for ent in entities:
            mt = ent.media_type
            if mt in rule_map:
                rule_map[mt][ent.name] = ent.rules if not ent.is_default else {}

        media_type = info.get("media_type")
        if media_type == MediaType.TV:
            genre_ids = info.get("genre_ids") or []
            # TMDB detail 返回 genres（数组）而非 genre_ids，需兼容提取
            if not genre_ids:
                genre_ids = [g.get("id") for g in (info.get("genres") or []) if g.get("id")]
            if isinstance(genre_ids, list):
                genre_ids = [str(val).upper() for val in genre_ids]
            else:
                genre_ids = [str(genre_ids).upper()]
            if set(genre_ids).intersection(set(ANIME_GENREIDS)):
                self.type = MediaType.ANIME
            else:
                self.type = MediaType.TV
        elif media_type:
            self.type = media_type
        else:
            return
        self.tmdb_id = info.get("id")
        if not self.tmdb_id:
            return
        if info.get("external_ids"):
            self.tvdb_id = info.get("external_ids", {}).get("tvdb_id", 0)
            self.imdb_id = info.get("external_ids", {}).get("imdb_id", "")
        self.tmdb_info = info
        self.vote_average = round(float(info.get("vote_average")), 1) if info.get("vote_average") else 0
        self.overview = info.get("overview")
        self.original_language = info.get("original_language")
        self.networks = [network.get("name") for network in info.get("networks") or []]
        if self.type == MediaType.MOVIE:
            tmdb_year = info.get("release_date", "")[:4] if info.get("release_date") else ""
            if self.year and tmdb_year and str(self.year) != str(tmdb_year):
                log.debug(f"[MediaInfo]TMDB年份不匹配: 种子={self.year}, TMDB={tmdb_year}, 保留种子元数据")
                tmdb_year = ""  # 年份冲突时不覆盖
        elif self.type != MediaType.MOVIE and self.year and info:
            tmdb_year = info.get("first_air_date", "")[:4] if info.get("first_air_date") else ""
            if tmdb_year.isdigit() and self.year.isdigit() and abs(int(self.year) - int(tmdb_year)) > 5:
                self.tmdb_id = None  # type: ignore[reportAttributeAccessIssue]
                self.tmdb_info = None  # type: ignore[reportAttributeAccessIssue]
                return

        if media_type == MediaType.MOVIE:
            self.title = info.get("title")
            self.original_title = info.get("original_title")
            self.runtime = info.get("runtime")
            self.release_date = info.get("release_date")
            title_val = info.get("title") or ""
            self.cn_name = title_val if StringUtils.is_chinese(title_val) else None
            en_val = info.get("original_title") or ""
            # en_name 仅存真正的英文/拉丁名；中日韩原名不存（交给上层取 TMDB 英文标题），避免日语名污染英文名
            self.en_name = None
            if not StringUtils.is_chinese(title_val) and not StringUtils.is_japanese(title_val):
                self.en_name = title_val
            elif not StringUtils.is_chinese(en_val) and not StringUtils.is_japanese(en_val):
                self.en_name = en_val
            # 兜底：name/original_name 均为中日文时（中文 locale 的 detail 接口），从 translations 提取英文名
            if not self.en_name:
                for tr in (info.get("translations") or {}).get("translations") or []:
                    if tr.get("iso_639_1") == "en" and tr.get("data", {}).get("name"):
                        self.en_name = tr["data"]["name"].strip()
                        break
            if self.release_date:
                self.year = self.release_date[0:4]
            self.category = get_category(rule_map.get("movie"), info)
            self.poster_path = ImageProxy.get_tmdbimage_url(info.get("poster_path")) if info.get("poster_path") else ""
            self.backdrop_path = (
                ImageProxy.get_tmdbimage_url(info.get("backdrop_path")) if info.get("backdrop_path") else ""
            )
        else:
            tmdb_year = info.get("first_air_date", "")[:4] if info.get("first_air_date") else ""
            if self.year and tmdb_year and str(self.year) != str(tmdb_year):
                log.debug(f"[MediaInfo]TMDB年份不匹配: 种子={self.year}, TMDB={tmdb_year}, 保留种子元数据")
                tmdb_year = ""  # 年份冲突时不覆盖
            self.title = info.get("name")
            self.original_title = info.get("original_name")
            runtime_val = info.get("episode_run_time")
            self.runtime = int(runtime_val[0]) if runtime_val else None  # type: ignore[assignment]
            self.release_date = info.get("first_air_date")
            name_val = info.get("name") or ""
            self.cn_name = name_val if StringUtils.is_chinese(name_val) else None
            en_val = info.get("original_name") or ""
            # en_name 仅存真正的英文/拉丁名；中日韩原名不存（交给上层取 TMDB 英文标题），避免日语名污染英文名
            self.en_name = None
            if not StringUtils.is_chinese(name_val) and not StringUtils.is_japanese(name_val):
                self.en_name = name_val
            elif not StringUtils.is_chinese(en_val) and not StringUtils.is_japanese(en_val):
                self.en_name = en_val
            # 兜底：name/original_name 均为中日文时（中文 locale 的 detail 接口），从 translations 提取英文名
            if not self.en_name:
                for tr in (info.get("translations") or {}).get("translations") or []:
                    if tr.get("iso_639_1") == "en" and tr.get("data", {}).get("name"):
                        self.en_name = tr["data"]["name"].strip()
                        break
            if self.release_date:
                self.year = self.release_date[0:4]
            if self.type == MediaType.MOVIE:
                self.category = get_category(rule_map.get("movie"), info)
            elif self.type == MediaType.TV:
                self.category = get_category(rule_map.get("tv"), info)
            else:
                self.category = get_category(rule_map.get("anime"), info)
            self.poster_path = (
                ImageProxy.get_tmdbimage_url(info.get("poster_path"), size="medium") if info.get("poster_path") else ""
            )
            self.backdrop_path = (
                ImageProxy.get_tmdbimage_url(info.get("backdrop_path"), size="large")
                if info.get("backdrop_path")
                else ""
            )

    def get_detail_url(self) -> str:
        if self.tmdb_id:
            if str(self.tmdb_id).startswith("DB:"):
                return "https://movie.douban.com/subject/{}".format(str(self.tmdb_id).replace("DB:", ""))
            if self.type == MediaType.MOVIE:
                return f"https://www.themoviedb.org/movie/{self.tmdb_id}"
            return f"https://www.themoviedb.org/tv/{self.tmdb_id}"
        if self.douban_id:
            return f"https://movie.douban.com/subject/{self.douban_id}"
        return ""

    def get_douban_detail_url(self) -> str:
        if self.douban_id:
            return f"https://movie.douban.com/subject/{self.douban_id}"
        return ""

    def get_backdrop_image(self, default=True, original=False):
        return MediaImageResolver.get_backdrop_image(self, default=default, original=original)

    def get_message_image(self):
        return MediaImageResolver.get_message_image(self)

    def get_poster_image(self, original=False):
        return MediaImageResolver.get_poster_image(self, original=original)

    def to_dict(self) -> dict:
        return {
            "id": self.tmdb_id,
            "orgid": self.tmdb_id,
            "title": self.title,
            "year": self.year,
            "type": self.type.value if self.type else "",
            "media_type": self.type.value if self.type else "",
            "vote": self.vote_average,
            "image": self.poster_path,
            "imdb_id": self.imdb_id,
            "tmdb_id": self.tmdb_id,
            "overview": str(self.overview).strip() if self.overview else "",
            "link": self.get_detail_url(),
            "season": self.get_season_list(),
            "episode": self.get_episode_list(),
            "seeds_season": self.seeds_season,
            "seeds_episode": self.seeds_episode,
            "seeds_end_episode": self.seeds_end_episode,
            "backdrop": self.get_backdrop_image(),
            "poster": self.get_poster_image(),
            "org_string": self.org_string,
            "rev_string": self.rev_string,
            "subtitle": self.subtitle,
            "cn_name": self.cn_name,
            "en_name": self.en_name,
            "total_seasons": self.total_seasons,
            "total_episodes": self.total_episodes,
            "part": self.part,
            "resource_type": self.resource_type,
            "resource_effect": self.resource_effect,
            "resource_pix": self.resource_pix,
            "resource_team": self.resource_team,
            "customization": self.customization,
            "video_encode": self.video_encode,
            "audio_encode": self.audio_encode,
            "category": self.category,
            "douban_id": self.douban_id,
            "keyword": self.keyword,
            "original_language": self.original_language,
            "original_title": self.original_title,
            "release_date": self.release_date,
            "networks": self.networks,
            "runtime": self.runtime,
            "fav": self.fav,
            "rss_sites": self.rss_sites,
            "search_sites": self.search_sites,
            "site": self.site,
            "site_order": self.site_order,
            "user_name": self.user_name,
            "enclosure": self.enclosure,
            "res_order": self.res_order,
            "filter_rule": self.filter_rule,
            "over_edition": self.over_edition,
            "size": self.size,
            "seeders": self.seeders,
            "peers": self.peers,
            "page_url": self.page_url,
            "upload_volume_factor": self.upload_volume_factor,
            "download_volume_factor": self.download_volume_factor,
            "hit_and_run": self.hit_and_run,
            "rssid": self.rssid,
            "save_path": self.save_path,
            "download_setting": self.download_setting,
            "ignored_words": self.ignored_words,
            "replaced_words": self.replaced_words,
            "offset_words": self.offset_words,
        }

    @classmethod
    def from_parser(cls, parsed) -> "MediaInfo":
        """从 ParserResult 创建 MediaInfo"""
        if not parsed:
            return cls()
        return cls(
            cn_name=parsed.title_cn,
            en_name=parsed.title_en,
            year=parsed.year,
            begin_season=parsed.season,
            end_season=parsed.end_season,
            begin_episode=parsed.episode,
            end_episode=parsed.end_episode,
            resource_pix=parsed.resource_pix,
            resource_type=parsed.resource_type,
            video_encode=parsed.video_encode,
            audio_encode=parsed.audio_encode,
            resource_team=parsed.resource_team,
            type=parsed.type,
        )

    def init_subtitle(self, title_text):
        """从副标题文本中解析季/集信息 — 从 MetaBase 迁移"""
        if not title_text:
            return
        title_text = f" {title_text} "
        subtitle_season_re = r"(?<!全\s*|共\s*)第\s*([0-9一二三四五六七八九十S\-]+)\s*季(?!\s*全|\s*共)"
        subtitle_season_all_re = (
            r"[全共]\s*([0-9一二三四五六七八九十]+)\s*季|([0-9一二三四五六七八九十]+)\s*季\s*[全共]"
        )
        subtitle_episode_re = r"(?<!全\s*|共\s*)第\s*([0-9一二三四五六七八九十百零EP\-]+)\s*[集话話期](?!\s*全|\s*共)"
        subtitle_episode_all_re = (
            r"([0-9一二三四五六七八九十百零]+)\s*集\s*[全共]|[共全]\s*([0-9一二三四五六七八九十百零]+)\s*[集话話期]"
        )
        if not re.search(r"[全第季集话話期]", title_text, re.IGNORECASE):
            return
        # 第x季
        season_str = re.search(subtitle_season_re, title_text, re.IGNORECASE)
        if season_str:
            seasons = season_str.group(1)
            if seasons:
                seasons = seasons.upper().replace("S", "").strip()
            try:
                end_season = None
                if seasons.find("-") != -1:
                    seasons = seasons.split("-")
                    begin_season = int(cn2an.cn2an(seasons[0].strip(), mode="smart"))
                    if len(seasons) > 1:
                        end_season = int(cn2an.cn2an(seasons[1].strip(), mode="smart"))
                else:
                    begin_season = int(cn2an.cn2an(seasons, mode="smart"))
            except Exception:
                return
            if self.begin_season is None and isinstance(begin_season, int):
                self.begin_season = begin_season
                self.total_seasons = 1
            if (
                self.begin_season is not None
                and self.end_season is None
                and isinstance(end_season, int)
                and end_season != self.begin_season
            ):
                self.end_season = end_season
                self.total_seasons = (self.end_season - self.begin_season) + 1
            self.type = MediaType.TV
        # 第x集
        episode_str = re.search(subtitle_episode_re, title_text, re.IGNORECASE)
        if episode_str:
            episodes = episode_str.group(1)
            if episodes:
                episodes = episodes.upper().replace("E", "").replace("P", "").strip()
            try:
                end_episode = None
                if episodes.find("-") != -1:
                    episodes = episodes.split("-")
                    begin_episode = int(cn2an.cn2an(episodes[0].strip(), mode="smart"))
                    if len(episodes) > 1:
                        end_episode = int(cn2an.cn2an(episodes[1].strip(), mode="smart"))
                else:
                    begin_episode = int(cn2an.cn2an(episodes, mode="smart"))
            except Exception:
                return
            if self.begin_episode is None and isinstance(begin_episode, int):
                self.begin_episode = begin_episode
                self.total_episodes = 1
            if (
                self.begin_episode is not None
                and self.end_episode is None
                and isinstance(end_episode, int)
                and end_episode != self.begin_episode
            ):
                self.end_episode = end_episode
                self.total_episodes = (self.end_episode - self.begin_episode) + 1
            self.type = MediaType.TV
        # x集全
        episode_all_str = re.search(subtitle_episode_all_re, title_text, re.IGNORECASE)
        if episode_all_str:
            episode_all = episode_all_str.group(1) or episode_all_str.group(2)
            if episode_all and self.begin_episode is None:
                try:
                    self.total_episodes = int(cn2an.cn2an(episode_all.strip(), mode="smart"))
                except Exception:
                    return
                self.begin_episode = None
                self.end_episode = None
                self.type = MediaType.TV
        # 全x季 x季全
        season_all_str = re.search(subtitle_season_all_re, title_text, re.IGNORECASE)
        if season_all_str:
            season_all = season_all_str.group(1) or season_all_str.group(2)
            if season_all and self.begin_season is None and self.begin_episode is None:
                try:
                    self.total_seasons = int(cn2an.cn2an(season_all.strip(), mode="smart"))
                except Exception:
                    return
                self.begin_season = 1
                self.end_season = self.total_seasons
                self.type = MediaType.TV
