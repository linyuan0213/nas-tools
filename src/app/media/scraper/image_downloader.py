"""刮削器 — 图片与 NFO 文件下载/保存"""

import io
import mimetypes
import os
import threading

import log
from app.infrastructure.http import HttpClientError
from app.infrastructure.http.client import HttpClient
from app.infrastructure.http.config import HttpClientConfig
from app.storage.backends.base import StorageBackend
from app.utils import ExceptionUtils
from app.utils.commons import retry
from app.utils.config_tools import get_proxies

# 全局图片下载并发上限：转移异步刮削/整库刮削并发时避免图片 CDN 请求突发
_IMAGE_DOWNLOAD_SEMAPHORE = threading.Semaphore(4)


def _proxy_url_from_settings() -> str | None:
    """图片多来自 TMDB/Fanart/Bangumi 等境外源，需按配置走代理。"""
    proxies = get_proxies() or {}
    if isinstance(proxies, dict):
        return proxies.get("http") or proxies.get("https")
    return None


_CONTENT_TYPE_EXT_MAP = {
    "image/jpeg": ".jpg",
    "image/png": ".png",
    "image/webp": ".webp",
    "image/gif": ".gif",
    "image/bmp": ".bmp",
    "image/tiff": ".tiff",
    "image/svg+xml": ".svg",
}


class ImageDownloader:
    """图片下载器 — 负责从 URL 下载图片并保存到本地或远程"""

    def __init__(self, temp_path: str, dst_backend: StorageBackend | None = None):
        self._temp_path = temp_path
        self._dst_backend = dst_backend

    def set_dst_backend(self, dst_backend: StorageBackend | None):
        self._dst_backend = dst_backend

    @retry(HttpClientError, logger=log)
    def download(self, url, out_path, itype="", force=False):
        """下载图片并保存"""
        if not url or not out_path:
            return
        if itype:
            ext = self._guess_extension(url)
            image_path = os.path.join(out_path, f"{itype}{ext}")
        else:
            image_path = out_path
        if not force and os.path.exists(image_path):
            return
        try:
            log.info(f"[Scraper]正在下载{itype}图片：{url} ...")
            with _IMAGE_DOWNLOAD_SEMAPHORE:
                r = HttpClient(config=HttpClientConfig(proxy_url=_proxy_url_from_settings())).get(
                    url=url, raise_exception=True
                )
            if r:
                resolved_path = self._resolve_extension(image_path, r.headers.get("content-type", ""))
                if self._dst_backend:
                    self._dst_backend.write_stream(resolved_path, io.BytesIO(r.content), len(r.content))
                else:
                    with open(file=resolved_path, mode="wb") as img:
                        img.write(r.content)
                log.info(f"[Scraper]{itype}图片已保存：{resolved_path}")
            else:
                log.info(f"[Scraper]{itype}图片下载失败，请检查网络连通性")
        except HttpClientError as ex:
            raise HttpClientError(str(ex)) from ex
        except Exception as err:
            log.error(f"[Scraper]下载{itype}图片失败：{image_path}，错误：{err}")
            ExceptionUtils.exception_traceback(err)

    @staticmethod
    def _guess_extension(url: str) -> str:
        url_path = str(url).split("?")[0]
        _, ext = os.path.splitext(url_path)
        if ext and len(ext) <= 5 and ext.isascii():
            return ext.lower()
        return ".jpg"

    @staticmethod
    def _resolve_extension(image_path: str, content_type: str) -> str:
        ct = content_type.split(";")[0].strip().lower()
        mapped = _CONTENT_TYPE_EXT_MAP.get(ct)
        if mapped:
            base, _ = os.path.splitext(image_path)
            return base + mapped
        if ct.startswith("image/"):
            guessed = mimetypes.guess_extension(ct)
            if guessed:
                base, _ = os.path.splitext(image_path)
                return base + guessed
        return image_path

    def save_nfo(self, doc, out_file):
        """保存 NFO XML 文件"""
        log.info(f"[Scraper]正在保存NFO文件：{out_file}")
        try:
            xml_str = doc.toprettyxml(indent="  ", encoding="utf-8")
            if self._dst_backend:
                self._dst_backend.write_stream(out_file, io.BytesIO(xml_str), len(xml_str))
            else:
                with open(out_file, "wb") as xml_file:
                    xml_file.write(xml_str)
            log.info(f"[Scraper]NFO文件已保存：{out_file}")
        except Exception as err:
            log.error(f"[Scraper]保存NFO文件失败：{out_file}，错误：{err}")
            ExceptionUtils.exception_traceback(err)
