"""app.media.scraper — 媒体元数据刮削模块

重构后架构:
  - Scraper           — 主协调类（保持原有 API）
  - NfoGenerator      — NFO XML 生成
  - ImageDownloader   — 图片下载与文件保存
  - MediaLibrary      — 媒体库文件遍历与 NFO 读取
  - ChineseCredits    — 豆瓣演职人员中文名匹配
"""

import json
import os

import log
from app.core.module_config import ModuleConf
from app.core.settings import settings
from app.core.system_config import SystemConfig
from app.db.repositories.download_repo_adapter import DownloadHistoryRepositoryAdapter
from app.domain.enums import SystemConfigKey
from app.domain.mediatypes import MediaType
from app.infrastructure.ffmpeg import FfmpegProcessor
from app.infrastructure.image_proxy import ImageProxy
from app.infrastructure.temp import temp_manager
from app.media.external.douban import DouBan
from app.media.fanart import Fanart
from app.media.parser._metainfo import meta_info
from app.media.service import MediaService
from app.utils import ExceptionUtils
from app.utils.json_utils import JsonUtils

from .chinese_credits import ChineseCredits
from .image_downloader import ImageDownloader
from .media_library import MediaLibrary
from .nfo_generator import NfoGenerator


class Scraper:
    """媒体元数据刮削器 — 生成 NFO 文件、下载图片"""

    def __init__(
        self,
        media_service: MediaService,
        douban: DouBan | None = None,
        system_config: SystemConfig | None = None,
    ):
        self.media = media_service
        self.douban = douban or DouBan()
        self.fanart = Fanart()
        self._system_config = system_config or SystemConfig()
        self._scraper_flag = False
        self._scraper_nfo = {}
        self._scraper_pic = {}
        self._rmt_mode = None
        self._temp_path = temp_manager.create_subdir("scraper")
        self._init_config()
        self._downloader = ImageDownloader(self._temp_path)
        self._nfo_gen = NfoGenerator(self._downloader)
        self._credits = ChineseCredits(self.media)

    def _init_config(self):
        self._scraper_flag = (settings.get("media") or {}).get("nfo_poster")
        scraper_conf = self._system_config.get(SystemConfigKey.UserScraperConf)
        if isinstance(scraper_conf, str):
            try:
                scraper_conf = JsonUtils.loads(scraper_conf)
                # 兼容旧版双重 JSON 编码（set_scraper_config 曾用 json.dumps 预编码）
                if isinstance(scraper_conf, str):
                    scraper_conf = JsonUtils.loads(scraper_conf)
            except Exception:
                scraper_conf = None
        if isinstance(scraper_conf, dict):
            self._scraper_nfo = scraper_conf.get("scraper_nfo") or {}
            self._scraper_pic = scraper_conf.get("scraper_pic") or {}

    def folder_scraper(self, path, exclude_path=None, mode=None, dst_backend=None):
        """刮削指定文件夹或文件"""
        try:
            force_nfo = mode in ["force_nfo", "force_all"]
            force_pic = mode == "force_all"
            self._downloader.set_dst_backend(dst_backend)
            files = list(MediaLibrary.get_library_files(path, exclude_path, backend=dst_backend))
            log.info(f"[Scraper]发现 {len(files)} 个待刮削文件")
            for file in files:
                if not file:
                    continue
                log.info(f"[Scraper]开始刮削媒体库文件：{file} ...")
                mi = meta_info(os.path.basename(file))
                tmdbid = self._extract_tmdbid(file, mi, dst_backend)
                if tmdbid and not force_nfo:
                    log.info(f"[Scraper]读取到本地nfo文件的tmdbid：{tmdbid}")
                    mi.set_tmdb_info(self.media.get_tmdb_info(mtype=mi.type, tmdbid=tmdbid, append_to_response="all"))
                    media_info = mi
                else:
                    # 尝试从下载历史中读取订阅时记录的 TMDB 信息（TMDB 身份确定，季/集仍从文件名解析）
                    dl_tmdbid, dl_type = self._download_history_tmdb(file)
                    if dl_tmdbid and not force_nfo:
                        log.info(f"[Scraper]从下载历史读取到tmdbid：{dl_tmdbid}，类型={dl_type}")
                        tmdb_details = self.media.get_tmdb_info(
                            mtype=dl_type, tmdbid=dl_tmdbid, append_to_response="all"
                        )
                        if tmdb_details:
                            mi.set_tmdb_info(tmdb_details)
                            # 再用 identify_files 解析季/集（有 tmdb_info 时跳过网络查询，仅做本地解析）
                            medias = self.media.get_media_info_on_files(
                                file_list=[file],
                                tmdb_info=tmdb_details,
                                media_type=dl_type,
                                append_to_response="all",
                                backend=dst_backend,
                            )
                            if medias:
                                media_info = next(iter(medias.values()), mi)
                            else:
                                media_info = mi
                        else:
                            media_info = mi
                    else:
                        medias = self.media.get_media_info_on_files(
                            file_list=[file], append_to_response="all", backend=dst_backend
                        )
                        if not medias:
                            log.warn(f"[Scraper]{file} 无法识别媒体信息")
                            continue
                        media_info = next(iter(medias.values()), None)
                if not media_info or not media_info.tmdb_info:
                    log.warn(f"[Scraper]{file} 无法获取TMDB信息")
                    continue
                self.gen_scraper_files(
                    media=media_info,
                    dir_path=os.path.dirname(file),
                    file_name=os.path.splitext(os.path.basename(file))[0],
                    file_ext=os.path.splitext(file)[-1],
                    force=True,
                    force_nfo=force_nfo,
                    force_pic=force_pic,
                    dst_backend=dst_backend,
                )
                log.info(f"[Scraper]{file} 刮削完成")
        except Exception as e:
            log.error(f"[Scraper]刮削异常：{e}")
            ExceptionUtils.exception_traceback(e)

    def _download_history_tmdb(self, file_path):
        """从下载历史中读取订阅时记录的 TMDB 信息。

        匹配方式：下载历史的 SAVE_PATH 是文件/目录所在路径。
        返回 (tmdbid: int, media_type: str)，未匹配时返回 (None, "")。
        """
        try:
            repo = DownloadHistoryRepositoryAdapter()
            history = repo.get_download_history_by_path(file_path)
            if not history:
                parent = os.path.dirname(file_path)
                if parent and parent != file_path:
                    history = repo.get_download_history_by_path(parent)
            if history:
                # get_download_history_by_path 返回原始 ORM 对象，字段为大写
                tmdbid = getattr(history, "TMDBID", "") or ""
                mtype = getattr(history, "TYPE", "") or ""
                if tmdbid:
                    return int(tmdbid), mtype
        except Exception as e:  # noqa: BLE001
            log.debug(f"[Scraper]读取下载历史 TMDB 失败: {file_path} - {e}")
        return None, ""

    def _extract_tmdbid(self, file_path, meta_info, dst_backend=None):
        """从本地 NFO 文件提取 TMDB ID"""
        if meta_info.type == MediaType.MOVIE:
            movie_nfo = os.path.join(os.path.dirname(file_path), "movie.nfo")
            if dst_backend is not None:
                if dst_backend.exists(movie_nfo):
                    return MediaLibrary.get_tmdbid_from_nfo_remote(movie_nfo, dst_backend)
                file_nfo = os.path.join(os.path.splitext(file_path)[0] + ".nfo")
                if dst_backend.exists(file_nfo):
                    return MediaLibrary.get_tmdbid_from_nfo_remote(file_nfo, dst_backend)
            else:
                if os.path.exists(movie_nfo):
                    return MediaLibrary.get_tmdbid_from_nfo(movie_nfo)
                file_nfo = os.path.join(os.path.splitext(file_path)[0] + ".nfo")
                if os.path.exists(file_nfo):
                    return MediaLibrary.get_tmdbid_from_nfo(file_nfo)
        else:
            tv_nfo = os.path.join(os.path.dirname(os.path.dirname(file_path)), "tvshow.nfo")
            if dst_backend is not None:
                if dst_backend.exists(tv_nfo):
                    return MediaLibrary.get_tmdbid_from_nfo_remote(tv_nfo, dst_backend)
            else:
                if os.path.exists(tv_nfo):
                    return MediaLibrary.get_tmdbid_from_nfo(tv_nfo)
        return None

    def _exists(self, path: str) -> bool:
        """后端感知的存在性检查（远程目标用 dst_backend.exists）"""
        if self._dst_backend is not None:
            try:
                return bool(self._dst_backend.exists(path))
            except Exception:  # noqa: BLE001
                return False
        return os.path.exists(path)

    def gen_scraper_files(
        self, media, dir_path, file_name, file_ext, force=False, force_nfo=False, force_pic=False, dst_backend=None
    ):
        """刮削元数据入口"""
        # 单例在启动时只加载一次配置，这里每次刮削前重新读取，保证运行期配置变更生效
        self._init_config()
        if not force and not self._scraper_flag:
            log.warn("[Scraper]刮削标志未启用，跳过")
            return
        if not self._scraper_nfo and not self._scraper_pic:
            log.warn("[Scraper]刮削配置为空，跳过")
            return
            return
        self._scraper_nfo = self._scraper_nfo or {}
        self._scraper_pic = self._scraper_pic or {}
        self._dst_backend = dst_backend
        self._downloader.set_dst_backend(dst_backend)
        log.info(
            f"[Scraper]开始生成刮削文件：dir={dir_path}, file={file_name}, "
            f"type={media.type}, backend={dst_backend is not None}, "
            f"nfo_keys={list(self._scraper_nfo.keys())}, pic_keys={list(self._scraper_pic.keys())}"
        )

        try:
            if media.type == MediaType.MOVIE:
                self._scrape_movie(media, dir_path, file_name, force_nfo, force_pic)
            else:
                self._scrape_tv(media, dir_path, file_name, file_ext, force_nfo, force_pic)
            log.info(f"[Scraper]刮削文件生成完成：{file_name}")
        except Exception as e:
            log.error(f"[Scraper]刮削文件生成失败：{file_name}，错误：{e}")
            ExceptionUtils.exception_traceback(e)

    def _scrape_movie(self, media, dir_path, file_name, force_nfo, force_pic):
        """刮削电影元数据 — 各步骤独立容错，单步失败不影响其他刮削输出."""
        scraper_movie_nfo = self._scraper_nfo.get("movie", {})
        scraper_movie_pic = self._scraper_pic.get("movie", {})

        if scraper_movie_nfo.get("basic") or scraper_movie_nfo.get("credits"):
            nfo_exists = self._exists(os.path.join(dir_path, "movie.nfo")) or self._exists(
                os.path.join(dir_path, f"{file_name}.nfo")
            )
            if force_nfo or not nfo_exists:
                try:
                    doubaninfo = self._fetch_douban(media, scraper_movie_nfo)
                    directors, actors = self._fetch_credits(media.tmdb_info, scraper_movie_nfo, doubaninfo)
                    self._nfo_gen.gen_movie_nfo(
                        media.tmdb_info, directors, actors, scraper_movie_nfo, dir_path, file_name
                    )
                except Exception as e:
                    log.error(f"[Scraper]生成 movie.nfo 失败：{e}")

        try:
            self._download_images(media, dir_path, scraper_movie_pic, force_pic)
        except Exception as e:
            log.error(f"[Scraper]下载电影图片失败：{e}")

    def _scrape_tv(self, media, dir_path, file_name, file_ext, force_nfo, force_pic):
        """刮削电视剧元数据 — 各步骤独立容错，单步失败不影响其他刮削输出."""
        scraper_tv_nfo = self._scraper_nfo.get("tv", {})
        scraper_tv_pic = self._scraper_pic.get("tv", {})
        tv_root = os.path.dirname(dir_path)

        # ---- tvshow.nfo ----
        if force_nfo or not self._exists(os.path.join(tv_root, "tvshow.nfo")):
            if scraper_tv_nfo.get("basic") or scraper_tv_nfo.get("credits"):
                try:
                    doubaninfo = self._fetch_douban(media, scraper_tv_nfo)
                    directors, actors = self._fetch_credits(media.tmdb_info, scraper_tv_nfo, doubaninfo)
                    self._nfo_gen.gen_tv_nfo(media.tmdb_info, directors, actors, scraper_tv_nfo, tv_root)
                except Exception as e:
                    log.error(f"[Scraper]生成 tvshow.nfo 失败：{e}")

        # ---- tv 图片 ----
        try:
            self._download_tv_images(media, tv_root, scraper_tv_pic, force_pic)
        except Exception as e:
            log.error(f"[Scraper]下载 TV 图片失败：{e}")

        # ---- 季/集详情 ----
        need_season_detail = (
            scraper_tv_nfo.get("season_basic")
            or scraper_tv_nfo.get("episode_basic")
            or scraper_tv_nfo.get("episode_credits")
            or scraper_tv_pic.get("season_poster")
        )
        seasoninfo = None
        if need_season_detail:
            try:
                seasoninfo = self.media.get_tmdb_tv_season_detail(
                    tmdbid=media.tmdb_id, season=int(media.get_season_seq())
                )
            except Exception as e:
                log.error(f"[Scraper]获取季详情失败：{e}")

        # ---- season.nfo ----
        if scraper_tv_nfo.get("season_basic"):
            if force_nfo or not self._exists(os.path.join(dir_path, "season.nfo")):
                if seasoninfo:
                    try:
                        self._nfo_gen.gen_season_nfo(seasoninfo, int(media.get_season_seq()), dir_path)
                    except Exception as e:
                        log.error(f"[Scraper]生成 season.nfo 失败：{e}")

        # ---- episode.nfo ----
        if scraper_tv_nfo.get("episode_basic") or scraper_tv_nfo.get("episode_credits"):
            if force_nfo or not self._exists(os.path.join(dir_path, f"{file_name}.nfo")):
                if seasoninfo:
                    try:
                        self._nfo_gen.gen_episode_nfo(
                            seasoninfo,
                            scraper_tv_nfo,
                            int(media.get_season_seq()),
                            int(media.get_episode_seq()),
                            dir_path,
                            file_name,
                        )
                    except Exception as e:
                        log.error(f"[Scraper]生成 episode nfo 失败：{e}")

        # ---- season poster ----
        if scraper_tv_pic.get("season_poster"):
            try:
                season_poster = "season{}-poster".format(media.get_season_seq().rjust(2, "0"))
                seasonposter = self.fanart.get_seasonposter(
                    media_type=media.type, queryid=media.tvdb_id, season=media.get_season_seq()
                )
                if seasonposter:
                    self._downloader.download(seasonposter, tv_root, season_poster, force_pic)
                elif seasoninfo:
                    self._downloader.download(
                        ImageProxy.get_tmdbimage_url(seasoninfo.get("poster_path"), prefix="original", use_proxy=False),
                        tv_root,
                        season_poster,
                        force_pic,
                    )
            except Exception as e:
                log.error(f"[Scraper]下载 season poster 失败：{e}")

        # ---- season banner ----
        if scraper_tv_pic.get("season_banner"):
            try:
                seasonbanner = self.fanart.get_seasonbanner(
                    media_type=media.type, queryid=media.tvdb_id, season=media.get_season_seq()
                )
                if seasonbanner:
                    self._downloader.download(
                        seasonbanner,
                        tv_root,
                        "season{}-banner".format(media.get_season_seq().rjust(2, "0")),
                        force_pic,
                    )
            except Exception as e:
                log.error(f"[Scraper]下载 season banner 失败：{e}")

        # ---- season thumb ----
        if scraper_tv_pic.get("season_thumb"):
            try:
                seasonthumb = self.fanart.get_seasonthumb(
                    media_type=media.type, queryid=media.tvdb_id, season=media.get_season_seq()
                )
                if seasonthumb:
                    self._downloader.download(
                        seasonthumb,
                        tv_root,
                        "season{}-landscape".format(media.get_season_seq().rjust(2, "0")),
                        force_pic,
                    )
            except Exception as e:
                log.error(f"[Scraper]下载 season thumb 失败：{e}")

        # ---- episode thumb ----
        if scraper_tv_pic.get("episode_thumb"):
            try:
                episode_thumb = os.path.join(dir_path, file_name + "-thumb.jpg")
                if force_pic or not self._exists(episode_thumb):
                    episode_image = self.media.get_episode_images(
                        tv_id=media.tmdb_id,
                        season_id=media.get_season_seq(),
                        episode_id=media.get_episode_seq(),
                        orginal=True,
                    )
                    if episode_image:
                        self._downloader.download(episode_image, episode_thumb, "", force_pic)
                    elif scraper_tv_pic.get("episode_thumb_ffmpeg"):
                        video_path = os.path.join(dir_path, file_name + file_ext)
                        log.info(f"[Scraper]正在生成缩略图：{video_path} ...")
                        FfmpegProcessor().get_thumb_image_from_video(video_path=video_path, image_path=episode_thumb)
                        log.info(f"[Scraper]缩略图生成完成：{episode_thumb}")
            except Exception as e:
                log.error(f"[Scraper]下载 episode thumb 失败：{e}")

    def _fetch_douban(self, media, scraper_nfo):
        """获取豆瓣信息（用于中文演职人员）"""
        if scraper_nfo.get("credits") and scraper_nfo.get("credits_chinese"):
            return self.douban.get_douban_info(media)
        return None

    def _fetch_credits(self, tmdbinfo, scraper_nfo, doubaninfo):
        """获取导演/演员列表，可选中文匹配"""
        if not scraper_nfo.get("credits"):
            return [], []
        directors, actors = self.media.get_tmdb_directors_actors(tmdbinfo=tmdbinfo)
        if scraper_nfo.get("credits_chinese") and doubaninfo:
            directors, actors = self._credits.match(directors, actors, doubaninfo)
        return directors, actors

    def _download_images(self, media, dir_path, scraper_pic, force_pic):
        """下载电影图片"""
        if scraper_pic.get("poster"):
            poster = media.get_poster_image(original=True)
            if poster:
                self._downloader.download(poster, dir_path, "poster", force_pic)
        if scraper_pic.get("backdrop"):
            backdrop = media.get_backdrop_image(default=False, original=True)
            if backdrop:
                self._downloader.download(backdrop, dir_path, "fanart", force_pic)
        for pic_type in ["background", "logo", "disc", "banner", "thumb"]:
            if scraper_pic.get(pic_type):
                getter = getattr(self.fanart, f"get_{pic_type}", None)
                if getter:
                    url = getter(media_type=media.type, queryid=media.tmdb_id)
                    if url:
                        self._downloader.download(url, dir_path, pic_type, force_pic)

    def _download_tv_images(self, media, tv_root, scraper_pic, force_pic):
        """下载电视剧图片"""
        if scraper_pic.get("poster"):
            poster = media.get_poster_image(original=True)
            if poster:
                self._downloader.download(poster, tv_root, "poster", force_pic)
        if scraper_pic.get("backdrop"):
            backdrop = media.get_backdrop_image(default=False, original=True)
            if backdrop:
                self._downloader.download(backdrop, tv_root, "fanart", force_pic)
        for pic_type in ["background", "logo", "disc", "banner", "thumb"]:
            if scraper_pic.get(pic_type):
                getter = getattr(self.fanart, f"get_{pic_type}", None)
                if getter:
                    url = getter(media_type=media.type, queryid=media.tvdb_id)
                    if url:
                        self._downloader.download(url, tv_root, pic_type, force_pic)
