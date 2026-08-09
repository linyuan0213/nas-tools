"""订阅领域事件处理器.

由 app.di.factories 在对象图构建完成后显式注册，避免事件处理器直接访问 registry。
"""

import log
from app.db.repositories.subscribe_repo_adapter import (
    SubscribeTvEpisodeRepositoryAdapter,
    SubscribeTvRepositoryAdapter,
)
from app.domain.entities.rss import SubscribeState
from app.events import Event, on_event
from app.events.constants import (
    MEDIA_EPISODE_TRANSFERRED,
    RSS_AUTO_SUBSCRIBE_REQUESTED,
    SUBSCRIBE_ADD,
    SUBSCRIBE_FINISHED,
)
from app.events.payloads import (
    MediaEpisodeTransferredPayload,
    RssAutoSubscribeRequestedPayload,
    SubscribeAddPayload,
    SubscribeFinishedPayload,
)
from app.infrastructure.thread import ThreadExecutor
from app.services.subscribe.management.service import SubscribeService
from app.services.subscribe.strategies.queue_search import QueueSearchStrategy


@on_event(SUBSCRIBE_FINISHED)
def handle_subscribe_finished(event: Event) -> None:
    """订阅完成事件处理器"""
    payload = event.payload
    if not isinstance(payload, SubscribeFinishedPayload):
        payload = SubscribeFinishedPayload(**payload)
    log.info(f"[Event]订阅完成: rssid={payload.rssid}")


@on_event(SUBSCRIBE_ADD)
def handle_subscribe_add(event: Event) -> None:
    """订阅添加事件处理器"""
    payload = event.payload
    if not isinstance(payload, SubscribeAddPayload):
        payload = SubscribeAddPayload(**payload)
    log.info(f"[Event]订阅添加: rssid={payload.rssid}")


def build_rss_auto_subscribe_handler(subscribe_service: SubscribeService):
    """构造 RSS 自动订阅事件处理器并注册到事件系统。"""

    @on_event(RSS_AUTO_SUBSCRIBE_REQUESTED)
    def handle_rss_auto_subscribe(event: Event) -> None:
        """RSS自动化订阅请求处理器"""
        payload = event.payload
        if not isinstance(payload, RssAutoSubscribeRequestedPayload):
            payload = RssAutoSubscribeRequestedPayload(**payload)
        try:
            code, msg, _ = subscribe_service.add_rss_subscribe(
                mtype=payload.mtype,
                name=payload.name,
                year=payload.year,
                season=payload.season,
                rss_sites=payload.rss_sites,
                search_sites=payload.search_sites,
                over_edition=payload.over_edition,
                filter_restype=payload.filter_restype,
                filter_pix=payload.filter_pix,
                filter_team=payload.filter_team,
                filter_rule=payload.filter_rule,
                save_path=payload.save_path,
                download_setting=payload.download_setting,
            )
            if code != 0:
                log.warn(f"[Event]自定义RSS订阅请求处理失败：{msg}")
            else:
                log.info(f"[Event]自定义RSS订阅请求已处理：{payload.name}")
        except Exception as e:
            log.error(f"[Event]处理自定义RSS订阅请求失败：{e!s}")

    return handle_rss_auto_subscribe


@on_event(MEDIA_EPISODE_TRANSFERRED)
def handle_media_episode_transferred(event: Event) -> None:
    """单集转移完成事件处理器 — 更新订阅进度"""
    payload = event.payload
    if not isinstance(payload, MediaEpisodeTransferredPayload):
        payload = MediaEpisodeTransferredPayload(**payload)
    try:
        tv_repo = SubscribeTvRepositoryAdapter()
        ep_repo = SubscribeTvEpisodeRepositoryAdapter()
        raw_id = tv_repo.get_id(
            title=payload.title,
            season=payload.season,
            tmdbid=payload.tmdb_id,
        )
        rssid = int(raw_id) if raw_id is not None else None
        if not rssid:
            log.info(f"[Event]未找到订阅: tmdb_id={payload.tmdb_id} season={payload.season}")
            return

        downloaded = {int(e) for e in (payload.episodes or []) if str(e).isdigit()}
        if not downloaded:
            return

        # 在「当前缺失集」基础上减去本次转移的集。
        # 不能用「全集 - 本次转移集」重算，否则会把之前已入库的集误标回缺失，
        # 导致订阅进度倒退并重复下载。
        current_missing = ep_repo.get(rssid)
        if current_missing is None:
            # 缺失列表未初始化：以订阅的 current_ep（首个待下载集）推导初始范围
            subs = tv_repo.get_all(rssid=rssid)
            start = int(subs[0].current_ep) if subs and subs[0].current_ep else 1
            total = int(payload.total_episodes or 0)
            current_missing = list(range(start, total + 1)) if total > 0 else []

        lack_episodes = sorted(set(int(e) for e in current_missing) - downloaded)

        if lack_episodes:
            log.info(f"[Subscribe]更新电视剧 {payload.title} S{payload.season} 缺失集数为 {len(lack_episodes)}")
            tv_repo.update_state(title=None, year=None, season=None, rssid=rssid, state=SubscribeState.RUNNING.value)
            tv_repo.update_lack(title=None, year=None, season=None, rssid=rssid, lack_episodes=lack_episodes)
        else:
            log.info(f"[Subscribe]电视剧 {payload.title} S{payload.season} 全部集数已下载完成")
            tv_repo.update_state(title=None, year=None, season=None, rssid=rssid, state=SubscribeState.COMPLETED.value)
            tv_repo.update_lack(title=None, year=None, season=None, rssid=rssid, lack_episodes=[])
    except Exception as e:
        log.error(f"[Event]更新订阅进度失败：{e!s}")


def build_subscribe_add_search_handler(queue_strategy: QueueSearchStrategy, thread_executor: ThreadExecutor):
    """构造订阅添加/更新后自动触发队列搜索的事件处理器。"""

    @on_event(SUBSCRIBE_ADD)
    def _handle(event: Event) -> None:
        payload = event.payload
        if not isinstance(payload, SubscribeAddPayload):
            payload = SubscribeAddPayload(**payload)
        log.info(f"[Event]订阅添加/更新 rssid={payload.rssid}，触发即时队列搜索")

        def _search():
            try:
                queue_strategy.run()
            except Exception as e:
                log.error(f"[Event]触发队列搜索失败：{e}")

        thread_executor.submit(_search)

    return _handle
