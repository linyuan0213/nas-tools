import base64
import hashlib
import os
import re
import time
from typing import Any, cast

import qbittorrentapi
from bencode import bdecode, bencode

import log
from app.core.exceptions import InfrastructureError, NetworkError
from app.downloader.client._base import _IDownloadClient
from app.downloader.schema import ConfigField, DownloaderConfigSchema
from app.downloader.strategy import RemoveStrategy
from app.infrastructure.cache_system.decorators import cached
from app.schemas.download import Torrent, TorrentStatus
from app.utils import ExceptionUtils


class Qbittorrent(_IDownloadClient):
    client_id = "qbittorrent"
    client_type = "qbittorrent"
    client_name = "Qbittorrent"

    config_schema = DownloaderConfigSchema(
        name="Qbittorrent",
        monitor_enable=True,
        speedlimit_enable=True,
        fields=[
            ConfigField(id="host", required=True, title="地址", type="text", placeholder="127.0.0.1"),
            ConfigField(id="port", required=True, title="端口", type="text", placeholder="8080"),
            ConfigField(id="username", required=True, title="用户名", type="text", placeholder="admin"),
            ConfigField(id="password", required=False, title="密码", type="password", placeholder="password"),
            ConfigField(
                id="torrent_management",
                required=False,
                title="种子管理模式",
                type="select",
                options={"default": "默认", "manual": "手动", "auto": "自动"},
                default="default",
            ),
        ],
    )

    _client_config = {}
    _torrent_management = False

    qbc = None
    ver = None
    host = None
    port = None
    username = None
    password = None
    download_dir = []
    name = "测试"
    _sync_rid: int = 0
    _sync_torrents: dict[str, dict] = {}
    _completed_states = {
        "uploading",
        "stalledUP",
        "queuedUP",
        "pausedUP",
        "stoppedUP",
        "forcedUP",
        "checkingUP",
    }

    def __init__(self, config: dict):
        self._client_config = config
        self._sync_rid = 0
        self._sync_torrents = {}
        self.init_config()
        self.connect()
        self.init_torrent_management()
        if self.qbc:
            self.qbc.app_set_preferences({"incomplete_files_ext": True})

    def init_config(self) -> None:
        if self._client_config:
            self.host = self._client_config.get("host")
            self.port = (
                int(self._client_config.get("port") or 0) if str(self._client_config.get("port") or "").isdigit() else 0
            )
            self.username = self._client_config.get("username")
            self.password = self._client_config.get("password")
            self.download_dir = self._client_config.get("download_dir") or []
            self.name = self._client_config.get("name") or ""
            self._torrent_management = self._client_config.get("torrent_management")
            if self._torrent_management not in ["default", "manual", "auto"]:
                self._torrent_management = "default"

    @classmethod
    def match(cls, ctype: str) -> Any:
        return ctype in [cls.client_id, cls.client_type, cls.client_name]

    def get_type(self) -> Any:
        return self.client_type

    def connect(self) -> Any:
        if self.host and self.port:
            self.qbc = self.__login_qbittorrent()

    def __login_qbittorrent(self):
        try:
            qbt = qbittorrentapi.Client(
                host=self.host or "",
                port=self.port,
                username=self.username,
                password=self.password,
                VERIFY_WEBUI_CERTIFICATE=False,
                REQUESTS_ARGS={"timeout": (15, 60)},
            )
            try:
                qbt.auth_log_in()
                self.ver = qbt.app_version()
            except qbittorrentapi.LoginFailed as e:
                log.error(f"[{self.client_name}]{self.name} 登录失败：{e}")
            return qbt
        except (InfrastructureError, NetworkError):
            raise
        except Exception as err:
            ExceptionUtils.exception_traceback(err)
            log.error(f"[{self.client_name}]{self.name} 连接出错：{err!s}")
            return None

    def get_status(self) -> Any:
        if not self.qbc:
            return False
        try:
            return bool(self.qbc.transfer_info())
        except (InfrastructureError, NetworkError):
            raise
        except Exception as err:
            ExceptionUtils.exception_traceback(err)
            return False

    def init_torrent_management(self):
        if self._torrent_management == "manual":
            return
        if self._torrent_management == "default" and not self.__get_qb_auto():
            return
        categories = self.__get_qb_category()
        for dir_item in self.download_dir:
            label = dir_item.get("label")
            save_path = dir_item.get("save_path")
            if not label or not save_path:
                continue
            category_item: Any = categories.get(label)
            if not category_item:
                self.__update_category(name=label, save_path=save_path)
            else:
                if os.path.normpath(str(category_item.get("savePath") or "")) != os.path.normpath(save_path):
                    self.__update_category(name=label, save_path=save_path, is_edit=True)

    def __get_qb_category(self):
        if not self.qbc:
            return {}
        return self.qbc.torrent_categories.categories or {}

    def __get_qb_auto(self):
        if not self.qbc:
            return {}
        preferences = self.qbc.app_preferences() or {}
        return preferences.get("auto_tmm_enabled")

    def __update_category(self, name, save_path, is_edit=False):
        if not self.qbc:
            return
        try:
            if is_edit:
                self.qbc.torrent_categories.edit_category(name=name, save_path=save_path)
                log.info(f"[{self.client_name}]{self.name} 更新分类：{name}，路径：{save_path}")
            else:
                self.qbc.torrent_categories.create_category(name=name, save_path=save_path)
                log.info(f"[{self.client_name}]{self.name} 创建分类：{name}，路径：{save_path}")
        except (InfrastructureError, NetworkError):
            raise
        except Exception as err:
            ExceptionUtils.exception_traceback(err)
            log.error(f"[{self.client_name}]{self.name} 设置分类：{name}，路径：{save_path} 错误：{err!s}")

    def __check_category(self, save_path=""):
        if not save_path:
            return None
        categories = self.__get_qb_category()
        for category_name, category_item in categories.items():
            category_item: Any = category_item
            if not category_item:
                continue
            catetory_path: Any = category_item.get("savePath")
            if not catetory_path:
                continue
            if os.path.normpath(str(catetory_path)) == os.path.normpath(save_path):
                return category_name
        return None

    def get_torrents(
        self,
        ids: list[str] | str | None = None,
        status: list[TorrentStatus] | str | None = None,
        tag: str | list[str] | None = None,
    ) -> tuple[list[Torrent], bool]:
        if not self.qbc:
            return [], True
        try:
            if ids is None and status == "completed":
                return self._get_torrents_sync(status=status, tag=tag)

            status_filter = cast(Any, status) if isinstance(status, str) else None
            torrents = self.qbc.torrents_info(torrent_hashes=ids, status_filter=status_filter)
            torrent_list: list[Torrent] = []
            for torrent in torrents:
                try:
                    torrent_list.append(self.torrent_properties(torrent=torrent))
                except (InfrastructureError, NetworkError):
                    raise
                except Exception:
                    log.warn(f"[Qbittorrent]获取种子 {torrent.get('hash', '')} 属性失败，跳过")
            if status and isinstance(status, list):
                filtered_list: list[Torrent] = []
                for torrent in torrent_list:
                    if torrent.status in status:
                        filtered_list.append(torrent)
                torrent_list = filtered_list
            if tag:
                results: list[Torrent] = []
                if not isinstance(tag, list):
                    tag = [tag]
                for torrent in torrent_list:
                    include_flag = True
                    for t in tag:
                        if t and t not in torrent.labels:
                            include_flag = False
                            break
                    if include_flag:
                        results.append(torrent)
                return results or [], False
            return torrent_list or [], False
        except (InfrastructureError, NetworkError):
            raise
        except Exception as err:
            ExceptionUtils.exception_traceback(err)
            return [], True

    def _get_torrents_sync(
        self,
        status: list[TorrentStatus] | str | None = None,
        tag: str | list[str] | None = None,
    ) -> tuple[list[Torrent], bool]:
        """使用 qBittorrent sync/maindata 增量接口获取已完成任务，减少数据传输。"""
        if not self.qbc:
            return [], True
        try:
            sync_data: Any = self.qbc.sync_maindata(rid=self._sync_rid)
            self._sync_rid = int(sync_data.get("rid") or self._sync_rid)

            if sync_data.get("full_update"):
                self._sync_torrents = {}

            torrents_data: dict[str, Any] = sync_data.get("torrents") or {}
            for t_hash, t_data in torrents_data.items():
                self._sync_torrents[t_hash] = {**(self._sync_torrents.get(t_hash) or {}), **t_data}
            for removed in sync_data.get("torrents_removed") or []:
                self._sync_torrents.pop(str(removed), None)

            tags_set = set(tag) if isinstance(tag, list) else {tag} if tag else None
            torrent_list: list[Torrent] = []
            for t_hash, t_data in self._sync_torrents.items():
                state = str(t_data.get("state") or "")
                if state not in self._completed_states:
                    continue
                if tags_set:
                    labels = {s.strip() for s in (t_data.get("tags") or "").split(",")}
                    if not tags_set.intersection(labels):
                        continue
                torrent_list.append(self._torrent_from_sync(t_hash, t_data))
            # sync 数据无 up_speed_avg：从 properties API 补准确的平均上传速度（带缓存）
            for torrent in torrent_list:
                torrent.avg_upload_speed = self._get_torrent_avg_upload_speed(torrent.id)
            return torrent_list or [], False
        except (InfrastructureError, NetworkError):
            raise
        except Exception as err:
            ExceptionUtils.exception_traceback(err)
            # 回退到全量接口
            self._sync_rid = 0
            self._sync_torrents = {}
            return self._fallback_get_torrents(status=status, tag=tag)

    def _fallback_get_torrents(
        self,
        status: list[TorrentStatus] | str | None = None,
        tag: str | list[str] | None = None,
    ) -> tuple[list[Torrent], bool]:
        """sync/maindata 失败时回退到 torrents_info 全量接口。"""
        if not self.qbc:
            return [], True
        status_filter = cast(Any, status) if isinstance(status, str) else None
        torrents = self.qbc.torrents_info(status_filter=status_filter)
        torrent_list: list[Torrent] = []
        for torrent in torrents:
            torrent_list.append(self.torrent_properties(torrent=torrent))
        if tag:
            results: list[Torrent] = []
            if not isinstance(tag, list):
                tag = [tag]
            for torrent in torrent_list:
                include_flag = True
                for t in tag:
                    if t and t not in torrent.labels:
                        include_flag = False
                        break
                if include_flag:
                    results.append(torrent)
            return results or [], False
        return torrent_list or [], False

    def _torrent_from_sync(self, t_hash: str, t_data: dict) -> Torrent:
        """从 sync/maindata 数据构造 Torrent（填充刷流/规则所需字段，避免额外 API 调用）."""
        date_now = int(time.time())
        torrent_obj = Torrent()
        torrent_obj.id = t_hash
        torrent_obj.name = t_data.get("name")
        torrent_obj.size = int(t_data.get("total_size") or 0)
        torrent_obj.status = self._map_status(str(t_data.get("state") or ""))
        torrent_obj.labels = [s.strip() for s in (t_data.get("tags") or "").split(",") if s.strip()]
        torrent_obj.content_path = t_data.get("content_path")
        torrent_obj.save_path = t_data.get("save_path")
        torrent_obj.progress = float(t_data.get("progress") or 0)
        torrent_obj.download_speed = int(t_data.get("dlspeed") or 0)
        torrent_obj.upload_speed = int(t_data.get("upspeed") or 0)
        added_on = t_data.get("added_on") or 0
        torrent_obj.download_time = date_now - added_on if added_on else 0
        completion_on = t_data.get("completion_on") or 0
        torrent_obj.seeding_time = date_now - completion_on if completion_on > 0 else 0
        torrent_obj.ratio = t_data.get("ratio") or 0
        torrent_obj.uploaded = t_data.get("uploaded") or 0
        torrent_obj.downloaded = int(t_data.get("downloaded") or 0)
        torrent_obj.add_time = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(added_on)) if added_on else ""
        last_activity = t_data.get("last_activity") or 0
        torrent_obj.iatime = date_now - last_activity if last_activity else 0
        return torrent_obj

    def get_completed_torrents(
        self, ids: list[str] | str | None = None, tag: str | list[str] | None = None
    ) -> list[Torrent] | None:
        if not self.qbc:
            return None
        torrents, error = self.get_torrents(status="completed", ids=ids, tag=tag)
        return None if error else torrents or []

    def get_downloading_torrents(
        self, ids: list[str] | str | None = None, tag: str | list[str] | None = None
    ) -> list[Torrent] | None:
        if not self.qbc:
            return None
        statuses = [
            TorrentStatus.Downloading,
            TorrentStatus.Paused,
            TorrentStatus.Queued,
            TorrentStatus.Checking,
            TorrentStatus.Pending,
        ]
        torrents, error = self.get_torrents(ids=ids, status=statuses, tag=tag)
        # 排除已完成任务（pausedUP/stoppedUP 等会被映射为 Paused），只统计真正下载中的
        torrents = [t for t in torrents if t.progress < 1.0]
        return None if error else torrents or []

    def remove_torrents_tag(self, ids: list[str] | str, tag: str) -> bool:
        if not self.qbc:
            return False
        try:
            self.qbc.torrents_delete_tags(torrent_hashes=ids, tags=tag)
            return True
        except (InfrastructureError, NetworkError):
            raise
        except Exception as err:
            ExceptionUtils.exception_traceback(err)
            return False

    def set_torrents_status(self, ids: list[str] | str | None = None, tags: str | list[str] | None = None) -> bool:
        if not self.qbc:
            return False
        try:
            self.qbc.torrents_add_tags(tags="已整理", torrent_hashes=ids)
            return True
        except (InfrastructureError, NetworkError):
            raise
        except Exception as err:
            ExceptionUtils.exception_traceback(err)
            return False

    def set_torrents_tag(self, ids: list[str] | str | None = None, tags: str | list[str] | None = None) -> bool:
        if not self.qbc:
            return False
        try:
            torrents, error_flag = self.get_torrents(ids=ids)
            if error_flag:
                return False
            for torrent in torrents:
                old_tags = torrent.labels
                self.qbc.torrents_remove_tags(old_tags, torrent_hashes=ids)
                self.qbc.torrents_add_tags(tags, torrent_hashes=ids)
            return True
        except (InfrastructureError, NetworkError):
            raise
        except Exception as err:
            ExceptionUtils.exception_traceback(err)
            return False

    def torrents_set_force_start(self, ids: list[str] | str) -> None:
        if not self.qbc:
            return
        try:
            self.qbc.torrents_set_force_start(enable=True, torrent_hashes=ids)
        except (InfrastructureError, NetworkError):
            raise
        except Exception as err:
            ExceptionUtils.exception_traceback(err)

    def _get_content_subpath(self, torrent: Torrent) -> str | None:
        content_path = torrent.content_path
        if not content_path:
            return None
        save_path = torrent.save_path or ""
        subpath = content_path.replace(save_path, "").replace("\\", "/")
        subpath = subpath.removeprefix("/")
        return subpath

    def _check_extra_remove_conditions(self, torrent: Torrent, strategy: RemoveStrategy) -> bool:
        if strategy.filter_status and torrent.status and torrent.status not in strategy.filter_status:
            return False
        return True

    def __get_last_add_torrentid_by_tag(self, tag, status=None):
        try:
            torrents, _ = self.get_torrents(status=status, tag=tag)
        except (InfrastructureError, NetworkError):
            raise
        except Exception as err:
            ExceptionUtils.exception_traceback(err)
            return None
        if torrents:
            return torrents[0].id
        else:
            return None

    @staticmethod
    def calculate_torrent_hash(content: str | bytes | None) -> str | None:
        if not content:
            return None
        if isinstance(content, str) and content.startswith("magnet:"):
            # 40 位十六进制 infohash（v1）
            match = re.search(r"xt=urn:btih:([a-fA-F0-9]{40})", content)
            if match:
                return match.group(1).lower()
            # 32 位 base32 infohash（部分站点磁力使用，如 ACG/动漫站）
            match32 = re.search(r"xt=urn:btih:([A-Za-z2-7]{32})", content)
            if match32:
                try:
                    return base64.b32decode(match32.group(1).upper()).hex().lower()
                except Exception as err:
                    log.debug(f"[{Qbittorrent.client_name}]base32 infohash 解析失败: {err!s}")
            return None
        if isinstance(content, bytes):
            try:
                torrent = bdecode(content)
                if torrent and torrent.get("info"):
                    info = torrent.get("info")
                    info_encoded = bencode(info)
                    return hashlib.sha1(info_encoded, usedforsecurity=False).hexdigest().lower()
            except (InfrastructureError, NetworkError):
                raise
            except Exception as err:
                log.debug(f"[{Qbittorrent.client_name}]计算种子hash失败: {err!s}")
                return None
        return None

    def check_torrent_exists(self, content: str | bytes) -> tuple[bool, str | None]:
        torrent_hash = self.calculate_torrent_hash(content)
        if not torrent_hash:
            return False, None
        if not self.qbc:
            return False, torrent_hash
        try:
            torrents, error = self.get_torrents(ids=[torrent_hash])
            if not error and torrents:
                return True, torrent_hash
        except (InfrastructureError, NetworkError):
            raise
        except Exception as err:
            log.debug(f"[{self.client_name}]{self.name} 检查种子存在性失败: {err!s}")
        return False, torrent_hash

    def get_torrent_id_by_tag(self, tag: str, status: str | None = None) -> str | None:
        torrent_id = None
        for _i in range(1, 6):
            time.sleep(5)
            torrent_id = self.__get_last_add_torrentid_by_tag(tag=tag, status=status)
            if torrent_id is None:
                continue
            else:
                tag_removed = False
                for retry in range(3):
                    if self.remove_torrents_tag(torrent_id, tag):
                        time.sleep(1)
                        torrents, error = self.get_torrents(ids=[torrent_id])
                        if not error and torrents:
                            torrent = torrents[0]
                            if tag not in torrent.labels:
                                tag_removed = True
                                log.info(f"[{self.client_name}]{self.name} 成功移除种子 {torrent_id} 的标签: {tag}")
                                break
                            else:
                                log.warn(
                                    f"[{self.client_name}]{self.name} 种子 {torrent_id} "
                                    f"标签 {tag} 移除失败，重试 {retry + 1}/3"
                                )
                        else:
                            log.warn(f"[{self.client_name}]{self.name} 无法获取种子 {torrent_id} 信息验证标签移除")
                    else:
                        log.warn(
                            f"[{self.client_name}]{self.name} 移除种子 {torrent_id} 标签 {tag} 失败，重试 {retry + 1}/3"
                        )

                    if retry < 2:
                        time.sleep(2)

                if tag_removed:
                    break
                else:
                    log.error(
                        f"[{self.client_name}]{self.name} 无法移除种子 {torrent_id} 的标签 {tag}，继续尝试获取新种子"
                    )
                    torrent_id = None
        return torrent_id

    def add_torrent(
        self,
        content,
        is_paused=False,
        download_dir=None,
        tag=None,
        category=None,
        content_layout=None,
        upload_limit=None,
        download_limit=None,
        ratio_limit=None,
        seeding_time_limit=None,
        cookie=None,
        **kwargs,
    ):
        if not content:
            return False
        if not self.qbc:
            log.error(f"[{self.client_name}]{self.name} qBittorrent 客户端不可用（未登录或连接失败）")
            return False
        if isinstance(content, str):
            urls = content
            torrent_files = None
        else:
            urls = None
            torrent_files = content
        if download_dir:
            save_path = download_dir
            is_auto = False
        else:
            save_path = None
            is_auto = None
        if not category:
            category = None
        if tag:
            tags = tag
        else:
            tags = None
        if not content_layout:
            content_layout = None
        if upload_limit:
            upload_limit = int(upload_limit) * 1024
        else:
            upload_limit = None
        if download_limit:
            download_limit = int(download_limit) * 1024
        else:
            download_limit = None
        if ratio_limit:
            ratio_limit = round(float(ratio_limit), 2)
        else:
            ratio_limit = None
        if seeding_time_limit:
            seeding_time_limit = int(seeding_time_limit)
        else:
            seeding_time_limit = None

        try:
            if is_auto is None:
                match self._torrent_management:
                    case "default":
                        if self.__get_qb_auto():
                            is_auto = True
                    case "auto":
                        is_auto = True
                    case "manual":
                        is_auto = False

            if is_auto and not category:
                category = self.__check_category(save_path or "")

            qbc_ret = self.qbc.torrents_add(
                urls=urls,
                torrent_files=torrent_files,
                save_path=save_path,
                category=category,
                is_stopped=is_paused,
                tags=tags,
                content_layout=content_layout,
                upload_limit=upload_limit,
                download_limit=download_limit,
                ratio_limit=ratio_limit,
                seeding_time_limit=seeding_time_limit,
                use_auto_torrent_management=is_auto,
                cookie=cookie,
            )
            ret_ok = bool(qbc_ret and str(qbc_ret).find("Ok") != -1)
            if not ret_ok:
                log.warn(
                    f"[{self.client_name}]{self.name} 添加种子失败，"
                    f"qBittorrent 返回: {qbc_ret!r}（重复种子会返回 Fails.，需确认是否已在下载器中）"
                )
            return ret_ok
        except (InfrastructureError, NetworkError):
            raise
        except Exception as err:
            ExceptionUtils.exception_traceback(err)
            return False

    def add_torrent_and_get_id(
        self,
        content: str | bytes,
        is_paused: bool = False,
        download_dir: str | None = None,
        tags: list[str] | None = None,
        category: str | None = None,
        upload_limit: int | None = None,
        download_limit: int | None = None,
        ratio_limit: float | None = None,
        seeding_time_limit: int | None = None,
        cookie: str | None = None,
        **kwargs: Any,
    ) -> str | None:
        torrent_hash = self.calculate_torrent_hash(content)
        if not torrent_hash:
            return None
        exists, _ = self.check_torrent_exists(content)
        if exists:
            return torrent_hash
        ret = self.add_torrent(
            content,
            is_paused=is_paused,
            download_dir=download_dir,
            tag=tags,
            category=category,
            content_layout="Original",
            upload_limit=upload_limit,
            download_limit=download_limit,
            ratio_limit=ratio_limit,
            seeding_time_limit=seeding_time_limit,
            cookie=cookie,
        )
        if ret:
            return torrent_hash
        return None

    def start_torrents(self, ids: list[str] | str | None = None) -> Any:
        if not self.qbc:
            return False
        try:
            return self.qbc.torrents_resume(torrent_hashes=ids)
        except (InfrastructureError, NetworkError):
            raise
        except Exception as err:
            ExceptionUtils.exception_traceback(err)
            return False

    def stop_torrents(self, ids: list[str] | str | None = None) -> Any:
        if not self.qbc:
            return False
        try:
            return self.qbc.torrents_pause(torrent_hashes=ids)
        except (InfrastructureError, NetworkError):
            raise
        except Exception as err:
            ExceptionUtils.exception_traceback(err)
            return False

    def delete_torrents(self, delete_file: bool | None = None, ids: list[str] | str | None = None) -> Any:
        if not self.qbc:
            return False
        if not ids:
            return False
        try:
            self.qbc.torrents_delete(delete_files=delete_file, torrent_hashes=ids)
            return True
        except (InfrastructureError, NetworkError):
            raise
        except Exception as err:
            ExceptionUtils.exception_traceback(err)
            return False

    def _normalize_files(self, raw_files: Any) -> list[dict]:
        """将 qbittorrent 文件列表转换为统一格式."""
        if not raw_files:
            return []
        return [{"id": f.get("index", i), "name": f.get("name", "")} for i, f in enumerate(raw_files)]

    def set_file_selection(self, tid: str | None, selected_map: dict[int, bool]) -> bool:
        """设置种子文件的选择状态（priority=0 表示不下载，priority=1 表示正常）."""
        if not tid or not selected_map or not self.qbc:
            return False
        # priority: 0=不下载, 1=正常
        file_ids_to_skip = [fid for fid, selected in selected_map.items() if not selected]
        if not file_ids_to_skip:
            return True
        try:
            self.qbc.torrents_file_priority(
                torrent_hash=tid,
                file_ids=file_ids_to_skip,
                priority=0,
            )
            return True
        except (InfrastructureError, NetworkError):
            raise
        except Exception as err:
            ExceptionUtils.exception_traceback(err)
            return False

    def get_files(self, tid: str | None = None) -> Any:
        if not self.qbc:
            return None
        try:
            return self.qbc.torrents_files(torrent_hash=tid)
        except (InfrastructureError, NetworkError):
            raise
        except Exception as err:
            ExceptionUtils.exception_traceback(err)
            return None

    def set_files(self, **kwargs: Any) -> Any:
        if not self.qbc:
            return False
        if not kwargs.get("torrent_hash") or not kwargs.get("file_ids"):
            return False
        try:
            self.qbc.torrents_file_priority(
                torrent_hash=kwargs.get("torrent_hash"),
                file_ids=kwargs.get("file_ids"),
                priority=kwargs.get("priority"),
            )
            return True
        except (InfrastructureError, NetworkError):
            raise
        except Exception as err:
            ExceptionUtils.exception_traceback(err)
            return False

    def set_torrent_tag(self, **kwargs: Any) -> None:
        pass

    def get_download_dirs(self) -> Any:
        if not self.qbc:
            return []
        ret_dirs = []
        try:
            categories = self.qbc.torrents_categories(requests_args={"timeout": (10, 30)}) or {}
        except (InfrastructureError, NetworkError):
            raise
        except Exception as err:
            ExceptionUtils.exception_traceback(err)
            return []
        for category in categories.values():
            category: Any = category
            if category and category.get("savePath") and category.get("savePath") not in ret_dirs:
                ret_dirs.append(str(category.get("savePath") or ""))
        return ret_dirs

    def list_remote_dirs(self) -> list[str]:
        """候选目录 = 默认保存路径 + 分类路径 + 已有种子保存路径"""
        dirs = []
        if self.qbc:
            try:
                default_path = self.qbc.app_default_save_path()
                if default_path:
                    dirs.append(str(default_path))
            except (InfrastructureError, NetworkError):
                raise
            except Exception as err:
                ExceptionUtils.exception_traceback(err)
        return sorted({*dirs, *super().list_remote_dirs()})

    def set_uploadspeed_limit(self, ids: list[str] | str, limit: int) -> None:
        if not self.qbc:
            return
        if not ids or not limit:
            return
        self.qbc.torrents_set_upload_limit(limit=int(limit), torrent_hashes=ids)

    def set_downloadspeed_limit(self, ids: list[str] | str, limit: int) -> None:
        if not self.qbc:
            return
        if not ids or not limit:
            return
        self.qbc.torrents_set_download_limit(limit=int(limit), torrent_hashes=ids)

    def change_torrent(self, tid: str | None = None, **kwargs: Any) -> bool:
        return True

    def set_speed_limit(self, download_limit: int | None = None, upload_limit: int | None = None, **kwargs: Any) -> Any:
        if not self.qbc:
            return
        try:
            if download_limit is not None:
                download_limit = download_limit * 1024
                if self.qbc.transfer.download_limit != download_limit:
                    self.qbc.transfer.download_limit = download_limit
            if upload_limit is not None:
                upload_limit = upload_limit * 1024
                if self.qbc.transfer.upload_limit != upload_limit:
                    self.qbc.transfer.upload_limit = upload_limit
        except (InfrastructureError, NetworkError):
            raise
        except Exception as err:
            ExceptionUtils.exception_traceback(err)
            return False

    def recheck_torrents(self, ids: list[str] | str | None = None) -> Any:
        if not self.qbc:
            return False
        try:
            return self.qbc.torrents_recheck(torrent_hashes=ids)
        except (InfrastructureError, NetworkError):
            raise
        except Exception as err:
            ExceptionUtils.exception_traceback(err)
            return False

    def get_free_space(self, path: str) -> Any:
        if not self.qbc:
            return
        try:
            status: Any = self.qbc.sync_maindata().get("server_state")
            if not status:
                return
            return status.get("free_space_on_disk")
        except (InfrastructureError, NetworkError):
            raise
        except Exception as err:
            ExceptionUtils.exception_traceback(err)
            return

    def _get_torrent_trackers(self, torrent_hash):
        if not self.qbc:
            return
        try:
            tracker_list = self.qbc.torrents_trackers(torrent_hash=torrent_hash)
            return tracker_list
        except qbittorrentapi.NotFound404Error:
            # 种子已被删除/清理（删种或整理竞态）：属正常，静默忽略
            return None
        except (InfrastructureError, NetworkError):
            raise
        except Exception as err:
            ExceptionUtils.exception_traceback(err)
            return None

    def get_torrent_trackers(self, torrent_hash) -> list[str]:
        tracker_list = self._get_torrent_trackers(torrent_hash)
        if not tracker_list:
            return []
        result = []
        for t in tracker_list:
            url = getattr(t, "url", None) or (t.get("url") if isinstance(t, dict) else None)
            # 过滤 qb 的伪 tracker（DHT/PeX/LSD）
            if url and str(url).startswith(("http://", "https://", "udp://")):
                result.append(str(url))
        return result

    def add_torrent_trackers(self, torrent_hash, urls):
        if not self.qbc:
            return
        try:
            self.qbc.torrents_add_trackers(torrent_hashes=torrent_hash, urls=urls)
        except qbittorrentapi.NotFound404Error:
            return
        except (InfrastructureError, NetworkError):
            raise
        except Exception as err:
            ExceptionUtils.exception_traceback(err)

    def remove_torrent_trackers(self, torrent_hash, urls):
        if not self.qbc:
            return
        try:
            self.qbc.torrents_remove_trackers(torrent_hashes=torrent_hash, urls=urls)
        except qbittorrentapi.NotFound404Error:
            return
        except (InfrastructureError, NetworkError):
            raise
        except Exception as err:
            ExceptionUtils.exception_traceback(err)

    def edit_torrent_tracker(self, torrent_hash, old_url, new_url):
        if not self.qbc:
            return
        try:
            self.qbc.torrents_edit_tracker(torrent_hash=torrent_hash, original_url=old_url, new_url=new_url)
        except qbittorrentapi.NotFound404Error:
            return
        except (InfrastructureError, NetworkError):
            raise
        except Exception as err:
            ExceptionUtils.exception_traceback(err)

    def _extract_tracker_errors(self, torrent_hash):
        tracker_list = self._get_torrent_trackers(torrent_hash) or []
        has_working = False
        errors = []
        for tracker in tracker_list:
            status = tracker.get("status")
            msg = str(tracker.get("msg") or "")
            if status == 2:
                has_working = True
            elif status == 4:
                errors.append(msg or "Error")
            elif status in (0, 1) and ("error" in msg.lower() or "fail" in msg.lower() or "timeout" in msg.lower()):
                errors.append(msg)
        if has_working:
            return ""
        return "|".join(errors)

    def _get_torrent_generic_properties(self, torrent_hash):
        if not self.qbc:
            return
        try:
            properties = self.qbc.torrents_properties(torrent_hash=torrent_hash)
            return properties
        except (InfrastructureError, NetworkError):
            raise
        except Exception as err:
            ExceptionUtils.exception_traceback(err)
            return

    # 平均上传速度缓存 TTL（秒）：up_speed_avg 为长期平均值，变化缓慢；10 分钟刷新一次足够
    _UP_AVG_CACHE_TTL = 600

    @cached(
        cache_instance="downloader_up_avg",
        key_func=lambda self, torrent_hash: f"up_avg:{torrent_hash}",
        ttl=_UP_AVG_CACHE_TTL,
    )
    def _get_torrent_avg_upload_speed(self, torrent_hash: str) -> float:
        """获取种子平均上传速度（带缓存，避免 completed 种子多时逐种拉取 properties）."""
        avg = 0.0
        props = self._get_torrent_generic_properties(torrent_hash)
        if props:
            up_avg = props.get("up_speed_avg")
            if isinstance(up_avg, (int, float)):
                avg = float(up_avg)
        return avg

    def torrent_properties(self, torrent: dict) -> Torrent:
        date_now = int(time.time())

        torrent_obj = Torrent()
        properties = self._get_torrent_generic_properties(torrent.get("hash"))

        torrent_obj.id = torrent.get("hash")
        torrent_obj.name = torrent.get("name")
        added_on = torrent.get("added_on") or 0
        torrent_obj.download_time = date_now - added_on if added_on else 0
        completion_on = torrent.get("completion_on") or 0
        torrent_obj.seeding_time = date_now - completion_on if completion_on > 0 else 0
        torrent_obj.ratio = torrent.get("ratio") or 0
        torrent_obj.uploaded = torrent.get("uploaded") or 0
        up_speed_avg = properties.get("up_speed_avg") if properties else 0
        torrent_obj.avg_upload_speed = float(up_speed_avg) if isinstance(up_speed_avg, (int, float)) else 0
        last_activity = torrent.get("last_activity") or 0
        torrent_obj.iatime = date_now - last_activity if last_activity else 0
        torrent_obj.downloaded = int(torrent.get("downloaded") or 0)
        torrent_obj.size = int(torrent.get("total_size") or 0)
        torrent_obj.add_time = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(torrent.get("added_on") or 0))
        torrent_obj.status = self._map_status(str(torrent.get("state") or ""))
        torrent_obj.labels = [s.strip() for s in (torrent.get("tags") or "").split(",")]
        torrent_obj.content_path = torrent.get("content_path")
        torrent_obj.category = [s.strip() for s in (torrent.get("category") or "").split(",")]
        torrent_obj.trackers = [
            str(tracker.get("url") or "")
            for tracker in self._get_torrent_trackers(torrent_hash=torrent.get("hash")) or []
            if not any(keyword in str(tracker.get("url") or "") for keyword in ["DHT", "PeX", "LSD"])
        ]
        torrent_obj.tracker_error = self._extract_tracker_errors(torrent.get("hash"))
        torrent_obj.download_speed = int(torrent.get("dlspeed") or 0)
        torrent_obj.upload_speed = int(torrent.get("upspeed") or 0)
        torrent_obj.eta = int(torrent.get("eta") or 0)
        torrent_obj.progress = float(torrent.get("progress") or 0)
        torrent_obj.save_path = torrent.get("save_path")

        return torrent_obj

    def _map_status(self, raw_state: Any) -> TorrentStatus:
        if raw_state == "downloading":
            return TorrentStatus.Downloading
        elif raw_state == "stalledDL":
            return TorrentStatus.Pending
        elif raw_state in ("queuedDL", "queuedUP"):
            return TorrentStatus.Queued
        elif raw_state in ("uploading", "stalledUP"):
            return TorrentStatus.Uploading
        elif raw_state in ("checkingUP", "checkingDL"):
            return TorrentStatus.Checking
        elif raw_state in ("pausedUP", "pausedDL", "stoppedUP", "stoppedDL"):
            return TorrentStatus.Paused
        elif raw_state == "error":
            return TorrentStatus.Error
        else:
            return TorrentStatus.Unknown

    @property
    def _supported_statuses(self) -> list[TorrentStatus]:
        return [
            TorrentStatus.Downloading,
            TorrentStatus.Uploading,
            TorrentStatus.Checking,
            TorrentStatus.Queued,
            TorrentStatus.Paused,
            TorrentStatus.Pending,
            TorrentStatus.Error,
            TorrentStatus.Unknown,
        ]
