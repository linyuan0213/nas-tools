"""
DownloadClientFactory - 下载器客户端工厂

职责：
- 下载器客户端类型注册与实例创建
- 下载器配置加载与管理
- 下载设置加载与管理
- 客户端实例缓存（线程安全）

移除 SingletonMeta，改为普通类 + 依赖注入。
"""

import os
from threading import Lock

import log
from app.core.constants import PT_TAG
from app.core.settings import settings
from app.core.system_config import SystemConfig as SystemConfigClass
from app.db.repositories.config_repo_adapter import DownloaderRepositoryAdapter
from app.db.repositories.download_repo_adapter import DownloadSettingRepositoryAdapter
from app.domain.enums import SystemConfigKey
from app.downloader.client._base import _IDownloadClient
from app.downloader.registry import get_all_clients, get_client_class
from app.utils import ExceptionUtils, NumberUtils, StringUtils, SystemUtils
from app.utils.json_utils import JsonUtils

client_lock = Lock()


class DownloadClientFactory:
    """
    下载器客户端工厂

    管理下载器 schema、配置、客户端实例缓存。
    """

    def __init__(self, config_repo=None, download_repo=None, systemconfig: SystemConfigClass | None = None):
        # 注入领域仓库适配器，不允许注入旧的 ConfigRepository/DownloadRepository
        self._config_repo = config_repo or DownloaderRepositoryAdapter()
        self._download_repo = download_repo or DownloadSettingRepositoryAdapter()
        self._systemconfig = systemconfig or SystemConfigClass()

        # 客户端实例缓存 {downloader_id: client_instance}
        self._clients = {}

        # 下载器配置 {downloader_id: conf_dict}
        self._downloader_confs = {}

        # 监控下载器ID列表
        self._monitor_downloader_ids = []

        # 下载设置 {setting_id: setting_dict}
        self._download_settings = {}

        # 全局下载顺序
        self._download_order = None

        # jobstore 标识
        self._jobstore = "download"

        self._refresh()

    # ---------- 配置加载 ----------

    def _refresh(self):
        """重新加载所有下载器配置和下载设置"""
        self._clients.clear()
        self._downloader_confs = {}
        self._monitor_downloader_ids = []

        for downloader_conf in self._config_repo.get_downloaders():
            if not downloader_conf:
                continue
            did = downloader_conf.ID
            name = downloader_conf.NAME
            enabled = downloader_conf.ENABLED
            transfer = downloader_conf.TRANSFER
            only_nexus_media = downloader_conf.ONLY_NEXUS_MEDIA
            match_path = downloader_conf.MATCH_PATH
            rmt_mode = str(downloader_conf.RMT_MODE or "")
            rmt_mode_name = rmt_mode

            if str(transfer or ""):
                log_content = ""
                if str(only_nexus_media or ""):
                    log_content += "启用标签隔离，"
                if str(match_path or ""):
                    log_content += "启用目录隔离，"
                log.info(f"[Downloader]读取到监控下载器：{name}{log_content}转移方式：{rmt_mode_name}")
                if int(str(enabled or 0)):
                    self._monitor_downloader_ids.append(did)
                else:
                    log.info(f"[Downloader]下载器：{name} 不进行监控：下载器未启用")

            config = JsonUtils.loads(str(downloader_conf.CONFIG))
            dtype = downloader_conf.TYPE
            download_dir_val = JsonUtils.loads(str(downloader_conf.DOWNLOAD_DIR))
            if not download_dir_val:
                download_dir_val = config.get("download_dir") or []
            self._downloader_confs[str(did)] = {
                "id": did,
                "name": name,
                "type": dtype,
                "enabled": enabled,
                "transfer": transfer,
                "only_nexus_media": only_nexus_media,
                "match_path": match_path,
                "rmt_mode": rmt_mode,
                "rmt_mode_name": rmt_mode_name,
                "config": config,
                "download_dir": download_dir_val,
            }

        # 下载顺序
        pt = settings.get("pt")
        if pt:
            self._download_order = pt.get("download_order")

        # 下载设置
        self._download_settings = {
            "-1": {
                "id": -1,
                "name": "预设",
                "category": "",
                "tags": PT_TAG,
                "is_paused": 0,
                "upload_limit": 0,
                "download_limit": 0,
                "ratio_limit": 0,
                "seeding_time_limit": 0,
                "downloader": "",
                "downloader_name": "",
                "downloader_type": "",
            }
        }
        download_settings = self._download_repo.get_download_setting()
        for download_setting in download_settings:
            downloader_id = download_setting.DOWNLOADER
            download_conf = self._downloader_confs.get(str(downloader_id))
            if download_conf:
                downloader_name = download_conf.get("name")
                downloader_type = download_conf.get("type")
            else:
                downloader_name = ""
                downloader_type = ""
                downloader_id = ""
            self._download_settings[str(download_setting.ID)] = {
                "id": download_setting.ID,
                "name": download_setting.NAME,
                "category": download_setting.CATEGORY,
                "tags": download_setting.TAGS,
                "is_paused": download_setting.IS_PAUSED,
                "upload_limit": download_setting.UPLOAD_LIMIT,
                "download_limit": download_setting.DOWNLOAD_LIMIT,
                "ratio_limit": download_setting.RATIO_LIMIT / 100,
                "seeding_time_limit": download_setting.SEEDING_TIME_LIMIT,
                "downloader": downloader_id,
                "downloader_name": downloader_name,
                "downloader_type": downloader_type,
            }

    # ---------- 客户端构建 ----------

    @staticmethod
    def _build_class(ctype, conf=None):
        """根据类型名构建客户端类实例"""
        for cls in get_all_clients():
            try:
                if cls.match(ctype):
                    return cls(conf)
            except Exception as e:
                ExceptionUtils.exception_traceback(e)
        return None

    def get_client(self, did=None) -> _IDownloadClient | None:
        """获取（或创建）下载器客户端实例"""
        if not did:
            return None
        downloader_conf = self.get_downloader_conf(did)
        if not downloader_conf:
            log.info("[Downloader]下载器配置不存在")
            return None
        if not downloader_conf.get("enabled"):
            log.info(f"[Downloader]下载器 {downloader_conf.get('name')} 未启用")
            return None
        ctype = downloader_conf.get("type")
        config = downloader_conf.get("config") or {}
        config["download_dir"] = downloader_conf.get("download_dir")
        config["name"] = downloader_conf.get("name")
        with client_lock:
            if not self._clients.get(str(did)):
                self._clients[str(did)] = self._build_class(ctype, config)
            return self._clients.get(str(did))

    def get_client_type(self, downloader_id=None):
        """获取下载器的类型枚举"""
        if not downloader_id:
            return self.default_client.get_type() if self.default_client else None
        client = self.get_client(downloader_id)
        return client.get_type() if client else None

    @property
    def default_downloader_id(self):
        """获取默认下载器id"""
        default_downloader_id = self._systemconfig.get(SystemConfigKey.DefaultDownloader)
        if not default_downloader_id or not self.get_downloader_conf(default_downloader_id):
            default_downloader_id = ""
        return default_downloader_id

    def set_default_downloader(self, did: str) -> bool:
        """设置默认下载器id"""
        if not did or not self.get_downloader_conf(did):
            return False
        self._systemconfig.set(SystemConfigKey.DefaultDownloader, did)
        return True

    @property
    def default_download_setting_id(self):
        """获取默认下载设置id"""
        default_download_setting_id = self._systemconfig.get(SystemConfigKey.DefaultDownloadSetting) or "-1"
        if not self._download_settings.get(str(default_download_setting_id)):
            default_download_setting_id = "-1"
        return default_download_setting_id

    def set_default_download_setting(self, sid: str) -> bool:
        """设置默认下载设置id"""
        if sid != "-1" and not self._download_settings.get(sid):
            return False
        self._systemconfig.set(SystemConfigKey.DefaultDownloadSetting, sid)
        return True

    @property
    def default_client(self):
        """获取默认下载器实例"""
        return self.get_client(self.default_downloader_id)

    @property
    def monitor_downloader_ids(self):
        """获取监控下载器ID列表"""
        return self._monitor_downloader_ids

    @property
    def jobstore(self):
        return self._jobstore

    @property
    def download_order(self):
        return self._download_order

    # ---------- 配置查询 ----------

    def get_downloader_conf(self, did=None):
        """获取下载器配置，返回数据中包含 is_default 标记"""
        default_id = self._systemconfig.get(SystemConfigKey.DefaultDownloader)
        if not did:
            result = {}
            for k, v in self._downloader_confs.items():
                item = dict(v)
                item["is_default"] = str(item.get("id")) == str(default_id)
                result[k] = item
            return result
        conf = self._downloader_confs.get(str(did))
        if conf:
            conf = dict(conf)
            conf["is_default"] = str(conf.get("id")) == str(default_id)
        return conf

    def get_downloader_conf_simple(self, brush: bool = False):
        """获取简化下载器配置；brush=True 时仅返回支持 PT（可用于刷流）的下载器"""
        ret_dict = {}
        for downloader_conf in (self.get_downloader_conf() or {}).values():
            if brush and not self._supports_brush(downloader_conf.get("type")):
                continue
            ret_dict[str(downloader_conf.get("id"))] = {
                "id": downloader_conf.get("id"),
                "name": downloader_conf.get("name"),
                "type": downloader_conf.get("type"),
                "enabled": downloader_conf.get("enabled"),
            }
        return ret_dict

    @staticmethod
    def _supports_brush(ctype) -> bool:
        """下载器是否支持刷流（刷流针对 PT 站，复用 supports_pt 标志）"""
        if not ctype:
            return False
        cls = get_client_class(ctype)
        return bool(getattr(cls, "supports_pt", True)) if cls else False

    def get_download_setting(self, sid=None):
        """获取下载设置，返回数据中包含 is_default 标记"""
        preset_downloader_conf = self.get_downloader_conf(self.default_downloader_id)
        if preset_downloader_conf:
            self._download_settings["-1"]["downloader"] = self.default_downloader_id
            self._download_settings["-1"]["downloader_name"] = preset_downloader_conf.get("name")
            self._download_settings["-1"]["downloader_type"] = preset_downloader_conf.get("type")
        default_sid = self.default_download_setting_id
        if not sid:
            result = {}
            for k, v in self._download_settings.items():
                item = dict(v)
                item["is_default"] = str(k) == str(default_sid)
                result[k] = item
            return result
        conf = self._download_settings.get(str(sid)) or {}
        if conf:
            conf = dict(conf)
            conf["is_default"] = str(sid) == str(default_sid)
        return conf

    def get_download_dirs(self, setting=None):
        """返回下载器中设置的保存目录"""
        if not setting:
            setting = self.default_download_setting_id
        download_setting = self.get_download_setting(sid=setting)
        downloader_conf = self.get_downloader_conf(download_setting.get("downloader"))
        if not downloader_conf:
            return []
        downloaddir = downloader_conf.get("download_dir") or []
        save_path_list = [attr.get("save_path") for attr in downloaddir if attr.get("save_path")]
        save_path_list.sort()
        return list(set(save_path_list))

    def get_download_visit_dirs(self):
        """返回所有下载器中设置的访问目录"""
        download_dirs = []
        for downloader_conf in (self.get_downloader_conf() or {}).values():
            download_dirs += downloader_conf.get("download_dir")
        visit_path_list = [
            attr.get("container_path") or attr.get("save_path") for attr in download_dirs if attr.get("save_path")
        ]
        visit_path_list.sort()
        return list(set(visit_path_list))

    def get_download_visit_dir(self, download_dir, downloader_id=None):
        """返回下载器中设置的访问目录"""
        if not downloader_id:
            downloader_id = self.default_downloader_id
        downloader_conf = self.get_downloader_conf(downloader_id)
        client = self.get_client(downloader_id)
        if not client:
            return ""
        if not downloader_conf:
            return ""
        true_path, _ = client.get_replace_path(download_dir, downloader_conf.get("download_dir"))
        return true_path

    def get_status(self, dtype=None, config=None):
        """测试下载器状态"""
        if not config or not dtype:
            return False
        client = self._build_class(ctype=dtype, conf=config)
        if not client:
            return False
        state = client.get_status()
        if not state:
            log.error("[Downloader]下载器连接测试失败")
        return state

    def get_remote_dirs(self, dtype=None, config=None) -> list[str]:
        """通过下载器 API 读取其已知目录候选列表（临时客户端）"""
        if not dtype or not config:
            return []
        client = self._build_class(ctype=dtype, conf=config)
        if not client:
            return []
        return client.list_remote_dirs()

    def get_free_space(self, downloader_id, path: str):
        """获取磁盘剩余空间"""
        if not downloader_id:
            downloader_id = self.default_downloader_id
        client = self.get_client(downloader_id)
        if not client:
            return None
        return client.get_free_space(path)

    @staticmethod
    def get_download_dir_info(media, downloaddir):
        """根据媒体信息读取一个下载目录的信息；多个匹配目录按剩余空间均衡选择"""
        if media.type:
            candidates = []
            for attr in downloaddir or []:
                if not attr or not isinstance(attr, dict):
                    continue
                if attr.get("type") and attr.get("type") not in (media.type.value, media.type.display_name):
                    continue
                if attr.get("category") and media.category and attr.get("category") != media.category:
                    continue
                if not attr.get("save_path") and not attr.get("label"):
                    continue
                path = attr.get("container_path") or attr.get("save_path")
                if path and os.path.exists(path) and media.size:
                    try:
                        if SystemUtils.get_free_space(path) < NumberUtils.get_size_gb(
                            StringUtils.num_filesize(media.size)
                        ):
                            continue
                    except Exception as e:  # noqa: BLE001
                        log.debug(f"[Downloader]剩余空间检查失败: {e}")
                candidates.append(attr)
            if candidates:
                if len(candidates) > 1:

                    def _free(attr) -> float:
                        p = attr.get("container_path") or attr.get("save_path")
                        try:
                            if not p or not os.path.exists(p):
                                return 0
                            return SystemUtils.get_free_space(p) or 0
                        except Exception as e:  # noqa: BLE001
                            log.debug(f"[Downloader]剩余空间检查失败: {e}")
                            return 0

                    best = max(candidates, key=_free)
                    return {"path": best.get("save_path"), "category": best.get("category"), "label": best.get("label")}
                c = candidates[0]
                return {"path": c.get("save_path"), "category": c.get("category"), "label": c.get("label")}
        return {"path": None, "category": None, "label": None}
