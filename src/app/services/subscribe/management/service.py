"""Subscribe service - 订阅业务 Facade."""

from typing import Any

import log
from app.domain.entities.rss import SubscribeState
from app.domain.enums import SystemConfigKey
from app.domain.mediatypes import MediaType
from app.media.external.bangumi import Bangumi
from app.services.subscribe.management.add_service import SubscribeAddService
from app.services.subscribe.management.finish_service import SubscribeFinishService
from app.services.subscribe.management.query_service import SubscribeQueryService
from app.services.subscribe.management.refresh_service import SubscribeRefreshService
from app.services.subscribe.management.update_service import SubscribeUpdateService
from app.services.web.utils import WebUtils


class SubscribeService:
    """订阅业务 Facade — 订阅的添加、完成、更新、查询、状态变更."""

    def __init__(
        self,
        movie_repo: Any,
        tv_repo: Any,
        tv_episode_repo: Any,
        history_repo: Any,
        message: Any,
        media_service: Any,
        downloader: Any,
        sites: Any,
        douban: Any,
        indexer_service: Any,
        filter_service: Any,
        event_bus: Any,
        system_config: Any,
        download_repo: Any = None,
        transfer_history_manager: Any = None,
    ):
        self._movie_repo = movie_repo
        self._tv_repo = tv_repo
        self._tv_episode_repo = tv_episode_repo
        self._history_repo = history_repo
        self._message = message
        self._media = media_service
        self._downloader = downloader
        self._sites = sites
        self._douban = douban
        self._indexer_service = indexer_service
        self._filter = filter_service
        self._event_bus = event_bus
        self._system_config = system_config
        self._download_repo = download_repo
        self._transfer_history_manager = transfer_history_manager

        self._web_utils = WebUtils(media_service=media_service, douban=douban, bangumi=Bangumi())

        self._update_svc = SubscribeUpdateService(
            self._movie_repo,
            self._tv_repo,
            self._media,
            self._message,
            self._event_bus,
            self._system_config,
            self._web_utils,
        )
        self._add_svc = SubscribeAddService(
            self._movie_repo,
            self._tv_repo,
            self._media,
            self._message,
            self._event_bus,
            self._system_config,
            self._web_utils,
            self._download_repo,
            self._transfer_history_manager,
        )
        self._finish_svc = SubscribeFinishService(
            self._movie_repo, self._tv_repo, self._history_repo, self._message, self._event_bus, self._download_repo
        )
        self._query_svc = SubscribeQueryService(
            self._movie_repo,
            self._tv_repo,
            self._tv_episode_repo,
            self._history_repo,
            self._sites,
            self._indexer_service,
        )
        self._refresh_svc = SubscribeRefreshService(self._movie_repo, self._tv_repo, self._tv_episode_repo, self._media)

    @property
    def default_subscribe_setting_tv(self) -> dict | None:
        return self._system_config.get(SystemConfigKey.DefaultSubscribeSettingTV) or {}

    @property
    def default_subscribe_setting_mov(self) -> dict | None:
        return self._system_config.get(SystemConfigKey.DefaultSubscribeSettingMOV) or {}

    def update_rss_subscribe(self, *args, **kwargs):
        return self._update_svc.update_rss_subscribe(*args, **kwargs)

    def add_rss_subscribe(self, *args, **kwargs):
        return self._add_svc.add_rss_subscribe(*args, **kwargs)

    def finish_rss_subscribe(self, rssid, media):
        return self._finish_svc.finish_rss_subscribe(rssid, media, self.delete_subscribe)

    def get_subscribe_movies(self, rid=None, state=None):
        return self._query_svc.get_subscribe_movies(rid, state)

    def get_subscribe_tvs(self, rid=None, state=None):
        return self._query_svc.get_subscribe_tvs(rid, state)

    def get_subscribe_tv_episodes(self, rssid):
        return self._query_svc.get_subscribe_tv_episodes(rssid)

    def get_subscribe_seasons(self, tmdbid=None, title=None, year=None):
        return self._query_svc.get_subscribe_seasons(tmdbid, title, year)

    def check_history(self, type_str, name, year=None, season=None):
        return self._query_svc.check_history(type_str, name, year, season)

    def delete_subscribe(self, mtype, title=None, year=None, season=None, rssid=None, tmdbid=None):
        return self._query_svc.delete_subscribe(mtype, title, year, season, rssid, tmdbid)

    def get_subscribe_id(self, mtype, title, year=None, season=None, tmdbid=None):
        return self._query_svc.get_subscribe_id(mtype, title, year, season, tmdbid)

    def refresh_rss_metainfo(self):
        return self._refresh_svc.refresh_rss_metainfo(self.get_subscribe_movies, self.get_subscribe_tvs)

    def update_rss_state(self, rtype, rssid, state):
        if rtype == MediaType.MOVIE:
            movies = self._movie_repo.get_all(rssid=rssid)
            if not movies:
                return
            entity = movies[0]
            if state == SubscribeState.RUNNING.value:
                entity.mark_running()
            elif state == SubscribeState.COMPLETED.value:
                entity.mark_completed()
            elif state == SubscribeState.CANCELLED.value:
                entity.mark_cancelled()
            elif state == SubscribeState.PENDING.value:
                entity.state = SubscribeState.PENDING.value
            elif state == SubscribeState.ERROR.value:
                entity.state = SubscribeState.ERROR.value
            self._movie_repo.update(rssid=rssid, state=entity.state)
        else:
            tvs = self._tv_repo.get_all(rssid=rssid)
            if not tvs:
                return
            entity = tvs[0]
            if state == SubscribeState.RUNNING.value:
                entity.mark_running()
            elif state == SubscribeState.COMPLETED.value:
                entity.mark_completed()
            elif state == SubscribeState.CANCELLED.value:
                entity.mark_cancelled()
            elif state == SubscribeState.PENDING.value:
                entity.state = SubscribeState.PENDING.value
            elif state == SubscribeState.ERROR.value:
                entity.state = SubscribeState.ERROR.value
            self._tv_repo.update(rssid=rssid, state=entity.state)

    def update_subscribe_over_edition(self, rtype, rssid, media):
        if not rssid or not media.res_order or not media.filter_rule:
            return False
        if rtype == MediaType.MOVIE:
            self._movie_repo.update_filter_order(rssid=rssid, res_order=media.res_order)
        else:
            self._tv_repo.update_filter_order(rssid=rssid, res_order=media.res_order)
        over_edition_order = self._filter.get_rule_first_order(rulegroup=media.filter_rule)
        if int(media.res_order) >= int(over_edition_order):
            self.finish_rss_subscribe(rssid=rssid, media=media)
            return True
        else:
            self.update_rss_state(rtype=rtype, rssid=rssid, state=SubscribeState.RUNNING.value)
        return False

    def check_subscribe_over_edition(self, rtype, rssid, res_order):
        if rtype == MediaType.MOVIE:
            pre_res_order = self._movie_repo.get_filter_order(rssid=rssid)
        else:
            pre_res_order = self._tv_repo.get_filter_order(rssid=rssid)
        if not pre_res_order:
            return True
        return int(pre_res_order) < int(res_order or 0)

    def update_subscribe_tv_lack(self, rssid, media_info, seasoninfo):
        self._tv_repo.update_state(title=None, year=None, season=None, rssid=rssid, state=SubscribeState.RUNNING.value)
        if not seasoninfo:
            return
        for info in seasoninfo:
            if str(info.get("season")) == media_info.get_season_seq():
                if info.get("episodes"):
                    log.info(
                        "[Subscribe]更新电视剧 {} {} 缺失集数为 {}".format(
                            media_info.get_title_string(), media_info.get_season_string(), len(info.get("episodes"))
                        )
                    )
                    self._tv_repo.update_lack(
                        title=None, year=None, season=None, rssid=rssid, lack_episodes=info.get("episodes")
                    )
                break

    def truncate_rss_episodes(self):
        self._tv_episode_repo.delete_all()
