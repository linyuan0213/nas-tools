"""
下载流水线

将 download_core.py 中的 download() 拆分为清晰的阶段化流水线：
1. 种子获取（Fetch）   — 从 URL 或文件获取种子内容
2. 配置解析（Resolve） — 确定下载设置、标签、暂停状态
3. 添加任务（Add）     — 调用下载器添加任务
4. 后续处理（Post）    — 历史记录、字幕、消息

位于 app/downloader/ 层，不依赖 app/services/。
"""

import contextlib
import os
import re
from typing import Any

import log
from app.core.constants import PT_TAG
from app.db.repositories.indexer_site_config_repo_adapter import IndexerSiteConfigRepositoryAdapter
from app.events import Event
from app.events.constants import DOWNLOAD_FAILED, DOWNLOAD_STARTED
from app.events.payloads import DownloadFailedPayload, DownloadStartedPayload
from app.infrastructure.thread import ThreadExecutor
from app.sites.torrent import Torrent
from app.utils import StringUtils
from app.utils.json_utils import JsonUtils


class DownloadPipeline:
    """
    下载流水线

    将下载过程拆分为四个独立的阶段，每个阶段可单独测试和维护。

    使用方式：
        pipeline = DownloadPipeline(client_factory=..., ...)
        downloader_id, download_id, error = pipeline.execute(media_info=..., ...)
    """

    def __init__(
        self,
        client_factory,
        message,
        mediaserver,
        filetransfer,
        sites,
        siteconf,
        sitesubtitle,
        event_bus,
        download_history_repo,
        site_engine,
        site_config_repo: IndexerSiteConfigRepositoryAdapter | None = None,
    ):
        self._client_factory = client_factory
        self._message = message
        self._mediaserver = mediaserver
        self._filetransfer = filetransfer
        self._sites = sites
        self._siteconf = siteconf
        self._sitesubtitle = sitesubtitle
        self._event_bus = event_bus
        self._download_history_repo = download_history_repo
        self._site_engine = site_engine
        self._site_config_repo = site_config_repo or IndexerSiteConfigRepositoryAdapter()

    def execute(
        self,
        media_info,
        is_paused=None,
        tag=None,
        download_dir=None,
        download_setting=None,
        downloader_id=None,
        upload_limit=None,
        download_limit=None,
        torrent_file=None,
        in_from=None,
        user_name=None,
        proxy=None,
        file_indices=None,
        file_names=None,
    ) -> tuple[str | None, str | None, str]:
        """
        执行完整下载流水线

        :return: (downloader_id, download_id, error_msg)
        """
        if self._client_factory is None:
            return None, None, "client_factory not set"
        title = media_info.org_string or media_info.get_title_string() or media_info.title or "未知"

        # ---------- 阶段1：获取种子内容 ----------
        fetch = self._stage_fetch(media_info=media_info, torrent_file=torrent_file, proxy=proxy)
        if not fetch:
            self._fail(media_info, in_from, "下载链接为空")
            return None, None, "下载链接为空"
        content, file_path, dl_files_folder, dl_files, retmsg, site_info, torrent_attr = fetch

        if retmsg:
            log.warn(f"[DownloadPipeline]{retmsg}")
        if not content:
            self._fail(media_info, in_from, retmsg)
            return None, None, retmsg

        # ---------- 阶段2：解析下载设置 ----------
        resolved = self._stage_resolve(
            media_info=media_info,
            download_setting=download_setting,
            downloader_id=downloader_id,
            tag=tag,
            is_paused=is_paused,
            site_info=site_info,
            torrent_attr=torrent_attr,
        )
        download_attr = resolved["download_attr"]
        download_setting_name = download_attr.get("name")
        downloader_id = resolved["downloader_id"]
        tags = resolved["tags"]
        is_paused = resolved["is_paused"]
        upload_limit = upload_limit or download_attr.get("upload_limit")
        download_limit = download_limit or download_attr.get("download_limit")
        ratio_limit = download_attr.get("ratio_limit")
        seeding_time_limit = download_attr.get("seeding_time_limit")
        category = download_attr.get("category")

        downloader_conf = self._client_factory.get_downloader_conf(downloader_id)
        downloader = self._client_factory.get_client(downloader_id)
        if not downloader or not downloader_conf:
            msg = "请检查下载设置所选下载器是否有效且启用"
            self._fail(media_info, in_from, msg)
            return None, None, f"下载设置 {download_setting_name} 所选下载器失效"
        downloader_name = downloader_conf.get("name")

        download_info = self._client_factory.get_download_dir_info(media_info, downloader_conf.get("download_dir"))
        if not download_dir:
            download_dir = download_info.get("path")
        if not category:
            category = download_info.get("category")
        if download_info.get("label"):
            tags.append(download_info.get("label"))

        # ---------- PT 拦截：目标下载器不支持 PT 时拒绝私有站点种子 ----------
        if not getattr(downloader, "supports_pt", True) and self._is_pt_torrent(site_info, content):
            msg = f"下载器 {downloader_name} 不支持 PT 私有站点种子，已拒绝下载"
            log.warn(f"[DownloadPipeline]{msg}: {title}")
            self._fail(media_info, in_from, msg)
            return downloader_id, None, msg

        # ---------- 阶段3：添加任务 ----------
        download_id = self._stage_add(
            downloader=downloader,
            content=content,
            title=title,
            is_paused=is_paused,
            download_dir=download_dir,
            tags=tags,
            category=category,
            upload_limit=upload_limit,
            download_limit=download_limit,
            ratio_limit=ratio_limit,
            seeding_time_limit=seeding_time_limit,
            cookie=site_info.get("cookie"),
            url=media_info.enclosure or torrent_file or "",
            file_indices=file_indices,
            file_names=file_names,
        )
        if not download_id:
            msg = f"下载器 {downloader_name} 添加下载任务失败"
            self._fail(media_info, in_from, msg)
            return downloader_id, None, msg

        self._event_bus.publish(
            Event(
                event_type=DOWNLOAD_STARTED,
                payload=DownloadStartedPayload(
                    media_info=media_info.to_dict(),
                    is_paused=is_paused,
                    tag=tag,
                    download_dir=download_dir,
                    download_setting=download_setting,
                    downloader_id=downloader_id,
                    torrent_file=torrent_file,
                    download_id=download_id,
                ),
            )
        )

        # ---------- 阶段4：后续处理 ----------
        self._stage_post(
            media_info=media_info,
            downloader_id=downloader_id,
            download_id=download_id,
            page_url=media_info.page_url,
            dl_files_folder=dl_files_folder,
            dl_files=dl_files,
            download_dir=download_dir,
            downloader_name=downloader_name,
            download_setting_name=download_setting_name,
            site_info=site_info,
            torrent_attr=torrent_attr,
            in_from=in_from,
            user_name=user_name,
        )

        if not media_info.enclosure and file_path:
            with contextlib.suppress(Exception):
                Torrent(self._site_engine).delete_torrent_file(file_path)

        return downloader_id, download_id, ""

    # ---------- 阶段1：种子获取 ----------

    def _stage_fetch(self, media_info, torrent_file=None, proxy=None):
        site_info: Any = {}
        dl_files_folder: Any = ""
        dl_files: Any = []
        retmsg: Any = ""
        torrent_attr = {}
        file_path = None
        content = None

        if torrent_file:
            content, dl_files_folder, dl_files, retmsg = Torrent(self._site_engine).read_torrent_content(torrent_file)
            file_path = torrent_file
            if media_info.page_url:
                site_info = self._sites.get_sites(siteurl=media_info.page_url)
        else:
            url = media_info.enclosure
            if media_info.page_url and not media_info.enclosure:
                site_info = self._sites.get_sites(siteurl=media_info.page_url)
                url = self._site_engine.resolve_download_url(
                    page_url=media_info.page_url,
                    user_config={
                        "cookie": site_info.get("cookie", ""),
                        "ua": site_info.get("ua", ""),
                        "headers": site_info.get("headers", {}),
                        "proxy": site_info.get("proxy"),
                        "api_key": site_info.get("api_key", ""),
                        "bearer_token": site_info.get("bearer_token", ""),
                    },
                )
            if not url:
                return None
            if url.startswith("magnet:"):
                content = url
            else:
                site_info = self._sites.get_sites(siteurl=url)
                cookie = site_info.get("cookie")
                api_key = site_info.get("api_key")
                bearer_token = site_info.get("bearer_token")
                site_def = self._site_engine.get_by_url(url)
                if site_def and site_def.api and site_def.api.auth.get("type") in ("api_key", "bearer"):
                    cookie = None
                headers = site_info.get("headers")
                headers = JsonUtils.loads(headers) if headers else {}
                if media_info.page_url and site_info.get("id"):
                    torrent_attr = self._siteconf.check_torrent_attr(
                        torrent_url=media_info.page_url,
                        cookie=cookie,
                        api_key=api_key,
                        bearer_token=bearer_token,
                        ua=site_info.get("ua"),
                        headers=headers,
                        proxy=proxy if proxy is not None else site_info.get("proxy") or False,
                    )
                file_path, content, dl_files_folder, dl_files, retmsg = Torrent(self._site_engine).get_torrent_info(
                    url=url,
                    cookie=cookie,
                    api_key=api_key,
                    bearer_token=bearer_token,
                    ua=site_info.get("ua"),
                    referer=media_info.page_url if not site_info.get("referer") else site_info.get("referer"),
                    proxy=proxy if proxy is not None else site_info.get("proxy") or False,
                )

                # enclosure 下载失败且为 API 站(如 M-Team 预签名链接过期)时，
                # 用详情页 tid 重新走下载 API 拿新鲜链接后重试一次
                if not file_path and media_info.enclosure and media_info.page_url:
                    page_site = self._site_engine.get_by_url(media_info.page_url)
                    if page_site and page_site.download and page_site.download.type in ("api", "api_chained"):
                        log.info(f"[Pipeline]下载链接可能已过期，尝试重新获取：{media_info.page_url}")
                        page_info = self._sites.get_sites(siteurl=media_info.page_url)
                        fresh_url = self._site_engine.resolve_download_url(
                            page_url=media_info.page_url,
                            user_config={
                                "cookie": page_info.get("cookie", ""),
                                "ua": page_info.get("ua", ""),
                                "headers": page_info.get("headers", {}),
                                "proxy": page_info.get("proxy"),
                                "api_key": page_info.get("api_key", ""),
                                "bearer_token": page_info.get("bearer_token", ""),
                            },
                        )
                        if fresh_url and fresh_url != url:
                            file_path, content, dl_files_folder, dl_files, retmsg = Torrent(
                                self._site_engine
                            ).get_torrent_info(
                                url=fresh_url,
                                cookie=cookie,
                                api_key=api_key,
                                bearer_token=bearer_token,
                                ua=site_info.get("ua"),
                                referer=media_info.page_url,
                                proxy=proxy if proxy is not None else site_info.get("proxy") or False,
                            )

        return content, file_path, dl_files_folder, dl_files, retmsg, site_info, torrent_attr

    # ---------- 阶段2：配置解析 ----------

    def _stage_resolve(self, media_info, download_setting, downloader_id, tag, is_paused, site_info, torrent_attr):
        if self._client_factory is None:
            return {"download_attr": {}, "downloader_id": downloader_id, "tags": [], "is_paused": is_paused}
        if not download_setting and media_info.site:
            download_setting = self._sites.get_site_download_setting(media_info.site)
            if not download_setting:
                download_setting = self._site_config_repo.get_download_setting(media_info.site)
        if download_setting == "-2":
            download_attr = {}
        elif download_setting:
            download_attr = self._client_factory.get_download_setting(
                download_setting
            ) or self._client_factory.get_download_setting(self._client_factory.default_download_setting_id)
        else:
            download_attr = self._client_factory.get_download_setting(self._client_factory.default_download_setting_id)

        if not downloader_id:
            downloader_id = download_attr.get("downloader")

        tags = download_attr.get("tags")
        if tags:
            tags = str(tags).split(";")
            if tag:
                if isinstance(tag, list):
                    tags.extend(tag)
                else:
                    tags.append(tag)
        else:
            if tag:
                tags = tag if isinstance(tag, list) else [tag]
            else:
                tags = []
        if torrent_attr and torrent_attr.get("hr"):
            tags.append("HR")
        _note = site_info.get("note", {}) if site_info else {}
        if site_info and _note.get("tag"):
            tags.append(site_info.get("name", ""))
        site_tag = site_info.get("name", "") if site_info and _note.get("tag") else None

        if downloader_id:
            downloader_conf = self._client_factory.get_downloader_conf(downloader_id)
            if downloader_conf and downloader_conf.get("only_nexus_media") and PT_TAG not in tags:
                tags.append(PT_TAG)

        if tags:
            tags.sort(key=lambda x: (0 if x == PT_TAG else 1 if x == site_tag else 2, x))

        if is_paused is None:
            is_paused = StringUtils.to_bool(download_attr.get("is_paused"))
        else:
            is_paused = bool(is_paused)

        return {"download_attr": download_attr, "downloader_id": downloader_id, "tags": tags, "is_paused": is_paused}

    # ---------- 阶段3：添加任务 ----------

    def _stage_add(
        self,
        downloader,
        content,
        title,
        is_paused,
        download_dir,
        tags,
        category,
        upload_limit,
        download_limit,
        ratio_limit,
        seeding_time_limit,
        cookie,
        url,
        file_indices=None,
        file_names=None,
    ):
        print_url = content if isinstance(content, str) else url
        log.info(
            f"[DownloadPipeline]{'添加任务并暂停' if is_paused else '添加任务'}：%s，目录：%s，Url：%s"
            % (title, download_dir, print_url)
        )

        return downloader.add_torrent_and_get_id(
            content,
            is_paused=is_paused,
            download_dir=download_dir,
            tags=tags,
            category=category,
            upload_limit=upload_limit,
            download_limit=download_limit,
            ratio_limit=ratio_limit,
            seeding_time_limit=seeding_time_limit,
            cookie=cookie,
            file_indices=file_indices,
            file_names=file_names,
        )

    # ---------- 阶段4：后续处理 ----------

    def _stage_post(
        self,
        media_info,
        downloader_id,
        download_id,
        page_url,
        dl_files_folder,
        dl_files,
        download_dir,
        downloader_name,
        download_setting_name,
        site_info,
        torrent_attr,
        in_from,
        user_name,
    ):
        if not self._client_factory:
            return

        visit_dir = self._client_factory.get_download_visit_dir(download_dir)
        save_dir = subtitle_dir = None
        if visit_dir:
            if dl_files_folder:
                save_dir = os.path.join(visit_dir, dl_files_folder)
                subtitle_dir = save_dir
            elif dl_files:
                save_dir = os.path.join(visit_dir, dl_files[0])
                subtitle_dir = visit_dir
            elif media_info.enclosure and media_info.enclosure.startswith("magnet:"):
                save_dir = visit_dir
                subtitle_dir = visit_dir
            else:
                save_dir = None
                subtitle_dir = visit_dir
                downloader = self._client_factory.get_client(downloader_id)
                if downloader:
                    downloader.delete_torrents(ids=download_id, delete_file=True)
                self._fail(media_info, in_from, "请检查下载任务保存目录是否正确")
                return

        try:
            self._download_history_repo.insert_download_history(
                media_info=media_info, downloader=downloader_id, download_id=download_id, save_dir=save_dir or ""
            )
        except Exception as e:
            log.warn(f"[Pipeline]写入下载历史失败（任务已提交至下载器）: {e}")

        if dl_files:
            self._check_file_type_mismatch(media_info, dl_files)

        if page_url and subtitle_dir and site_info and site_info.get("subtitle"):

            def _download_subtitle():
                try:
                    self._sitesubtitle.download(
                        media_info,
                        site_info.get("id"),
                        site_info.get("cookie"),
                        site_info.get("ua"),
                        subtitle_dir,
                    )
                except Exception:
                    log.warn(f"[Pipeline]字幕下载失败: {media_info.title or media_info.org_string}")

            ThreadExecutor(name="subtitle").submit(_download_subtitle)

        if in_from:
            media_info.user_name = user_name
            media_info.hit_and_run = bool(torrent_attr and torrent_attr.get("hr"))
            self._message.send_download_message(
                in_from=in_from,
                can_item=media_info,
                download_setting_name=download_setting_name,
                downloader_name=downloader_name,
            )

    # ---------- 辅助 ----------

    @staticmethod
    def _infer_type_from_files(file_names: list[str]) -> str | None:
        """从文件列表推断媒体类型：>=3 个递进编号文件 → tv，1 个文件 → movie，其他 → None"""
        if not file_names:
            return None
        if len(file_names) == 1:
            return "movie"
        false_positives = {"720", "1080", "2160", "480", "264", "265", "444", "420", "10"}
        nums: list[list[int]] = []
        for f in file_names:
            found = re.findall(r"(?<!\d)(\d{2,4})(?!\d)", os.path.basename(f))
            filtered = [int(n) for n in found if n not in false_positives]
            if filtered:
                nums.append(filtered)
        if len(nums) < 3:
            return None
        # 取每组的最后一个数字作为标识（通常是集号）
        last_nums = [group[-1] for group in nums]
        for i in range(1, len(last_nums)):
            if last_nums[i] <= last_nums[i - 1]:
                return None
        return "tv"

    @staticmethod
    def _check_file_type_mismatch(media_info, file_names: list[str]) -> None:
        """当文件列表类型推断与 matched type 不一致时输出警告"""
        inferred = DownloadPipeline._infer_type_from_files(file_names)
        if not inferred:
            return
        matched = str(media_info.type.value) if media_info.type else ""
        if inferred != matched:
            log.warn(
                "[Pipeline] 类型推断不一致: 匹配类型={} 文件推断={} name={} files={}".format(
                    matched,
                    inferred,
                    media_info.org_string or media_info.title or "?",
                    file_names[:5],
                )
            )

    @staticmethod
    def _is_pt_torrent(site_info: dict, content) -> bool:
        """判断种子是否来自私有站点（PT）.

        优先用站点定义的 public 标志；字符串内容（magnet/URL）按私密 tracker 特征兜底。
        """
        if site_info and site_info.get("public") is False:
            return True
        if isinstance(content, str):
            for keyword in ("passkey=", "secure=", "announce?uid=", "totheglory", "credential="):
                if keyword in content:
                    return True
        return False

    def _fail(self, media_info, in_from, reason):
        self._event_bus.publish(
            Event(
                event_type=DOWNLOAD_FAILED,
                payload=DownloadFailedPayload(media_info=media_info.to_dict(), reason=reason),
            )
        )
        if in_from:
            self._message.send_download_fail_message(media_info, f"添加下载任务失败：{reason}")
