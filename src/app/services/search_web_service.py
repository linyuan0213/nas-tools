"""
WEB 资源搜索服务
对应原 search_medias_for_web 功能
"""

import hashlib
from concurrent.futures import ThreadPoolExecutor, as_completed
from contextlib import contextmanager

import log
from app.agent.agents.search_intent import SearchIntentAgent
from app.core.exceptions import DomainError, RepositoryError, ServiceError
from app.core.settings import settings
from app.domain.enums import ProgressKey, SearchType
from app.domain.mediatypes import MediaType
from app.infrastructure.progress import ProgressTracker
from app.media.service import MediaService
from app.services.search_service import Searcher
from app.services.web.utils import get_mediainfo_from_id
from app.utils import StringUtils

# 媒体识别结果缓存
_MEDIA_IDENT_CACHE: dict = {}
_MEDIA_IDENT_CACHE_VERSION = "2"


def _clear_media_ident_cache():
    """清除媒体识别缓存"""
    _MEDIA_IDENT_CACHE.clear()


@contextmanager
def _web_search_executor(max_workers=8):
    """Web搜索线程池上下文管理器"""
    executor = ThreadPoolExecutor(max_workers=max_workers, thread_name_prefix="web_search")
    try:
        yield executor
    finally:
        executor.shutdown(wait=False)


def search_medias_for_web(
    content,
    searcher: Searcher,
    progress_helper: ProgressTracker,
    media_service: MediaService,
    intent_agent: SearchIntentAgent | None,
    ident_flag=True,
    filters=None,
    tmdbid=None,
    media_type=None,
    session_id: str | None = None,
):
    """
    WEB资源搜索
    :param content: 关键字文本，可以包括 类型、标题、季、集、年份等信息
    :param ident_flag: 是否进行媒体信息识别
    :param filters: 其它过滤条件
    :param tmdbid: TMDBID或DB:豆瓣ID
    :param media_type: 媒体类型，配合tmdbid传入
    :return: 错误码，错误原因，成功时直接插入数据库
    """
    mtype, key_word, season_num, episode_num, year, content = StringUtils.get_keyword_from_string(content)

    # Agent 意图解析（自然语言查询）
    _intent_agent = intent_agent
    if _intent_agent and _intent_agent.ready and key_word:
        try:
            intent = _intent_agent.parse(content or "")
            if intent and intent.is_specific:
                if intent.keywords and len(intent.keywords) > len(key_word):
                    key_word = intent.keywords
                if intent.media_type:
                    if intent.media_type == "movie":
                        mtype = MediaType.MOVIE
                    elif intent.media_type in ("tv", "anime"):
                        mtype = MediaType.TV
                if intent.season is not None:
                    season_num = intent.season
                if intent.episode is not None:
                    episode_num = intent.episode
                if intent.year is not None:
                    year = str(intent.year)
                log.info(
                    f"[Web]Agent 解析搜索意图: {content} -> {key_word}, type={mtype}, "
                    f"season={season_num}, episode={episode_num}, year={year}"
                )
        except (ServiceError, RepositoryError, DomainError):
            raise
        except Exception as e:
            log.warn(f"[Web]Agent 意图解析失败: {e}")

    if not key_word:
        log.info(f"[Web]{content} 搜索关键字有误！")
        return -1, f"{content} 未识别到搜索关键字！"

    if media_type:
        mtype = media_type

    _searcher = searcher
    _process = progress_helper
    _media = media_service
    _process.start(ProgressKey.Search)

    media_info = None
    search_name_list = []
    max_workers = 1

    if ident_flag:
        if tmdbid:
            media_info = get_mediainfo_from_id(mtype=mtype, mediaid=tmdbid)
        else:
            raw = f"{content}_{mtype}_{_MEDIA_IDENT_CACHE_VERSION}".encode()
            cache_key = hashlib.md5(raw, usedforsecurity=False).hexdigest()
            if cache_key in _MEDIA_IDENT_CACHE:
                media_info = _MEDIA_IDENT_CACHE[cache_key]
                log.info(f"[Web]从缓存获取媒体信息: {content}")
            else:
                media_info = _media.get_media_info(mtype=media_type or mtype, title=content)
                if media_info and media_info.tmdb_info:
                    _MEDIA_IDENT_CACHE[cache_key] = media_info

        if media_info:
            if season_num:
                media_info.begin_season = int(season_num)
            if episode_num:
                media_info.begin_episode = int(episode_num)

        if media_info and media_info.tmdb_info:
            media_type = media_info.type.value if media_info.type else ""
            log.info(f"[Web]从TMDB中匹配到{media_type}：{media_info.get_title_string()}")
            search_season = media_info.get_season_list() if media_info.begin_season is not None else None
            search_episode = media_info.get_episode_list()
            if search_episode and not search_season:
                search_season = [1]

            search_cn_name = media_info.cn_name or media_info.title
            search_en_name = None
            if media_info.en_name:
                search_en_name = media_info.en_name
            elif media_info.original_language == "en":
                search_en_name = media_info.original_title
            else:
                en_title = _media.get_tmdb_en_title(media_info)
                if en_title:
                    search_en_name = en_title
                    media_info.en_name = en_title

            if search_cn_name:
                search_name_list.append(search_cn_name)
            if search_en_name and search_en_name != search_cn_name:
                search_name_list.append(search_en_name)

            if settings.get("laboratory").get("search_multi_language"):
                search_zhtw_name = _media.get_tmdb_zhtw_title(media_info)
                if search_zhtw_name and search_zhtw_name != search_cn_name and search_zhtw_name != search_en_name:
                    search_name_list.append(search_zhtw_name)
                if (
                    media_info.original_language != "cn"
                    and media_info.original_title
                    and media_info.original_title != search_cn_name
                    and media_info.original_title != search_en_name
                ):
                    search_name_list.append(media_info.original_title)

            search_name_list = list(set(filter(None, search_name_list)))
            max_workers = min(len(search_name_list), 8)

            filter_args = {
                "season": search_season,
                "episode": search_episode,
                "year": media_info.year,
                "type": media_info.type,
            }
        else:
            log.info(f"[Web]{content} 未从TMDB匹配到媒体信息，将使用快速搜索...")
            ident_flag = False
            media_info = None
            search_name_list.append(key_word)
            filter_args = {"season": season_num, "episode": episode_num, "year": year}
    else:
        search_name_list.append(key_word)
        filter_args = {"season": season_num, "episode": episode_num, "year": year}

    if filters:
        filter_args.update(filters)

    log.info(f"[Web]开始通过 {search_name_list} 搜索 ...")

    media_list = []
    if search_name_list:
        _process.update_max(ptype=ProgressKey.Search, value=5, text=f"准备搜索 {content} ...")
        with _web_search_executor(max_workers) as executor:
            all_task = []
            for search_name in search_name_list:
                task = executor.submit(_searcher.search_medias, search_name, filter_args, media_info, SearchType.WEB)
                all_task.append(task)

            finish_count = 0
            for finish_count, future in enumerate(as_completed(all_task), start=1):
                result = future.result()
                # 关键词搜索占 5-70%，去重排序占 70-90%，入库占 90-100%
                pct = 5 + round(65 * (finish_count / len(all_task)))
                _process.update_max(
                    ptype=ProgressKey.Search,
                    value=pct,
                    text=f"关键词 {finish_count}/{len(all_task)} 完成 ({pct}%)",
                )
                if result:
                    media_list.extend(result)

    # 去重：与 DB 唯一键 (PAGEURL, SITE, SEARCH_SESSION_ID) 对齐
    _process.update_max(ptype=ProgressKey.Search, value=70, text="去重排序中...")
    unique_media_list = []
    media_seen = set()
    for d in media_list:
        # page_url 缺失时，按入库逻辑回退到 enclosure 前 200 字符；两者都为空则只按 site 去重
        page_key = d.page_url or ((d.enclosure or "")[:200] if d.enclosure else "")
        dedup_key = StringUtils.md5_hash(f"{page_key}{d.site}")
        if dedup_key not in media_seen:
            unique_media_list.append(d)
            media_seen.add(dedup_key)
    media_list = unique_media_list

    if len(media_list) == 0:
        _process.end(ProgressKey.Search)
        log.info(f"[Web]{content} 未搜索到任何资源")
        return 1, f"{content} 未搜索到任何资源"
    else:
        log.info(f"[Web]共搜索到 {len(media_list)} 个有效资源")
        _process.update_max(ptype=ProgressKey.Search, value=90, text=f"共 {len(media_list)} 个有效资源，入库中...")
        media_list = sorted(
            media_list,
            key=lambda x: "{}{}{}".format(
                str(x.res_order).rjust(3, "0"), str(x.site_order).rjust(3, "0"), str(x.seeders).rjust(10, "0")
            ),
            reverse=True,
        )
        if media_info:
            poster_url = media_info.get_poster_image()
            if poster_url:
                for media_item in media_list:
                    if not media_item.get_poster_image():
                        media_item.poster_path = poster_url
            if media_info.overview:
                for media_item in media_list:
                    if not media_item.overview:
                        media_item.overview = media_info.overview
            if media_info.vote_average:
                for media_item in media_list:
                    if not media_item.vote_average:
                        media_item.vote_average = media_info.vote_average
        # 按 session 隔离：先清同 session 旧数据再插入
        if session_id:
            _searcher.search_repo.delete_by_session(session_id)
        else:
            _searcher.delete_all_search_torrents()
        _searcher.insert_search_results(
            media_items=media_list, ident_flag=ident_flag, title=content, session_id=session_id
        )
        _process.update_max(ptype=ProgressKey.Search, value=100, text=f"搜索完成，共 {len(media_list)} 个资源")
        _process.end(ProgressKey.Search)
        return 0, ""
