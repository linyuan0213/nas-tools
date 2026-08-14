"""RSS Feed 轮询策略 — 从站点 RSS Feed 收集资源并匹配订阅."""

import log
from app.core.exceptions import (
    DownloadError,
    IndexerError,
    MediaError,
    NetworkError,
    RepositoryError,
    ServiceError,
)
from app.core.settings import settings
from app.db.repositories.download_repo_adapter import DownloadHistoryRepositoryAdapter
from app.db.repositories.subscribe_repo_adapter import SubscribeHistoryRepositoryAdapter
from app.domain.entities.rss import SubscribeState
from app.domain.enums import SearchType, SystemConfigKey
from app.domain.mediatypes import MediaType
from app.media.service import MediaService
from app.message import Message
from app.services.downloader_core import DownloaderCore
from app.services.rss_processor import RssHelper
from app.services.subscribe.management.service import SubscribeService
from app.services.subscribe.matcher import SubscribeMatcher
from app.services.subscribe.strategy_lock import strategy_lock
from app.sites.site_cache import SiteCache
from app.sites.siteconf import SiteConf
from app.sites.torrent import Torrent
from app.utils import ExceptionUtils, JsonUtils


class RssFeedStrategy:
    """RSS Feed 轮询策略：从站点 RSS Feed 收集资源，识别媒体，匹配订阅，择优下载."""

    def __init__(
        self,
        media: MediaService,
        downloader: DownloaderCore,
        sites: SiteCache,
        siteconf: SiteConf,
        download_repo: DownloadHistoryRepositoryAdapter,
        rss_repo: SubscribeHistoryRepositoryAdapter,
        rsshelper: RssHelper,
        subscribe: SubscribeService | None,
        matcher: SubscribeMatcher,
        message: Message,
        coordinator=None,
        system_config=None,
    ):
        self.media = media
        self.sites = sites
        self.siteconf = siteconf
        self.downloader = downloader
        self.download_repo = download_repo
        self.rss_repo = rss_repo
        self.rsshelper = rsshelper
        self.subscribe = subscribe
        self.matcher = matcher
        self.message = message
        self._coordinator = coordinator
        self._system_config = system_config

    def set_coordinator(self, coordinator) -> None:
        """设置下载协调器（用于 SubscriptionMonitor 注入）."""
        self._coordinator = coordinator

    def run(self) -> None:
        """RSS Feed 轮询入口，由 SubscriptionMonitor 调用，持锁期间自动续期."""
        with strategy_lock("rss:download", ttl_seconds=300) as acquired:
            if not acquired:
                log.info("[RssFeedStrategy] RSS 轮询正在其他实例执行，跳过")
                return
            self._do_rss_poll()

    def _get_default_rss_sites(self, mtype: MediaType) -> list:
        """读取默认订阅设置的 rss_sites（订阅未配置时的回退站点）"""
        if not self._system_config:
            return []
        try:
            default_setting = self._system_config.get(
                SystemConfigKey.DefaultSubscribeSettingTV
                if mtype in (MediaType.TV, MediaType.ANIME)
                else SystemConfigKey.DefaultSubscribeSettingMOV
            )
            if isinstance(default_setting, dict):
                return default_setting.get("rss_sites") or []
        except Exception as e:
            log.debug(f"[RssFeedStrategy]读取默认订阅设置 RSS 站点失败: {e}")
        return []

    def _do_rss_poll(self) -> None:
        if self.sites is None:
            return
        if self.subscribe is None:
            return
        rss_sites_info = self.sites.get_sites(rss=True, public=True)
        if not rss_sites_info:
            return

        log.info("[RssFeedStrategy] 开始 RSS 订阅轮询...")

        rss_movies = self.subscribe.get_subscribe_movies(state=SubscribeState.RUNNING.value)
        if not rss_movies:
            log.warn(f"[RssFeedStrategy] 没有正在订阅的{MediaType.MOVIE.display_name}")
        else:
            log.info(
                "[RssFeedStrategy] {}订阅清单：{}".format(
                    MediaType.MOVIE.display_name,
                    " ".join("{}".format(info.get("name")) for info in rss_movies.values()),
                )
            )

        rss_tvs = self.subscribe.get_subscribe_tvs(state=SubscribeState.RUNNING.value)
        if not rss_tvs:
            log.warn(f"[RssFeedStrategy] 没有正在订阅的{MediaType.TV.display_name}")
        else:
            log.info(
                "[RssFeedStrategy] {}订阅清单：{}".format(
                    MediaType.TV.display_name, " ".join("{}".format(info.get("name")) for info in rss_tvs.values())
                )
            )

        if not rss_movies and not rss_tvs:
            return

        check_sites = []
        check_all = False
        for rinfo in rss_movies.values():
            rss_sites = rinfo.get("rss_sites")
            if not rss_sites:
                check_all = True
                break
            else:
                check_sites += rss_sites
        if not check_all:
            for rinfo in rss_tvs.values():
                rss_sites = rinfo.get("rss_sites")
                if not rss_sites:
                    check_all = True
                    break
                else:
                    check_sites += rss_sites
        if check_all:
            # 订阅未配置 rss_sites → 使用默认订阅设置的 rss_sites（与搜索/手动一致），而非全部站点
            check_sites = self._get_default_rss_sites(MediaType.TV) + self._get_default_rss_sites(
                MediaType.MOVIE
            )
            check_sites = list(set(check_sites))
        else:
            check_sites = list(set(check_sites))

        all_articles = []
        for site_info in rss_sites_info:
            if not site_info:
                continue
            site_name = site_info.get("name")
            if check_sites and site_name not in check_sites:
                continue
            rss_url = site_info.get("rssurl")
            if not rss_url:
                log.info(f"[RssFeedStrategy] {site_name} 未配置 rssurl，跳过...")
                continue
            site_id = site_info.get("id")
            site_order = 100 - int(site_info.get("pri") or 0)

            log.info(f"[RssFeedStrategy] 正在处理：{site_name}")
            rss_articles = self.rsshelper.parse_rssxml(url=rss_url)
            if rss_articles is None:
                log.error(f"[RssFeedStrategy] 站点 {site_name} RSS 链接已过期，请重新获取！")
                self.message.send_site_message(title="[RSS 链接过期提醒]", text=f"站点：{site_name}\n链接：{rss_url}")
                continue
            if not rss_articles:
                log.warn(f"[RssFeedStrategy] {site_name} 未下载到数据")
                continue

            log.info(f"[RssFeedStrategy] {site_name} 获取数据：{len(rss_articles)}")
            for article in rss_articles:
                all_articles.append(
                    {
                        "article": article,
                        "site_name": site_name,
                        "site_id": site_id,
                        "site_order": site_order,
                        "site_cookie": site_info.get("cookie"),
                        "site_api_key": site_info.get("api_key"),
                        "site_bearer_token": site_info.get("bearer_token"),
                        "site_ua": site_info.get("ua"),
                        "site_headers": site_info.get("headers"),
                        "site_parse": site_info.get("parse"),
                        "site_proxy": site_info.get("proxy"),
                        "site_filter_rule": site_info.get("rule"),
                    }
                )

        if not all_articles:
            log.info("[RssFeedStrategy] 所有站点 RSS 处理结束，无有效数据")
            return

        seen_enclosures = set()
        to_identify = []

        for idx, item in enumerate(all_articles):
            article = item["article"]
            title = article.get("title")
            enclosure = article.get("enclosure")

            if not title:
                continue

            if enclosure and enclosure in seen_enclosures:
                continue
            if enclosure and self.rsshelper.is_rssd_by_enclosure(enclosure):
                log.info(f"[RssFeedStrategy] {title} 已成功订阅过")
                continue
            seen_enclosures.add(enclosure or "")

            to_identify.append({"idx": idx, "title": title})

        identify_results = {}
        if to_identify:
            log.info(f"[RssFeedStrategy] 批量识别 {len(to_identify)} 条不重复结果 ...")
            try:
                batch_results = self.media.identify_batch(to_identify)
                for item, info in zip(to_identify, batch_results, strict=False):
                    identify_results[item["idx"]] = info
            except (MediaError, NetworkError) as e:
                log.error(f"[RssFeedStrategy] 批量识别出错: {e}")

        rss_download_torrents = []
        rss_no_exists = {}

        for idx, item in enumerate(all_articles):
            try:
                article = item["article"]
                title = article.get("title")
                if not title:
                    continue

                enclosure = article.get("enclosure")
                page_url = article.get("link")
                size = article.get("size")
                site_name = item["site_name"]
                site_id = item["site_id"]
                site_order = item["site_order"]

                log.info(f"[RssFeedStrategy] 开始处理：{title}")

                if idx not in identify_results:
                    continue
                media_info = identify_results[idx]
                if not media_info:
                    log.warn(f"[RssFeedStrategy] {title} 无法识别出媒体信息！")
                    continue
                elif not media_info.tmdb_info:
                    log.info(f"[RssFeedStrategy] {title} 识别为 {media_info.get_name()} 未匹配到 TMDB 媒体信息")

                media_info.set_torrent_info(
                    size=size, page_url=page_url, site=site_name, site_order=site_order, enclosure=enclosure
                )

                if media_info.tmdb_id:
                    season_episode = media_info.get_season_episode_string()
                    if self.download_repo.is_completed_by_tmdb(str(media_info.tmdb_id), season_episode):
                        log.info(f"[RssFeedStrategy] {title} 已完成下载，跳过")
                        continue

                match_flag, match_msg, match_info = self.matcher.match(
                    media_info=media_info,
                    rss_movies=rss_movies,
                    rss_tvs=rss_tvs,
                    site_id=site_id,
                    site_filter_rule=item["site_filter_rule"],
                    site_cookie=item["site_cookie"],
                    site_api_key=item.get("site_api_key"),
                    site_bearer_token=item.get("site_bearer_token"),
                    site_parse=item["site_parse"],
                    site_ua=item["site_ua"],
                    site_headers=JsonUtils.is_valid_json(item["site_headers"])
                    and JsonUtils.loads(item["site_headers"])
                    or {},
                    site_proxy=item["site_proxy"],
                )

                for msg in match_msg:
                    log.info(f"[RssFeedStrategy] {msg}")

                if not match_flag:
                    if match_info and any("站点属性解析失败" in m for m in match_msg):
                        rtype = "tv" if media_info.type == MediaType.TV else "movie"
                        self.subscribe.update_rss_state(rtype, match_info.get("id"), SubscribeState.ERROR.value)
                        log.warn(f"[RssFeedStrategy] {match_info.get('name')} 站点属性解析失败，标记为错误状态")
                    continue

                if not match_info.get("fuzzy_match"):
                    if not media_info.tmdb_info and media_info.tmdb_id:
                        media_info.set_tmdb_info(
                            self.media.get_tmdb_info(mtype=media_info.type, tmdbid=media_info.tmdb_id)
                        )
                    if not media_info.tmdb_info:
                        continue

                    if not match_info.get("over_edition"):
                        if media_info.type == MediaType.MOVIE:
                            exist_flag, rss_no_exists, _ = self.downloader.check_exists_medias(
                                meta_info=media_info, no_exists=rss_no_exists
                            )
                        else:
                            season = 1
                            if match_info.get("season"):
                                season = int(str(match_info.get("season")).replace("S", ""))
                            total_ep = match_info.get("total")
                            current_ep = match_info.get("current_ep")
                            # 懒更新：TMDB 集数增加时自动同步，避免订阅停留在旧集数
                            # 优先用季详情集数（12h 缓存，episode_count 常滞后），失败再退回主详情
                            if match_info.get("id") and media_info.tmdb_id:
                                try:
                                    new_total = 0
                                    try:
                                        season_detail = self.media.get_tmdb_tv_season_detail(media_info.tmdb_id, season)
                                        season_eps = (
                                            season_detail.get("episodes") if isinstance(season_detail, dict) else None
                                        )
                                        if isinstance(season_eps, list):
                                            new_total = len(season_eps)
                                    except Exception:  # noqa: BLE001
                                        new_total = 0
                                    if new_total <= 0 and media_info.tmdb_info:
                                        new_total = int(
                                            self.media.get_tmdb_season_episodes_num(
                                                tv_info=media_info.tmdb_info, season=season
                                            )
                                            or 0
                                        )
                                    if new_total > 0 and (total_ep is None or new_total > total_ep):
                                        log.info(
                                            f"[RssFeedStrategy] {media_info.get_title_string()} S{season} "
                                            f"TMDB 总集数更新: {total_ep or 0} -> {new_total}"
                                        )
                                        old_total = int(total_ep or 0)
                                        total_ep = int(new_total)
                                        new_missing = list(range(old_total + 1, int(new_total) + 1))
                                        self.subscribe._tv_repo.update_total(
                                            rssid=match_info.get("id"),
                                            total_ep=int(new_total),
                                            lack_episodes=new_missing,
                                        )
                                except Exception as e:  # noqa: BLE001
                                    log.debug(f"[RssFeedStrategy] TMDB 集数检查异常: {e}")
                            episodes = self.subscribe.get_subscribe_tv_episodes(match_info.get("id"))
                            if episodes is None:
                                episodes = []
                                if current_ep:
                                    episodes = list(range(int(current_ep), int(total_ep or 0) + 1))
                            if media_info.tmdb_id not in rss_no_exists:
                                rss_no_exists[media_info.tmdb_id] = []
                            rss_no_exists[media_info.tmdb_id].append(
                                {
                                    "season": season,
                                    "episodes": episodes,
                                    "total_episodes": total_ep,
                                }
                            )
                            exist_flag, library_no_exists, _ = self.downloader.check_exists_medias(
                                meta_info=media_info, total_ep={season: total_ep}
                            )
                            rss_no_exists = Torrent.get_intersection_episodes(
                                target=rss_no_exists, source=library_no_exists, title=media_info.tmdb_id
                            )
                            if rss_no_exists.get(media_info.tmdb_id):
                                missing = rss_no_exists.get(media_info.tmdb_id)
                                log.info(f"[RssFeedStrategy] {media_info.get_title_string()} 订阅缺失季集：{missing}")
                        if exist_flag:
                            continue
                    else:
                        if media_info.type != MediaType.MOVIE and media_info.get_episode_list():
                            log.info(
                                f"[RssFeedStrategy] {media_info.get_title_string()}{media_info.get_season_string()} "
                                f"正在洗版，过滤掉季集不完整的资源：{title}"
                            )
                            continue
                        if not self.subscribe.check_subscribe_over_edition(
                            rtype=media_info.type, rssid=match_info.get("id"), res_order=match_info.get("res_order")
                        ):
                            log.info(
                                f"[RssFeedStrategy] {media_info.get_title_string()}{media_info.get_season_string()} "
                                f"正在洗版，跳过低优先级或同优先级资源：{title}"
                            )
                            continue

                if self.sites.check_ratelimit(site_id):
                    continue

                media_info.set_torrent_info(
                    res_order=match_info.get("res_order"),
                    filter_rule=match_info.get("filter_rule"),
                    over_edition=match_info.get("over_edition"),
                    download_volume_factor=match_info.get("download_volume_factor"),
                    upload_volume_factor=match_info.get("upload_volume_factor"),
                    rssid=match_info.get("id"),
                )
                media_info.set_download_info(
                    download_setting=match_info.get("download_setting"), save_path=match_info.get("save_path")
                )
                self.rsshelper.insert_rss_torrents(media_info)
                if media_info not in rss_download_torrents:
                    rss_download_torrents.append(media_info)
            except (MediaError, DownloadError, IndexerError, RepositoryError, ServiceError, NetworkError) as e:
                ExceptionUtils.exception_traceback(e)
                log.error(f"[RssFeedStrategy] 处理 RSS 发生错误：{e!s}")
                continue

        log.info(f"[RssFeedStrategy] 所有 RSS 处理结束，共 {len(rss_download_torrents)} 个有效资源")
        self._download_matched_torrents(rss_download_torrents=rss_download_torrents, rss_no_exists=rss_no_exists)

    def _download_matched_torrents(self, rss_download_torrents, rss_no_exists):
        if not rss_download_torrents:
            return

        if self.subscribe is None:
            return
        if self.downloader is None:
            return
        finished_rss_torrents = []
        updated_rss_torrents = []

        def __finish_rss(download_item):
            if not download_item:
                return
            if not download_item.rssid or download_item.rssid in finished_rss_torrents:
                return
            finished_rss_torrents.append(download_item.rssid)
            if self.subscribe is None:
                return
            self.subscribe.finish_rss_subscribe(rssid=download_item.rssid, media=download_item)

        def __update_tv_rss(download_item, left_media):
            if not download_item or not left_media:
                return
            if not download_item.rssid or download_item.rssid in updated_rss_torrents:
                return
            updated_rss_torrents.append(download_item.rssid)
            if self.subscribe is None:
                return
            self.subscribe.update_subscribe_tv_lack(
                rssid=download_item.rssid, media_info=download_item, seasoninfo=left_media
            )

        def __update_over_edition(download_item):
            if not download_item:
                return
            if not download_item.rssid or download_item.rssid in updated_rss_torrents:
                return
            if download_item.get_episode_list():
                return
            updated_rss_torrents.append(download_item.rssid)
            if self.subscribe is None:
                return
            self.subscribe.update_subscribe_over_edition(
                rtype=download_item.type, rssid=download_item.rssid, media=download_item
            )

        for media in rss_download_torrents:
            if media.type not in (MediaType.TV, MediaType.ANIME):
                continue
            if media.begin_episode is not None:
                continue
            if not media.enclosure or media.enclosure.startswith("magnet:"):
                continue
            try:
                episodes, file_path = self.downloader.get_torrent_episodes(media.enclosure, media.page_url)
                if file_path:
                    Torrent.delete_torrent_file(file_path)
                if episodes:
                    media.total_episodes = len(episodes)
                    media.begin_episode = min(episodes)
                    media.end_episode = max(episodes)
                    log.info(
                        f"[RssFeedStrategy] {media.org_string or media.title} 解析种子实际集数：{len(episodes)} 集"
                    )
                else:
                    log.info(f"[RssFeedStrategy] {media.org_string or media.title} 解析种子未识别出集数，视为单集")
            except DownloadError as e:
                log.debug(f"[RssFeedStrategy] 解析种子失败：{e!s}")

        def _rss_sort_key(x):
            episode_list = x.get_episode_list() if hasattr(x, "get_episode_list") else []
            episode_count = max(len(episode_list), getattr(x, "total_episodes", 0))
            if episode_count > 1:
                collection_priority = 2
            elif (
                getattr(x, "type", None) in (MediaType.TV, MediaType.ANIME)
                and getattr(x, "begin_season", None) is not None
                and getattr(x, "begin_episode", None) is None
            ):
                collection_priority = 1
            else:
                collection_priority = 0
            download_order = (settings.get("pt") or {}).get("download_order")
            # 做种数优先时做种数在站点顺序前，与下载优先规则一致
            if download_order == "seeder":
                return (
                    collection_priority,
                    episode_count,
                    x.res_order,
                    x.seeders,
                    x.site_order,
                )
            return (collection_priority, episode_count, x.res_order, x.site_order, x.seeders)

        rss_download_torrents.sort(key=_rss_sort_key, reverse=True)

        if self._coordinator:
            filtered = []
            for item in rss_download_torrents:
                if self._coordinator.try_acquire(item):
                    filtered.append(item)
                else:
                    log.info(f"[RssFeedStrategy] {item.title} 已被其他策略锁定，跳过")
            rss_download_torrents = filtered

        try:
            download_items, _ = self.downloader.batch_download(
                SearchType.SUBSCRIBE, rss_download_torrents, rss_no_exists
            )

            if download_items:
                for item in download_items:
                    if not item.rssid:
                        continue
                    if item.over_edition:
                        __update_over_edition(item)
                    elif not rss_no_exists or not rss_no_exists.get(item.tmdb_id):
                        __finish_rss(item)
                    else:
                        __update_tv_rss(item, rss_no_exists.get(item.tmdb_id))
                log.info(f"[RssFeedStrategy] 实际下载了 {len(download_items)} 个资源")
            else:
                log.info("[RssFeedStrategy] 未下载到任何资源")
        finally:
            if self._coordinator:
                for item in rss_download_torrents:
                    self._coordinator.release(item)
