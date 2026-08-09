"""Subscribe update service - 更新订阅."""

from dataclasses import asdict
from typing import Any, cast

from app.domain.entities.rss import SubscribeState
from app.domain.enums import SubscribeType
from app.domain.mediatypes import MediaType
from app.events import Event
from app.events.constants import SUBSCRIBE_ADD
from app.events.payloads import SubscribeAddPayload
from app.media import meta_info
from app.services.subscribe.management.utils import gen_rss_note
from app.services.web.utils import WebUtils


class SubscribeUpdateService:
    """更新订阅服务"""

    def __init__(
        self,
        movie_repo,
        tv_repo,
        media_service,
        message,
        event_bus,
        system_config,
        web_utils: WebUtils,
    ):
        self._movie_repo = movie_repo
        self._tv_repo = tv_repo
        self._media = media_service
        self._message = message
        self._event_bus = event_bus
        self._system_config = system_config
        self._web_utils = web_utils

    def update_rss_subscribe(
        self,
        mtype: Any,
        rssid: int | None,
        name: str | None = None,
        year: Any = None,
        keyword: str | None = None,
        season: int | None = None,
        fuzzy_match: bool = False,
        mediaid: str | None = None,
        rss_sites: list[str] | str | None = None,
        search_sites: list[str] | str | None = None,
        over_edition: bool | int = False,
        filter_restype: str | None = None,
        filter_pix: str | None = None,
        filter_team: str | None = None,
        filter_rule: int | str | None = None,
        filter_include: str | None = None,
        filter_exclude: str | None = None,
        filter_free: bool | None = None,
        save_path: str | None = None,
        download_setting: int | str | None = None,
        total_ep: int | None = None,
        current_ep: int | None = None,
        state: str = SubscribeState.PENDING.value,
        in_from: str | None = None,
        user_name: str | None = None,
        image: str | None = None,
    ) -> tuple[int, str, Any]:
        """更新电影、电视剧订阅"""
        if not rssid:
            return -1, "缺少订阅ID", None

        year = int(str(year)) if str(year).isdigit() else ""
        if isinstance(rss_sites, str):
            rss_sites = rss_sites.split(",")
        if isinstance(search_sites, str):
            search_sites = search_sites.split(",")
        over_edition = 1 if over_edition else 0
        filter_rule = int(str(filter_rule)) if str(filter_rule).isdigit() else 0
        total_ep = int(str(total_ep)) if str(total_ep).isdigit() else None
        current_ep = int(str(current_ep)) if str(current_ep).isdigit() else None
        download_setting = int(str(download_setting)) if str(download_setting).replace("-", "").isdigit() else -1
        fuzzy_match = bool(fuzzy_match)

        media_info = None
        if not fuzzy_match:
            if mediaid:
                media_info = self._web_utils.get_mediainfo_from_id(mtype=mtype, mediaid=mediaid)
                if not season and media_info:
                    season = media_info.begin_season
            else:
                if season:
                    title = "%s %s 第%s季".strip() % (name, year, season)
                else:
                    title = "%s %s".strip() % (name, year)
                media_info = self._media.get_media_info(title=title, mtype=mtype, strict=bool(year), cache=False)
            if not media_info or not media_info.tmdb_info:
                return 1, "TMDB无法查询到媒体信息", None
            if media_info.type != MediaType.MOVIE:
                if not season and str(mediaid).startswith("DB:"):
                    season = 1
                if season:
                    total_episode = (
                        total_ep
                        if total_ep
                        else self._media.get_tmdb_season_episodes_num(tv_info=media_info.tmdb_info, season=int(season))
                    )
                else:
                    total_seasoninfo = self._media.get_tmdb_tv_seasons(tv_info=media_info.tmdb_info)
                    if not total_seasoninfo:
                        return 2, "获取剧集信息失败", media_info
                    total_seasoninfo = sorted(total_seasoninfo, key=lambda x: x.get("season_number"), reverse=True)
                    season = total_seasoninfo[0].get("season_number")
                    total_episode = total_seasoninfo[0].get("episode_count")
                if not total_episode:
                    return 3, f"第{season}季获取剧集数失败，请确认该季是否存在", media_info
                media_info.begin_season = int(season or 0)
                media_info.total_episodes = total_episode
                if total_ep:
                    total = total_ep
                else:
                    total = media_info.total_episodes
                if current_ep:
                    # 首个待下载集为 current_ep → 缺失集数 = total - current_ep + 1
                    lack = max(0, total - current_ep + 1)
                else:
                    lack = total
                season_str = media_info.get_season_string()
                code = self._tv_repo.update(
                    rssid=int(rssid),
                    name=media_info.title,
                    year=media_info.year,
                    season=season_str,
                    tmdbid=media_info.tmdb_id,
                    image=image or media_info.get_poster_image(),
                    rss_sites=rss_sites,
                    search_sites=search_sites,
                    over_edition=over_edition,
                    filter_restype=filter_restype,
                    filter_pix=filter_pix,
                    filter_team=filter_team,
                    filter_rule=filter_rule,
                    filter_include=filter_include,
                    filter_exclude=filter_exclude,
                    filter_free=filter_free,
                    save_path=save_path,
                    download_setting=download_setting,
                    total_ep=total_ep,
                    current_ep=current_ep,
                    total=total,
                    lack=lack,
                    state=state,
                    desc=media_info.overview,
                    note=gen_rss_note(media_info),
                    keyword=keyword,
                    fuzzy_match=0,
                )
            else:
                code = self._movie_repo.update(
                    rssid=int(rssid),
                    name=media_info.title,
                    year=media_info.year,
                    tmdbid=media_info.tmdb_id,
                    image=image or media_info.get_poster_image(),
                    rss_sites=rss_sites,
                    search_sites=search_sites,
                    over_edition=over_edition,
                    filter_restype=filter_restype,
                    filter_pix=filter_pix,
                    filter_team=filter_team,
                    filter_rule=filter_rule,
                    filter_include=filter_include,
                    filter_exclude=filter_exclude,
                    filter_free=filter_free,
                    save_path=save_path,
                    download_setting=download_setting,
                    state=state,
                    desc=media_info.overview,
                    note=gen_rss_note(media_info),
                    keyword=keyword,
                    fuzzy_match=0,
                )
        else:
            media_info = meta_info(title=name or "", mtype=mtype)
            media_info.title = name
            media_info.type = mtype
            if season:
                media_info.begin_season = int(season)
            if mtype == MediaType.MOVIE:
                code = self._movie_repo.update(
                    rssid=int(rssid),
                    name=name,
                    year=year,
                    image=image,
                    rss_sites=rss_sites,
                    search_sites=search_sites,
                    over_edition=over_edition,
                    filter_restype=filter_restype,
                    filter_pix=filter_pix,
                    filter_team=filter_team,
                    filter_rule=filter_rule,
                    filter_include=filter_include,
                    filter_exclude=filter_exclude,
                    filter_free=filter_free,
                    save_path=save_path,
                    download_setting=download_setting,
                    state=state,
                    keyword=keyword,
                    fuzzy_match=1,
                )
            else:
                season_str = media_info.get_season_string() if media_info.begin_season else ""
                code = self._tv_repo.update(
                    rssid=int(rssid),
                    name=name,
                    year=year,
                    season=season_str,
                    image=image,
                    rss_sites=rss_sites,
                    search_sites=search_sites,
                    over_edition=over_edition,
                    filter_restype=filter_restype,
                    filter_pix=filter_pix,
                    filter_team=filter_team,
                    filter_rule=filter_rule,
                    filter_include=filter_include,
                    filter_exclude=filter_exclude,
                    filter_free=filter_free,
                    save_path=save_path,
                    download_setting=download_setting,
                    total=0,
                    lack=0,
                    state=state,
                    keyword=keyword,
                    fuzzy_match=1,
                )

        if code == 0:
            self._event_bus.publish(
                Event(
                    event_type=SUBSCRIBE_ADD,
                    payload=asdict(
                        SubscribeAddPayload(
                            media=media_info.to_dict() if media_info else {},
                            rssid=rssid,
                            rss_sites=cast(list[str], rss_sites),
                            search_sites=cast(list[str], search_sites),
                            over_edition=bool(over_edition),
                            filter_restype=filter_restype,
                            filter_pix=filter_pix,
                            filter_team=filter_team,
                            filter_rule=filter_rule,
                            save_path=save_path,
                            download_setting=download_setting,
                            total_ep=total_ep,
                            current_ep=current_ep,
                            fuzzy_match=fuzzy_match,
                            keyword=keyword,
                        )
                    ),
                ),
            )
            if in_from and media_info:
                media_info.user_name = user_name
                self._message.send_subscribe_success_message(
                    in_from=cast(SubscribeType, in_from), media_info=media_info
                )
            return code, "更新订阅成功", media_info
        else:
            return code, "更新订阅失败", media_info
