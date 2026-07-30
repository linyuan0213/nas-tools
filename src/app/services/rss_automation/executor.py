"""RSS 任务执行核心（模块级函数）."""

import time
import traceback
from typing import Any

import log
from app.core.exceptions import RepositoryError, ServiceError
from app.core.settings import settings
from app.domain.enums import SearchType, UserRssTaskUseType
from app.domain.media_type_utils import MediaTypeMapper
from app.domain.mediatypes import MediaType
from app.events.bus import EventBus
from app.events.constants import RSS_AUTO_SUBSCRIBE_REQUESTED
from app.events.payloads import RssAutoSubscribeRequestedPayload
from app.events.types import Event
from app.infrastructure.http.client import HttpClient
from app.infrastructure.http.config import HttpClientConfig
from app.media import meta_info
from app.services.rss_automation.parser import RssParserEngine
from app.utils import ExceptionUtils
from app.utils.config_tools import get_proxies
from app.utils.json_utils import JsonUtils


def _check_task_rss(service, taskid: int | None, event_bus: EventBus | None = None) -> None:
    """处理自定义RSS任务，由定时服务调用."""
    if not taskid:
        return
    rss_download_torrents = []
    rss_subscribe_torrents = []
    rss_search_torrents = []
    taskinfo = service.get_rsstask_info(taskid)
    if not taskinfo:
        return
    rss_result = _parse_userrss_result(service, taskinfo)
    if len(rss_result) == 0:
        log.warn("[RssTaskService]{} 未下载到数据".format(taskinfo.get("name")))
        return
    else:
        log.info("[RssTaskService]{} 获取数据：{}".format(taskinfo.get("name"), len(rss_result)))
    res_num = 0
    no_exists = {}
    for res in rss_result:
        try:
            title = res.get("title")
            if not title:
                continue
            enclosure = res.get("enclosure")
            page_url = res.get("link")
            size = int(res.get("size") or 0)
            year = res.get("year")
            if year and len(year) > 4:
                year = year[:4]
            mediatype = res.get("type")
            if mediatype:
                mediatype = MediaType.from_string(mediatype)

            log.info(f"[RssTaskService]开始处理：{title}")

            task_type = taskinfo.get("uses")
            meta_name = f"{title} {year}" if year else title
            if service.is_article_processed(task_type, title, year, enclosure):
                log.info(f"[RssTaskService]{title} 已处理过")
                continue

            if task_type == UserRssTaskUseType.DOWNLOAD.value:
                media_info = meta_info(title=meta_name, mtype=mediatype)
                if taskinfo.get("recognization") == "Y":
                    media_info = service.media.get_media_info(title=meta_name, mtype=mediatype)
                    if not media_info:
                        log.warn(f"[RssTaskService]{title} 识别媒体信息出错！")
                        continue
                    if not media_info.tmdb_info:
                        log.info(f"[RssTaskService]{title} 识别为 {media_info.get_name()} 未匹配到媒体信息")
                        continue
                    if media_info.type == MediaType.MOVIE:
                        exist_flag, no_exists, _ = service.downloader.check_exists_medias(
                            meta_info=media_info, no_exists=no_exists
                        )
                        if exist_flag:
                            log.info(f"[RssTaskService]电影 {media_info.get_title_string()} 已存在")
                            continue
                    else:
                        exist_flag, no_exists, _ = service.downloader.check_exists_medias(
                            meta_info=media_info, no_exists=no_exists
                        )
                        if exist_flag:
                            if not no_exists or not no_exists.get(media_info.tmdb_id):
                                log.info(
                                    f"[RssTaskService]电视剧 {media_info.get_title_string()} "
                                    f"{media_info.get_season_episode_string()} 已存在"
                                )
                            continue
                        if no_exists.get(media_info.tmdb_id):
                            missing = no_exists.get(media_info.tmdb_id)
                            log.info(f"[RssTaskService]{media_info.get_title_string()} 缺失季集：{missing}")
                media_info.set_torrent_info(
                    size=size, page_url=page_url, site=taskinfo.get("name"), enclosure=enclosure
                )
                filter_args = {
                    "include": taskinfo.get("include"),
                    "exclude": taskinfo.get("exclude"),
                    "rule": taskinfo.get("filter"),
                }
                match_flag, res_order, match_msg = service.filter.check_torrent_filter(
                    meta_info=media_info, filter_args=filter_args
                )
                if not match_flag:
                    log.info(f"[RssTaskService]{match_msg}")
                    continue
                else:
                    media_info.set_torrent_info(res_order=res_order)
                    if taskinfo.get("recognization") == "Y":
                        log.info(
                            f"[RssTaskService]{title} 识别为 {media_info.get_title_string()} "
                            f"{media_info.get_season_episode_string()} 匹配成功"
                        )
                        if not media_info.tmdb_info:
                            media_info.set_tmdb_info(
                                service.media.get_tmdb_info(mtype=media_info.type, tmdbid=media_info.tmdb_id)
                            )
                        if media_info.type != MediaType.MOVIE:
                            service.config_repo.insert_userrss_mediainfos(taskid, media_info)
                    else:
                        log.info(f"[RssTaskService]{title}  匹配成功")
                if not enclosure:
                    log.warn("[RssTaskService]{} RSS报文中没有enclosure种子链接".format(taskinfo.get("name")))
                    continue
                if media_info not in rss_download_torrents:
                    rss_download_torrents.append(media_info)
                    res_num = res_num + 1
            elif task_type == UserRssTaskUseType.SUBSCRIBE.value:
                media_info = meta_info(title=meta_name, mtype=mediatype)
                filter_args = {"include": taskinfo.get("include"), "exclude": taskinfo.get("exclude"), "rule": -1}
                match_flag, _, match_msg = service.filter.check_torrent_filter(
                    meta_info=media_info, filter_args=filter_args
                )
                if not match_flag:
                    log.info(f"[RssTaskService]{match_msg}")
                    continue
                if service.rss_repo.check_rss_history(
                    type_str=MediaTypeMapper.to_tmdb(media_info.type),  # type: ignore[reportArgumentType]
                    name=media_info.title,
                    year=media_info.year,
                    season=media_info.get_season_string(),
                ):
                    log.info(
                        f"[RssTaskService]{media_info.get_title_string()}{media_info.get_season_string()} 已订阅过"
                    )
                    continue
                media_info.set_torrent_info(enclosure=meta_name)
                service.rsshelper.insert_rss_torrents(media_info)
                if media_info not in rss_subscribe_torrents:
                    rss_subscribe_torrents.append(media_info)
                    res_num = res_num + 1
            else:
                continue
        except (ServiceError, RepositoryError):
            raise
        except Exception as e:
            ExceptionUtils.exception_traceback(e, "处理RSS任务时发生错误")
            log.error(f"[RssTaskService]处理RSS发生错误：{e!s} - {traceback.format_exc()}")
            continue
    log.info("[RssTaskService]{} 处理结束，匹配到 {} 个有效资源".format(taskinfo.get("name"), res_num))
    if rss_download_torrents:
        for media in rss_download_torrents:
            downloader_id, ret, ret_msg = service.downloader.download(
                media_info=media,
                download_dir=taskinfo.get("save_path"),
                download_setting=taskinfo.get("download_setting"),
                in_from=SearchType.USERRSS,
                proxy=taskinfo.get("proxy"),
            )
            if ret:
                service.rsshelper.insert_rss_torrents(media)
                conf = service.downloader.get_downloader_conf(downloader_id)
                downloader_name = conf.get("name") if conf else ""
                service.config_repo.insert_userrss_task_history(taskid, media.org_string or "", downloader_name or "")
            else:
                log.error(
                    "[RssTaskService]添加下载任务 {} 失败：{}".format(
                        media.get_title_string(), ret_msg or "请检查下载任务是否已存在"
                    )
                )
    if event_bus and rss_subscribe_torrents:
        for media in rss_subscribe_torrents:
            event_bus.publish(
                Event(
                    event_type=RSS_AUTO_SUBSCRIBE_REQUESTED,
                    payload=RssAutoSubscribeRequestedPayload(
                        mtype=media.type,
                        name=media.get_name(),
                        year=media.year,
                        channel="manual",
                        season=media.begin_season,
                        rss_sites=taskinfo.get("sites", {}).get("rss_sites"),
                        search_sites=taskinfo.get("sites", {}).get("search_sites"),
                        over_edition=bool(taskinfo.get("over_edition")),
                        filter_restype=taskinfo.get("filter_args", {}).get("restype"),
                        filter_pix=taskinfo.get("filter_args", {}).get("pix"),
                        filter_team=taskinfo.get("filter_args", {}).get("team"),
                        filter_rule=taskinfo.get("filter"),
                        save_path=taskinfo.get("save_path"),
                        download_setting=taskinfo.get("download_setting"),
                    ),
                )
            )
            log.info(f"[RssTaskService]{media.get_name()} 已发送订阅请求事件")

    counter = len(rss_download_torrents) + len(rss_subscribe_torrents) + len(rss_search_torrents)
    if counter:
        service.config_repo.update_userrss_task_info(taskid, counter)
        taskinfo["counter"] = (
            int(taskinfo.get("counter")) + counter if str(taskinfo.get("counter")).isdigit() else counter
        )
        taskinfo["update_time"] = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(time.time()))


def _parse_userrss_result(service, taskinfo: dict[str, Any]) -> list[dict[str, Any]]:
    """获取RSS链接数据，根据PARSER进行解析获取返回结果."""
    task_name = taskinfo.get("name")
    rss_urls = taskinfo.get("address") or []
    rss_parsers = taskinfo.get("parser") or []
    count = min(len(rss_urls), len(rss_parsers))
    rss_result = []
    engine = service.site_engine
    for i in range(count):
        rss_url = rss_urls[i]
        if not rss_url:
            continue
        rss_parser = service.get_userrss_parser(rss_parsers[i])
        if not rss_parser:
            log.error(f"[RssTaskService]任务 {task_name} RSS地址 {rss_url} 配置解析器不存在")
            continue
        parser_name = rss_parser.get("name")
        if not rss_parser.get("format"):
            log.error(f"[RssTaskService]任务 {task_name} 配置解析器 {parser_name} 格式不正确")
            continue
        try:
            JsonUtils.loads(rss_parser.get("format"))
        except (ServiceError, RepositoryError):
            raise
        except Exception as e:
            ExceptionUtils.exception_traceback(e, f"任务 {task_name} 配置解析器 {parser_name} JSON格式错误")
            log.error(f"[RssTaskService]任务 {task_name} 配置解析器 {parser_name} 不是合法的Json格式")
            continue

        if rss_parser.get("params"):
            _dict = {"TMDBKEY": settings.get("app").get("rmt_tmdbkey")}
            try:
                param_url = rss_parser.get("params").format(**_dict)
            except (ServiceError, RepositoryError):
                raise
            except Exception as e:
                ExceptionUtils.exception_traceback(e, f"任务 {task_name} 配置解析器 {parser_name} 附加参数不合法")
                log.error(f"[RssTaskService]任务 {task_name} 配置解析器 {parser_name} 附加参数不合法")
                continue
            rss_url = f"{rss_url}?{param_url}" if rss_url.find("?") == -1 else f"{rss_url}&{param_url}"
        proxies = get_proxies() if taskinfo.get("proxy") else None
        proxy_url = proxies.get("http") if proxies else None
        rate_limiter = getattr(engine, "site_limiter", None)
        rate_limiter_engine = rate_limiter.engine if rate_limiter else None
        try:
            ret = HttpClient(
                config=HttpClientConfig(proxy_url=proxy_url),
                rate_limiter=rate_limiter_engine,
            ).get(rss_url)
        except (ServiceError, RepositoryError):
            raise
        except Exception as e2:
            ExceptionUtils.exception_traceback(e2, f"请求RSS地址 {rss_url} 失败")
            continue
        try:
            items = RssParserEngine.parse_items(rss_parser, ret.text, i + 1)
            rss_result.extend(items)
        except (ServiceError, RepositoryError):
            raise
        except Exception as err:
            ExceptionUtils.exception_traceback(err, f"任务 {task_name} RSS报文解析失败")
            log.error(f"[RssTaskService]任务 {task_name} RSS地址 {rss_url} 获取的订阅报文无法解析：{err!s}")
            continue
    return rss_result
