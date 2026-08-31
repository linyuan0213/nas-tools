from app.downloader.registry import register

from .qbittorrent import Qbittorrent
from .transmission import Transmission


def init_clients() -> None:
    """注册内置下载器（核心保留 qbittorrent/transmission，xunlei/aria2 已插件化）"""
    register(Qbittorrent)
    register(Transmission)
