"""MessageBuilder - 业务消息构建与发送."""

import re
import time
from enum import Enum
from typing import Any

import log
from app.domain.mediatypes import MediaType
from app.services.web import WebUtils
from app.utils import StringUtils


class MessageBuilder:
    """负责各类业务场景的消息内容构建和发送."""

    def __init__(self, client_manager, dispatcher, messagecenter, template_engine=None):
        self._client_manager = client_manager
        self._dispatcher = dispatcher
        self._messagecenter = messagecenter
        self._template_engine = template_engine

    def send_download_message(self, in_from, can_item, download_setting_name=None, downloader_name=None) -> None:
        msg_title = f"{can_item.get_title_ep_string()} 开始下载"
        msg_text = f"{can_item.get_star_string()}"
        msg_text = f"{msg_text}\n来自：{StringUtils.resolve_in_from_display(in_from)}"
        message_image = can_item.get_message_image() if hasattr(can_item, "get_message_image") else ""
        log.debug(f"[MessageBuilder]下载消息图片: {message_image}")
        if download_setting_name:
            msg_text = f"{msg_text}\n下载设置：{download_setting_name}"
        if downloader_name:
            msg_text = f"{msg_text}\n下载器：{downloader_name}"
        if can_item.user_name:
            msg_text = f"{msg_text}\n用户：{can_item.user_name}"
        if can_item.site:
            if StringUtils.resolve_in_from_display(in_from) == "自定义订阅":
                msg_text = f"{msg_text}\n任务：{can_item.site}"
            else:
                msg_text = f"{msg_text}\n站点：{can_item.site}"
        if can_item.get_resource_type_string():
            msg_text = f"{msg_text}\n质量：{can_item.get_resource_type_string()}"
        if can_item.size:
            if str(can_item.size).isdigit():
                size = StringUtils.str_filesize(can_item.size)
            else:
                size = can_item.size
            msg_text = f"{msg_text}\n大小：{size}"
        if can_item.org_string:
            msg_text = f"{msg_text}\n种子：{can_item.org_string}"
        if can_item.seeders:
            msg_text = f"{msg_text}\n做种数：{can_item.seeders}"
        msg_text = f"{msg_text}\n促销：{can_item.get_volume_factor_string()}"
        if can_item.hit_and_run:
            msg_text = f"{msg_text}\nHit&Run：是"
        if can_item.description:
            html_re = re.compile(r"<[^>]+>", re.S)
            description = html_re.sub("", can_item.description)
            can_item.description = re.sub(r"<[^>]+>", "", description)
            msg_text = f"{msg_text}\n描述：{can_item.description}"
        if self._messagecenter:
            self._messagecenter.insert_system_message(title=msg_title, content=msg_text)
        for client in self._client_manager.active_clients:
            if "download_start" in (client.get("switches") or ""):
                size_str = StringUtils.str_filesize(can_item.size) if can_item.size else ""
                description_clean = ""
                if can_item.description:
                    description_clean = re.sub(r"<[^>]+>", "", can_item.description)
                variables = {
                    "item": can_item,
                    "in_from": StringUtils.resolve_in_from_display(in_from),
                    "download_setting_name": download_setting_name or "",
                    "downloader_name": downloader_name or "",
                    "title": can_item.title or can_item.get_name() or "",
                    "year": can_item.year or "",
                    "season": can_item.get_season_string() if hasattr(can_item, "get_season_string") else "",
                    "episode": can_item.get_episode_string() if hasattr(can_item, "get_episode_string") else "",
                    "site": can_item.site or "",
                    "size": can_item.size or 0,
                    "size_str": size_str,
                    "seeders": can_item.seeders or 0,
                    "peers": can_item.peers or 0,
                    "org_string": can_item.org_string or "",
                    "description": description_clean,
                    "description_raw": can_item.description or "",
                    "resource_type": can_item.get_resource_type_string()
                    if hasattr(can_item, "get_resource_type_string")
                    else "",
                    "volume_factor": can_item.get_volume_factor_string()
                    if hasattr(can_item, "get_volume_factor_string")
                    else "未知",
                    "hit_and_run": can_item.hit_and_run or False,
                    "user_name": can_item.user_name or "",
                    "page_url": can_item.page_url or "",
                    "vote_average": can_item.vote_average or 0,
                    "star_string": can_item.get_star_string() if hasattr(can_item, "get_star_string") else "",
                    "title_ep_string": can_item.get_title_ep_string()
                    if hasattr(can_item, "get_title_ep_string")
                    else "",
                    "title_string": can_item.get_title_string() if hasattr(can_item, "get_title_string") else "",
                }
                self._dispatcher.sendmsg(
                    client=client,
                    title=msg_title,
                    text=msg_text,
                    image=message_image,
                    url="downloading",
                    msg_type="download_start",
                    variables=variables,
                    template_engine=self._template_engine,
                )

    def send_transfer_movie_message(self, in_from, media_info, exist_filenum, category_flag) -> None:
        msg_title = f"{media_info.get_title_string()} 已入库"
        if media_info.vote_average:
            msg_str = f"{media_info.get_vote_string()}，类型：{MediaType.MOVIE.display_name}"
        else:
            msg_str = f"类型：{MediaType.MOVIE.display_name}"
        if media_info.category:
            if category_flag:
                msg_str = f"{msg_str}，类别：{media_info.category}"
        if media_info.get_resource_type_string():
            msg_str = f"{msg_str}，质量：{media_info.get_resource_type_string()}"
        msg_str = (
            f"{msg_str}，大小：{StringUtils.str_filesize(media_info.size)}，"
            f"来自：{StringUtils.resolve_in_from_display(in_from)}"
        )
        if exist_filenum != 0:
            msg_str = f"{msg_str}，{exist_filenum}个文件已存在"
        if self._messagecenter:
            self._messagecenter.insert_system_message(title=msg_title, content=msg_str)
        for client in self._client_manager.active_clients:
            if "transfer_finished" in (client.get("switches") or ""):
                variables = {
                    "media_info": media_info,
                    "in_from": StringUtils.resolve_in_from_display(in_from),
                    "exist_filenum": exist_filenum,
                    "category_flag": category_flag,
                }
                self._dispatcher.sendmsg(
                    client=client,
                    title=msg_title,
                    text=msg_str,
                    image=media_info.get_message_image(),
                    url="history",
                    msg_type="transfer_finished",
                    variables=variables,
                    template_engine=self._template_engine,
                )

    def send_transfer_tv_message(
        self, message_medias: dict, in_from: Enum, exist_filenum: int = 0, category_flag: bool = False
    ) -> None:
        for item_info in message_medias.values():
            if item_info.total_episodes == 1:
                msg_title = f"{item_info.get_title_string()} {item_info.get_season_episode_string()} 已入库"
            else:
                msg_title = (
                    f"{item_info.get_title_string()} {item_info.get_season_string()} "
                    f"共{item_info.total_episodes}集 已入库"
                )
            if item_info.vote_average:
                msg_str = f"{item_info.get_vote_string()}，类型：{item_info.type.display_name}"
            else:
                msg_str = f"类型：{item_info.type.display_name}"
            if item_info.category:
                msg_str = f"{msg_str}，类别：{item_info.category}"
            from_source = f"，来自：{StringUtils.resolve_in_from_display(in_from)}"
            if item_info.total_episodes == 1:
                msg_str = f"{msg_str}，大小：{StringUtils.str_filesize(item_info.size)}{from_source}"
            else:
                msg_str = f"{msg_str}，总大小：{StringUtils.str_filesize(item_info.size)}{from_source}"
            if self._messagecenter:
                self._messagecenter.insert_system_message(title=msg_title, content=msg_str)
            for client in self._client_manager.active_clients:
                if "transfer_finished" in (client.get("switches") or ""):
                    variables = {
                        "media_info": item_info,
                        "in_from": StringUtils.resolve_in_from_display(in_from),
                        "exist_filenum": exist_filenum,
                        "category_flag": category_flag,
                        "total_episodes": item_info.total_episodes if hasattr(item_info, "total_episodes") else 1,
                        "season_episode": item_info.get_season_episode_string()
                        if hasattr(item_info, "get_season_episode_string")
                        else "",
                    }
                    self._dispatcher.sendmsg(
                        client=client,
                        title=msg_title,
                        text=msg_str,
                        image=item_info.get_message_image(),
                        url="history",
                        msg_type="transfer_finished",
                        variables=variables,
                        template_engine=self._template_engine,
                    )

    def send_download_fail_message(self, item, error_msg: str) -> None:
        title = f"添加下载任务失败：{item.get_title_string()} {item.get_season_episode_string()}"
        text = f"站点：{item.site}\n种子名称：{item.org_string}\n种子链接：{item.enclosure}\n错误信息：{error_msg}"
        if self._messagecenter:
            self._messagecenter.insert_system_message(title=title, content=text)
        for client in self._client_manager.active_clients:
            if "download_fail" in (client.get("switches") or ""):
                variables = {"item": item, "error_msg": error_msg}
                self._dispatcher.sendmsg(
                    client=client,
                    title=title,
                    text=text,
                    image=item.get_message_image(),
                    msg_type="download_fail",
                    variables=variables,
                    template_engine=self._template_engine,
                )

    def send_subscribe_success_message(self, in_from: Enum, media_info) -> None:
        if media_info.type == MediaType.MOVIE:
            msg_title = f"{media_info.get_title_string()} 已添加订阅"
        else:
            msg_title = f"{media_info.get_title_string()} {media_info.get_season_string()} 已添加订阅"
        msg_str = f"类型：{media_info.type.display_name}"
        if media_info.vote_average:
            msg_str = f"{msg_str}，{media_info.get_vote_string()}"
        msg_str = f"{msg_str}，来自：{StringUtils.resolve_in_from_display(in_from)}"
        if media_info.user_name:
            msg_str = f"{msg_str}，用户：{media_info.user_name}"
        if self._messagecenter:
            self._messagecenter.insert_system_message(title=msg_title, content=msg_str)
        for client in self._client_manager.active_clients:
            if "rss_added" in (client.get("switches") or ""):
                variables = {"media_info": media_info, "in_from": StringUtils.resolve_in_from_display(in_from)}
                self._dispatcher.sendmsg(
                    client=client,
                    title=msg_title,
                    text=msg_str,
                    image=media_info.get_message_image(),
                    url="movie_rss" if media_info.type == MediaType.MOVIE else "tv_rss",
                    msg_type="rss_added",
                    variables=variables,
                    template_engine=self._template_engine,
                )

    def send_rss_finished_message(self, media_info) -> None:
        if media_info.type == MediaType.MOVIE:
            return
        if media_info.over_edition:
            msg_title = f"{media_info.get_title_string()} {media_info.get_season_string()} 已完成洗版"
        else:
            msg_title = f"{media_info.get_title_string()} {media_info.get_season_string()} 已完成订阅"
        msg_str = f"类型：{media_info.type.display_name}"
        if media_info.vote_average:
            msg_str = f"{msg_str}，{media_info.get_vote_string()}"
        if self._messagecenter:
            self._messagecenter.insert_system_message(title=msg_title, content=msg_str)
        for client in self._client_manager.active_clients:
            if "rss_finished" in (client.get("switches") or ""):
                variables = {
                    "media_info": media_info,
                    "over_edition": media_info.over_edition if hasattr(media_info, "over_edition") else False,
                }
                self._dispatcher.sendmsg(
                    client=client,
                    title=msg_title,
                    text=msg_str,
                    image=media_info.get_message_image(),
                    url="downloaded",
                    msg_type="rss_finished",
                    variables=variables,
                    template_engine=self._template_engine,
                )

    def send_site_signin_message(self, msgs: list) -> None:
        if not msgs:
            return
        title = "站点签到"
        text = "\n".join(msgs)
        if self._messagecenter:
            self._messagecenter.insert_system_message(title=title, content=text)
        for client in self._client_manager.active_clients:
            if "site_signin" in (client.get("switches") or ""):
                variables = {"msgs": msgs}
                self._dispatcher.sendmsg(
                    client=client,
                    title=title,
                    text=text,
                    msg_type="site_signin",
                    variables=variables,
                    template_engine=self._template_engine,
                )

    def send_site_message(self, title=None, text=None) -> None:
        if not title:
            return
        if not text:
            text = ""
        if self._messagecenter:
            self._messagecenter.insert_system_message(title=title, content=text)
        for client in self._client_manager.active_clients:
            if "site_message" in (client.get("switches") or ""):
                variables = {"title": title, "text": text}
                self._dispatcher.sendmsg(
                    client=client,
                    title=title,
                    text=text,
                    msg_type="site_message",
                    variables=variables,
                    template_engine=self._template_engine,
                )

    def send_site_parse_health_message(self, title=None, text=None) -> None:
        """站点解析健康告警：独立开关 site_parse_health，与通用站点通知分开控制."""
        if not title:
            return
        if not text:
            text = ""
        if self._messagecenter:
            self._messagecenter.insert_system_message(title=title, content=text)
        for client in self._client_manager.active_clients:
            if "site_parse_health" in (client.get("switches") or ""):
                variables = {"title": title, "text": text}
                self._dispatcher.sendmsg(
                    client=client,
                    title=title,
                    text=text,
                    msg_type="site_parse_health",
                    variables=variables,
                    template_engine=self._template_engine,
                )

    def send_transfer_fail_message(self, path: str, count: int, text: str) -> None:
        if not path or not count:
            return
        title = f"[{count} 个文件入库失败]"
        text = f"源路径：{path}\n原因：{text}"
        if self._messagecenter:
            self._messagecenter.insert_system_message(title=title, content=text)
        for client in self._client_manager.active_clients:
            if "transfer_fail" in (client.get("switches") or ""):
                variables = {"path": path, "count": count, "text": text}
                self._dispatcher.sendmsg(
                    client=client,
                    title=title,
                    text=text,
                    url="unidentification",
                    msg_type="transfer_fail",
                    variables=variables,
                    template_engine=self._template_engine,
                )

    def send_auto_remove_torrents_message(self, title: str, text: str) -> None:
        if not title or not text:
            return
        if self._messagecenter:
            self._messagecenter.insert_system_message(title=title, content=text)
        for client in self._client_manager.active_clients:
            if "auto_remove_torrents" in (client.get("switches") or ""):
                variables = {"title": title, "text": text}
                self._dispatcher.sendmsg(
                    client=client,
                    title=title,
                    text=text,
                    url="torrent_remove",
                    msg_type="auto_remove_torrents",
                    variables=variables,
                    template_engine=self._template_engine,
                )

    def send_brushtask_remove_message(self, title: str, text: str) -> None:
        if not title or not text:
            return
        if self._messagecenter:
            self._messagecenter.insert_system_message(title=title, content=text)
        for client in self._client_manager.active_clients:
            if "brushtask_remove" in (client.get("switches") or ""):
                variables = {"title": title, "text": text}
                self._dispatcher.sendmsg(
                    client=client,
                    title=title,
                    text=text,
                    url="brushtask",
                    msg_type="brushtask_remove",
                    variables=variables,
                    template_engine=self._template_engine,
                )

    def send_brushtask_added_message(self, title: str, text: str) -> None:
        if not title or not text:
            return
        if self._messagecenter:
            self._messagecenter.insert_system_message(title=title, content=text)
        for client in self._client_manager.active_clients:
            if "brushtask_added" in (client.get("switches") or ""):
                variables = {"title": title, "text": text}
                self._dispatcher.sendmsg(
                    client=client,
                    title=title,
                    text=text,
                    url="brushtask",
                    msg_type="brushtask_added",
                    variables=variables,
                    template_engine=self._template_engine,
                )

    def send_brushtask_pause_message(self, title: str, text: str) -> None:
        if not title or not text:
            return
        if self._messagecenter:
            self._messagecenter.insert_system_message(title=title, content=text)
        for client in self._client_manager.active_clients:
            if "brushtask_pause" in (client.get("switches") or ""):
                variables = {"title": title, "text": text}
                self._dispatcher.sendmsg(
                    client=client,
                    title=title,
                    text=text,
                    url="brushtask",
                    msg_type="brushtask_pause",
                    variables=variables,
                    template_engine=self._template_engine,
                )

    def send_mediaserver_message(self, event_info: dict, channel: Any, image_url: str | None) -> None:
        if not event_info or not channel:
            return
        _webhook_actions = {
            "library.new": "新入库",
            "system.webhooktest": "测试",
            "playback.start": "开始播放",
            "playback.stop": "停止播放",
            "user.authenticated": "登录成功",
            "user.authenticationfailed": "登录失败",
            "media.play": "开始播放",
            "media.stop": "停止播放",
            "PlaybackStart": "开始播放",
            "PlaybackStop": "停止播放",
            "item.rate": "标记了",
        }
        _webhook_images = {
            "Emby": "https://emby.media/notificationicon.png",
            "Plex": "https://www.plex.tv/wp-content/uploads/2022/04/new-logo-process-lines-gray.png",
            "Jellyfin": "https://play-lh.googleusercontent.com/SCsUK3hCCRqkJbmLDctNYCfehLxsS4ggD1ZPHIFrrAN1Tn9yhjmGMPep2D9lMaaa9eQi",
        }
        if not _webhook_actions.get(event_info.get("event") or ""):
            return
        item_type = event_info.get("item_type") or ""
        parsed = MediaType.from_string(item_type)
        action = _webhook_actions.get(event_info.get("event") or "<unknown>")
        if parsed in (MediaType.TV, MediaType.ANIME) or item_type == "show":
            message_title = f"{action}{MediaType.TV.display_name} {event_info.get('item_name')}"
        elif parsed == MediaType.MOVIE:
            message_title = f"{action}{MediaType.MOVIE.display_name} {event_info.get('item_name')}"
        elif event_info.get("item_type") == "AUD":
            message_title = f"{action}有声书 {event_info.get('item_name')}"
        else:
            message_title = f"{action}"
        message_texts = []
        if event_info.get("user_name"):
            message_texts.append(f"用户：{event_info.get('user_name')}")
        if event_info.get("device_name"):
            message_texts.append(f"设备：{event_info.get('client')} {event_info.get('device_name')}")
        if event_info.get("ip"):
            message_texts.append(f"位置：{event_info.get('ip')} {WebUtils.get_location(event_info.get('ip'))}")
        if event_info.get("percentage"):
            percentage = round(float(event_info.get("percentage") or 0), 2)
            message_texts.append(f"进度：{percentage}%")
        if event_info.get("overview"):
            message_texts.append(f"剧情：{event_info.get('overview')}")
        message_texts.append(f"时间：{time.strftime('%Y-%m-%d %H:%M:%S', time.localtime(time.time()))}")
        if not image_url:
            image_url = _webhook_images.get(channel)
        message_content = "\n".join(message_texts)
        if self._messagecenter:
            self._messagecenter.insert_system_message(title=message_title, content=message_content)
        url = event_info.get("play_url") or ""
        for client in self._client_manager.active_clients:
            if "mediaserver_message" in (client.get("switches") or ""):
                variables = {
                    "event_info": event_info,
                    "channel": channel,
                    "message_title": message_title,
                    "message_content": message_content,
                    "image_url": image_url,
                    "url": url,
                }
                self._dispatcher.sendmsg(
                    client=client,
                    title=message_title,
                    text=message_content,
                    image=image_url,
                    url=url,
                    msg_type="mediaserver_message",
                    variables=variables,
                    template_engine=self._template_engine,
                )

    def send_plugin_message(
        self, title: str, text: str | None = "", image: str | None = "", url: str | None = ""
    ) -> None:
        if not title:
            return
        if self._messagecenter:
            self._messagecenter.insert_system_message(title=title, content=text)
        for client in self._client_manager.active_clients:
            if "custom_message" in (client.get("switches") or ""):
                variables = {"title": title, "text": text, "url": url, "image": image}
                self._dispatcher.sendmsg(
                    client=client,
                    title=title,
                    text=text,
                    url=url,
                    image=image,
                    msg_type="custom_message",
                    variables=variables,
                    template_engine=self._template_engine,
                )

    def send_custom_message(self, clients, title: str, text: str = "", image: str = "") -> None:
        if not title:
            return
        if not clients:
            return
        if self._messagecenter:
            self._messagecenter.insert_system_message(title=title, content=text)
        for client in self._client_manager.active_clients:
            if str(client.get("id")) in clients:
                variables = {"title": title, "text": text, "image": image}
                self._dispatcher.sendmsg(
                    client=client,
                    title=title,
                    text=text,
                    image=image,
                    msg_type="custom_message",
                    variables=variables,
                    template_engine=self._template_engine,
                )

    def send_user_statistics_message(self, msgs: list) -> None:
        if not msgs:
            return
        title = "站点数据统计"
        text = "\n".join(msgs)
        if self._messagecenter:
            self._messagecenter.insert_system_message(title=title, content=text)
        for client in self._client_manager.active_clients:
            if "ptrefresh_date_message" in (client.get("switches") or ""):
                variables = {"msgs": msgs, "title": title, "text": text}
                self._dispatcher.sendmsg(
                    client=client,
                    title=title,
                    text=text,
                    msg_type="ptrefresh_date_message",
                    variables=variables,
                    template_engine=self._template_engine,
                )
