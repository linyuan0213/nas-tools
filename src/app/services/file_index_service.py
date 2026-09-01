"""
FileIndexService - 媒体库文件索引服务
后台维护媒体库 + 同步源目录的文件索引，支持 O(1) 搜索响应。

实现：
- 启动时后台线程全量扫描构建索引
- 每 5 分钟自动重建
- 索引数据存储在 app.utils.cache_system 的内存缓存中
- 提供内存中字符串匹配搜索（遍历，万级文件毫秒级）
"""

from __future__ import annotations

import os
import threading

import log
from app.core.constants import RMT_MEDIAEXT
from app.core.settings import settings
from app.infrastructure.cache_system import get_cache_manager
from app.infrastructure.distributed_lock.lock_manager import get_lock_manager

_CACHE_NAME = "file_index"
_KEY_INDEX = "index"
_KEY_READY = "ready"
_KEY_COUNT = "count"


class FileIndexService:
    """文件索引服务"""

    def __init__(self, sync_path_repo):
        self._thread: threading.Thread | None = None
        self._stop_event = threading.Event()
        self._cache = get_cache_manager().get_or_create(_CACHE_NAME, "memory", maxsize=10, ttl=None)
        self._sync_path_repo = sync_path_repo

    # ---------- 生命周期 ----------

    def start(self) -> None:
        """启动后台索引线程"""
        if self._thread is not None and self._thread.is_alive():
            return
        self._stop_event.clear()
        self._thread = threading.Thread(target=self._build_index_loop, daemon=True)
        self._thread.start()
        log.info("[FileIndex]文件索引服务已启动")

    def stop(self) -> None:
        """停止后台索引线程"""
        self._stop_event.set()
        if self._thread:
            self._thread.join(timeout=5)
        log.info("[FileIndex]文件索引服务已停止")

    def refresh(self) -> None:
        """手动触发一次重建"""
        threading.Thread(target=self._rebuild_index, daemon=True).start()

    @property
    def is_ready(self) -> bool:
        return bool(self._cache.get(_KEY_READY))

    @property
    def indexed_count(self) -> int:
        return self._cache.get(_KEY_COUNT) or 0

    # ---------- 索引构建 ----------

    def _build_index_loop(self) -> None:
        """后台循环：先立即建一次，之后每 5 分钟重建"""
        self._rebuild_index()
        while not self._stop_event.is_set():
            self._stop_event.wait(300)
            if not self._stop_event.is_set():
                self._rebuild_index()

    def _rebuild_index(self) -> None:
        """全量扫描所有根目录，重建索引"""
        lock = get_lock_manager().create_lock("fileindex:rebuild", ttl_seconds=600)
        acquired = lock.acquire()
        if not acquired:
            log.info("[FileIndex]索引重建正在执行，跳过")
            return
        try:
            roots = self._get_root_paths()
            if not roots:
                log.warn("[FileIndex]未配置媒体库或同步源目录，索引为空")
                self._cache.set(_KEY_INDEX, {})
                self._cache.set(_KEY_READY, True)
                self._cache.set(_KEY_COUNT, 0)
                return

            new_index: dict[str, dict] = {}
            seen: set[str] = set()

            for root in roots:
                if not root or not os.path.isdir(root):
                    continue
                try:
                    self._scan_dir(root, new_index, seen)
                except Exception as e:
                    log.warn(f"[FileIndex]扫描目录失败 {root}: {e}")

            self._cache.set(_KEY_INDEX, new_index)
            self._cache.set(_KEY_READY, True)
            self._cache.set(_KEY_COUNT, len(new_index))
            log.info(f"[FileIndex]索引重建完成，共 {len(new_index)} 个文件，根目录: {roots}")
        finally:
            lock.release()

    def _get_root_paths(self) -> list[str]:
        """获取所有需要索引的根目录"""
        cfg = settings
        roots: list[str] = []

        # 媒体库目录
        media = cfg.get("media") or {}
        for key in ("movie_path", "tv_path", "anime_path"):
            paths = media.get(key) or []
            if isinstance(paths, str):
                paths = [paths]
            for p in paths:
                if p:
                    roots.append(os.path.normpath(p).replace("\\", "/"))

        # 同步源目录
        try:
            for conf in self._sync_path_repo.get_config_sync_paths():
                if conf:
                    src = getattr(conf, "SOURCE", None) or (
                        conf.__dict__.get("SOURCE") if hasattr(conf, "__dict__") else None
                    )
                    if src:
                        roots.append(os.path.normpath(src).replace("\\", "/"))
        except Exception as e:  # noqa: BLE001
            log.debug(f"[FileIndex]忽略异常: {e}")

        # 去重
        seen: set[str] = set()
        result = []
        for r in roots:
            if r and r not in seen:
                seen.add(r)
                result.append(r)
        return result

    def _scan_dir(self, directory: str, index: dict[str, dict], seen: set[str]) -> None:
        """递归扫描目录，只索引媒体文件 + 目录（供浏览用）"""
        try:
            entries = os.scandir(directory)
        except (OSError, PermissionError):
            return

        for entry in entries:
            if len(index) >= 50000:  # 上限 5 万文件
                return

            try:
                is_dir = entry.is_dir(follow_symlinks=False)
            except (OSError, PermissionError):
                continue

            norm_path = entry.path.replace("\\", "/")
            if norm_path in seen:
                continue
            seen.add(norm_path)

            if is_dir:
                # 目录入索引（供浏览时快速定位）
                index[norm_path] = {
                    "name": entry.name,
                    "path": norm_path,
                    "is_dir": True,
                }
                self._scan_dir(entry.path, index, seen)
            else:
                # 只索引媒体扩展名
                ext = os.path.splitext(entry.name)[1].lower()
                if ext in RMT_MEDIAEXT:
                    item = {
                        "name": entry.name,
                        "path": norm_path,
                        "is_dir": False,
                        "ext": ext,
                    }
                    try:
                        st = entry.stat(follow_symlinks=False)
                        item["size"] = st.st_size
                        item["mtime"] = st.st_mtime
                        item["ctime"] = st.st_ctime
                    except OSError:
                        item["size"] = None
                        item["mtime"] = None
                        item["ctime"] = None
                    index[norm_path] = item

    # ---------- 搜索 ----------

    def _get_index(self) -> dict[str, dict]:
        """获取当前索引字典"""
        return self._cache.get(_KEY_INDEX) or {}

    def search(self, keyword: str, limit: int = 100) -> list[dict]:
        """关键词搜索，返回匹配的文件列表"""
        if not keyword:
            return []

        kw = keyword.lower()
        results = []
        index = self._get_index()

        for item in index.values():
            if item.get("is_dir"):
                continue
            if kw in item["name"].lower():
                results.append(dict(item))
                if len(results) >= limit:
                    break

        return results

    def search_dirs(self, keyword: str, limit: int = 50) -> list[dict]:
        """搜索目录"""
        if not keyword:
            return []

        kw = keyword.lower()
        results = []
        index = self._get_index()

        for item in index.values():
            if not item.get("is_dir"):
                continue
            if kw in item["name"].lower():
                results.append(dict(item))
                if len(results) >= limit:
                    break

        return results

    def get_dir_contents(self, path: str) -> list[dict]:
        """获取指定目录下的内容（用于浏览时的快速目录跳转）"""
        norm = (path or "").replace("\\", "/").rstrip("/")
        prefix = norm + "/"
        results = []
        index = self._get_index()

        for item in index.values():
            p = item["path"]
            if p == norm:
                continue
            if p.startswith(prefix):
                rest = p[len(prefix) :]
                if "/" not in rest:  # 直接子项
                    results.append(dict(item))

        results.sort(key=lambda x: (not x.get("is_dir", False), x["name"].lower()))
        return results

    def find_path(self, keyword: str) -> str | None:
        """搜索并返回第一个匹配文件的所在目录"""
        results = self.search(keyword, limit=1)
        if results:
            p = results[0]["path"]
            return os.path.dirname(p).replace("\\", "/")
        return None
