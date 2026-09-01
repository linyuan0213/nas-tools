import re
import urllib.parse

import log
from app.core.constants import TMDB_IMAGE_DOMAIN, TMDB_IMAGE_SIZE


class ImageProxy:
    """
    图片代理 URL 生成助手
    纯逻辑类，无单例，不持有 Config 状态。
    """

    @staticmethod
    def get_tmdbimage_url(path, prefix="w500", size=None, use_proxy=False, tmdb_image_url=None):
        """
        获取 TMDB 图片 URL
        :param path: 图片路径
        :param prefix: 尺寸前缀（默认 w500，兼容旧代码）
        :param size: 尺寸名称（thumb/small/medium/large/xlarge/original），优先级高于 prefix
        :param use_proxy: 是否使用本地代理
        :param tmdb_image_url: 自定义 TMDB 图片域名
        :return: 完整图片 URL
        """
        if not path:
            return ""

        # 如果指定了 size，使用对应的尺寸
        if size and size in TMDB_IMAGE_SIZE:
            prefix = TMDB_IMAGE_SIZE[size]

        # 如果使用代理，返回本地代理 URL
        if use_proxy:
            path_clean = path.lstrip("/")
            return f"/img/tmdb/{prefix}/{path_clean}"

        if tmdb_image_url:
            return tmdb_image_url + f"/t/p/{prefix}{path}"
        return f"https://{TMDB_IMAGE_DOMAIN}/t/p/{prefix}{path}"

    @staticmethod
    def get_tmdbimage_thumb_url(path, use_proxy=False):
        """获取缩略图 URL (w92)"""
        return ImageProxy.get_tmdbimage_url(path, size="thumb", use_proxy=use_proxy)

    @staticmethod
    def get_tmdbimage_small_url(path, use_proxy=False):
        """获取小图 URL (w185) - 适合列表"""
        return ImageProxy.get_tmdbimage_url(path, size="small", use_proxy=use_proxy)

    @staticmethod
    def get_tmdbimage_medium_url(path, use_proxy=False):
        """获取中图 URL (w342) - 适合卡片"""
        return ImageProxy.get_tmdbimage_url(path, size="medium", use_proxy=use_proxy)

    @staticmethod
    def get_tmdbimage_large_url(path, use_proxy=False):
        """获取大图 URL (w500) - 适合详情页"""
        return ImageProxy.get_tmdbimage_url(path, size="large", use_proxy=use_proxy)

    @staticmethod
    def get_image_proxy_enabled(app_config):
        """检查是否启用了图片代理 - 默认开启"""
        if app_config is None:
            return True
        return app_config.get("enable_image_proxy", True)

    @staticmethod
    def get_proxy_image_url(url, use_proxy=True):
        """
        将任意图片 URL 转换为本地代理 URL
        支持 TMDB、豆瓣、Bangumi 等图片
        :param url: 原始图片 URL
        :param use_proxy: 是否启用代理
        :return: 代理后的图片 URL
        """
        if not url:
            return ""

        # 如果未启用图片代理，直接返回原 URL
        if not use_proxy:
            return url

        # 已经是本地代理路径，直接返回
        if url.startswith("/img/"):
            return url

        try:
            # 处理 TMDB 图片
            if "image.tmdb.org" in url:
                match = re.search(r"/t/p/(\w+)(/.+)", url)
                if match:
                    size = match.group(1)
                    path = match.group(2).lstrip("/")
                    return f"/img/tmdb/{size}/{path}"
                return url

            # 处理豆瓣图片
            if "doubanio.com" in url or "douban.com" in url:
                encoded_path = urllib.parse.quote(url, safe="")
                return f"/img/douban/{encoded_path}"

            # 处理 Bangumi 图片
            if "lain.bgm.tv" in url:
                encoded_path = urllib.parse.quote(url, safe="")
                return f"/img/bgm/{encoded_path}"

            # 其他外部图片统一走 library 代理
            if url.startswith("http"):
                encoded_path = urllib.parse.quote(url, safe="")
                return f"/img/library/{encoded_path}"

        except Exception as e:
            log.error(f"[ImageProxy]处理图片代理失败: {str(e)}")

        return url
