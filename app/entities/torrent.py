from dataclasses import dataclass, field
from typing import List

from app.entities.torrentstatus import TorrentStatus

@dataclass
class Torrent:
    id: str = None                                      # 种子id
    name: str = None                                    # 种子名称
    size: int = 0                                       # 种子大小
    downloaded: int = 0                                 # 下载量
    uploaded: int = 0                                   # 上传量
    ratio: float = 0                                    # 分享率
    add_time: str = None                                # 种子添加时间
    seeding_time: int = 0                               # 做种时间
    download_time: int = 0                              # 下载时间
    avg_upload_speed: float = 0                         # 平均上传速度
    iatime: int = 0                                     # 未活跃时间
    labels: List[str] = field(default_factory=list)     # 种子标签
    status: TorrentStatus = None                        # 种子状态
    save_path: str = None                               # 保存路径
    content_path: str = None                            # 文件完整路径
    trackers: List[str] = field(default_factory=list)   # 种子tracker
    category: List[str] = field(default_factory=list)   # 种子分类
    progress: float = 0                                 # 种子进度
    download_speed: int = 0                             # 下载速度
    upload_speed: int = 0                               # 上传速度
    eta: int = 0                                        # eta
    