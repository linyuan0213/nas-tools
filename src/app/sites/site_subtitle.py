import os
import re
import shutil
from datetime import datetime
from typing import cast

from lxml import etree

import log
from app.core.constants import RMT_SUBEXT
from app.infrastructure.http.auth import CookieAuth
from app.infrastructure.http.client import HttpClient
from app.infrastructure.http.config import HttpClientConfig
from app.infrastructure.temp import temp_manager
from app.sites import engine_tools
from app.utils import ExceptionUtils, PathUtils, StringUtils, SystemUtils
from app.utils.json_utils import JsonUtils


def _get_url_subtitle_name(disposition, url):
    fname = re.findall(r"filename=\"?(.+)\"?", disposition or "")
    if fname:
        fname = str(fname[0].encode("ISO-8859-1").decode()).split(";")[0].strip()
        if fname.endswith('"'):
            fname = fname[:-1]
    elif url and os.path.splitext(url)[-1] in (RMT_SUBEXT + [".zip"]):
        fname = url.split("/")[-1]
    else:
        fname = str(datetime.now())
    return fname


def _transfer_subtitle(source, target):
    new_sub_file = f"{os.path.splitext(target)[0]}{os.path.splitext(source)[-1]}"
    if os.path.exists(new_sub_file):
        return 1
    return SystemUtils.copy(source, new_sub_file)


class SiteSubtitle:
    siteconf = None
    sites = None
    _save_tmp_path = None

    def __init__(self, siteconf, sites, site_engine):
        self.siteconf = siteconf
        self._site_engine = site_engine
        self.sites = sites
        self._save_tmp_path = temp_manager.get_temp_path()

    def download(self, media_info, site_id, cookie, ua, download_dir):
        """
        从站点下载字幕文件，并保存到本地
        """

        if not media_info.page_url:
            return
        # 字幕下载目录
        log.info(f"[Sites]开始从站点下载字幕：{media_info.page_url}")
        if not download_dir:
            log.warn("[Sites]未找到字幕下载目录")
            return

        # 站点流控
        if self.sites and self.sites.check_ratelimit(site_id):
            return

        engine = self._site_engine
        site_def = engine.get_by_url(media_info.page_url)
        rate_limiter = getattr(engine, "site_limiter", None)
        rate_limiter_engine = rate_limiter.engine if rate_limiter else None
        rl_kwargs = engine_tools._get_rate_limit_kwargs(engine, site_def)
        if site_def and site_def.subtitle:
            engine.resolve_subtitle(media_info.page_url, "", download_dir)
            return

        # 读取网站代码
        try:
            headers = {"User-Agent": ua} if ua else {}
            res = HttpClient(
                rate_limiter=rate_limiter_engine,
            ).get(media_info.page_url, headers=headers, auth=CookieAuth(cookie), **rl_kwargs)
            html = etree.HTML(res.text)
        except Exception:
            log.warn(f"[Sites]读取页面代码失败：{media_info.page_url}")
            return

        sublink_list = []
        for xpath in self.siteconf.get_subtitle_conf() if self.siteconf else []:
            sublinks = cast(list, html.xpath(xpath))
            if sublinks:
                for sublink in sublinks:
                    if not sublink:
                        continue
                    if not sublink.startswith("http"):
                        base_url = StringUtils.get_base_url(media_info.page_url)
                        if sublink.startswith("/"):
                            sublink = f"{base_url}{sublink}"
                        else:
                            sublink = f"{base_url}/{sublink}"
                    sublink_list.append(sublink)
        # 下载所有字幕文件
        for sublink in sublink_list:
            log.info(f"[Sites]找到字幕下载链接：{sublink}，开始下载...")
            try:
                ret = HttpClient(
                    rate_limiter=rate_limiter_engine,
                ).get(sublink, **rl_kwargs)
                # 创建目录
                if not os.path.exists(download_dir):
                    os.makedirs(download_dir)
                # 保存ZIP
                file_name = _get_url_subtitle_name(ret.headers.get("content-disposition"), sublink)
                if not file_name:
                    log.warn(f"[Sites]链接不是字幕文件：{sublink}")
                    continue
                if file_name.lower().endswith(".zip"):
                    # ZIP包
                    zip_file = os.path.join(self._save_tmp_path or "", file_name)
                    # 解压路径
                    zip_path = os.path.splitext(zip_file)[0]
                    with open(zip_file, "wb") as f:
                        f.write(ret.content)
                    # 解压文件
                    shutil.unpack_archive(zip_file, zip_path, format="zip")
                    # 遍历转移文件
                    for sub_file in PathUtils.get_dir_files(in_path=zip_path, exts=RMT_SUBEXT):
                        target_sub_file = os.path.join(download_dir, os.path.splitext(os.path.basename(sub_file))[0])
                        log.info(f"[Sites]转移字幕 {sub_file} 到 {target_sub_file}")
                        _transfer_subtitle(sub_file, target_sub_file)
                    # 删除临时文件
                    try:
                        shutil.rmtree(zip_path)
                        os.remove(zip_file)
                    except Exception as err:
                        ExceptionUtils.exception_traceback(err)
                else:
                    sub_file = os.path.join(self._save_tmp_path or "", file_name)
                    # 保存
                    with open(sub_file, "wb") as f:
                        f.write(ret.content)
                    target_sub_file = os.path.join(download_dir, os.path.splitext(os.path.basename(sub_file))[0])
                    log.info(f"[Sites]转移字幕 {sub_file} 到 {target_sub_file}")
                    _transfer_subtitle(sub_file, target_sub_file)
            except Exception:
                log.error(f"[Sites]下载字幕文件失败：{sublink}")
                continue
        if sublink_list:
            log.info(f"[Sites]{media_info.page_url} 页面字幕下载完成")
        else:
            log.warn(f"[Sites]{media_info.page_url} 页面未找到字幕下载链接")

    def _download_mteam_subtitle(self, media_info, site_id, cookie, ua, download_dir):
        """
        下载 m-team 站点字幕
        """
        log.info("[Sites]开始从 m-team 下载字幕")

        # 获取站点信息
        site_info = self.sites.get_sites(siteid=site_id) if self.sites else None
        if not site_info:
            log.warn(f"[Sites]无法获取站点 {site_id} 的信息")
            return

        if not isinstance(site_info, dict):
            log.warn(f"[Sites]站点信息格式错误，预期为 dict，实际为 {type(site_info)}")
            return

        # 从站点信息中获取 headers
        headers = site_info.get("headers")
        if headers and isinstance(headers, str):
            try:
                headers = JsonUtils.loads(headers)
            except Exception:
                headers = {}
        elif not headers:
            headers = {}

        # 添加必要的头信息
        headers.update(
            {
                "Content-Type": "application/json; charset=utf-8",
                "accept": "application/json, text/plain, */*",
            }
        )

        # 添加 User-Agent
        if isinstance(ua, str):
            headers["User-Agent"] = ua
        elif isinstance(ua, dict):
            headers.update(ua)

        # 从 page_url 提取 torrent id
        page_url = media_info.page_url
        torrent_id = None
        match = re.search(r"/detail/(\d+)", page_url)
        if match:
            torrent_id = match.group(1)
        else:
            # 尝试其他格式
            match = re.search(r"\d+", page_url)
            if match:
                torrent_id = match.group(0)

        if not torrent_id:
            log.warn(f"[Sites]无法从页面URL提取 torrent id: {page_url}")
            return

        # 获取字幕列表
        engine = self._site_engine
        site_def = engine.get_by_url(media_info.page_url) or engine.get_by_name("M-Team")
        api_base = ""
        if site_def and getattr(site_def, "api", None):
            api_base = site_def.api.base_url or ""
        api_base = api_base.rstrip("/") or "https://api.m-team.cc"
        subtitle_list_url = f"{api_base}/api/subtitle/list"
        rate_limiter = getattr(engine, "site_limiter", None)
        rate_limiter_engine = rate_limiter.engine if rate_limiter else None
        client = HttpClient(
            config=HttpClientConfig(default_headers=headers),
            rate_limiter=rate_limiter_engine,
        )
        try:
            res = client.post(url=subtitle_list_url, data=JsonUtils.dumps({"id": torrent_id}))
            data = res.json()
            if data.get("code") != "0" or data.get("message") != "SUCCESS":
                log.warn(f"[Sites]m-team 字幕列表返回错误：{data.get('message')}")
                return

            subtitles = data.get("data", [])
            if not subtitles:
                log.info(f"[Sites]m-team 种子 {torrent_id} 没有可用的字幕")
                return

            log.info(f"[Sites]找到 {len(subtitles)} 个字幕文件")

            # 创建下载目录
            if not os.path.exists(download_dir):
                os.makedirs(download_dir)

            # 下载每个字幕
            downloaded_count = 0
            for subtitle in subtitles:
                subtitle_id = subtitle.get("id")
                subtitle_name = subtitle.get("name", f"subtitle_{subtitle_id}")
                subtitle_ext = subtitle.get("ext", "srt")

                if not subtitle_id:
                    continue

                # 获取下载凭证
                genlink_url = f"{api_base}/api/subtitle/genlink"
                genlink_res = client.post(url=genlink_url, data=JsonUtils.dumps({"id": subtitle_id}))
                genlink_data = genlink_res.json()
                if genlink_data.get("code") != "0":
                    log.warn(f"[Sites]字幕 {subtitle_id} 下载链接返回错误：{genlink_data.get('message')}")
                    continue

                credential = genlink_data.get("data", "")
                if not credential:
                    log.warn(f"[Sites]字幕 {subtitle_id} 下载凭证为空")
                    continue

                # 下载字幕文件
                download_url = f"{api_base}/api/subtitle/dlV2?credential={credential}"
                download_res = client.get(url=download_url)

                # 保存字幕文件
                file_name = f"{subtitle_name}.{subtitle_ext}"
                # 清理文件名中的非法字符
                file_name = re.sub(r'[<>"/\\|?*]', "_", file_name)
                sub_file = os.path.join(self._save_tmp_path or "", file_name)

                with open(sub_file, "wb") as f:
                    f.write(download_res.content)

                # 转移字幕文件
                target_sub_file = os.path.join(download_dir, os.path.splitext(file_name)[0])
                log.info(f"[Sites]转移字幕 {sub_file} 到 {target_sub_file}")
                _transfer_subtitle(sub_file, target_sub_file)

                # 删除临时文件
                try:
                    os.remove(sub_file)
                except Exception as err:
                    ExceptionUtils.exception_traceback(err)

                downloaded_count += 1

            log.info(f"[Sites]m-team 字幕下载完成，共下载 {downloaded_count} 个字幕")

        except Exception as err:
            ExceptionUtils.exception_traceback(err)
            log.error(f"[Sites]处理 m-team 字幕时发生错误：{err!s}")
