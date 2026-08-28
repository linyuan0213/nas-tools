"""文件转移引擎——唯一文件操作入口。"""

import os
import re
from threading import Lock

import log
from app.core.constants import RMT_AUDIO_TRACK_EXT, RMT_SUBEXT
from app.db.repositories.transfer_repo_adapter import TransferBlacklistRepositoryAdapter
from app.media import meta_info
from app.storage import LocalStorageBackend, StorageConfig, cross_copy, cross_move
from app.storage.backends.base import StorageBackend, StorageType
from app.utils import PathUtils

_lock = Lock()


class TransferEngine:
    """
    文件转移引擎。
    所有文件操作通过 StorageBackend 完成，不再区分本地/远程。
    operation 为字符串："copy" / "move" / "link" / "softlink"
    """

    def __init__(self):
        self._local = LocalStorageBackend(StorageConfig(id="local", name="local", type=StorageType.LOCAL))
        self._blacklist = TransferBlacklistRepositoryAdapter()

    def _execute(
        self,
        src: str,
        dst: str,
        operation: str,
        src_backend: StorageBackend | None = None,
        dst_backend: StorageBackend | None = None,
    ) -> None:
        src_b = src_backend or self._local
        dst_b = dst_backend or self._local
        with _lock:
            if src_b is self._local and dst_b is self._local:
                if operation == "copy":
                    self._local.copy(src, dst)
                elif operation == "move":
                    self._local.move(src, dst)
                elif operation == "link":
                    self._local.hardlink(src, dst)
                elif operation == "softlink":
                    self._local.softlink(src, dst)
                else:
                    raise ValueError(f"不支持的操作: {operation}")
                return
            # 同一远程后端：优先服务端复制（webdav MOVE/COPY 等），避免本地中转
            if src_b is dst_b:
                if operation in ("link", "softlink"):
                    log.warn(f"[Rmt]远程后端不支持 {operation}，自动降级为 copy")
                    operation = "copy"
                if operation == "copy":
                    src_b.copy(src, dst)
                elif operation == "move":
                    src_b.copy(src, dst)
                    src_b.remove(src)
                else:
                    raise ValueError(f"远程后端不支持 {operation}")
                return
            # 跨后端（含本地↔远程）：流式传输或服务端快速复制
            if operation in ("link", "softlink"):
                log.warn(f"[Rmt]远程后端不支持 {operation}，自动降级为 copy")
                operation = "copy"
            if operation == "copy":
                cross_copy(src_b, src, dst_b, dst)
            elif operation == "move":
                cross_move(src_b, src, dst_b, dst)
            else:
                raise ValueError(f"远程后端不支持 {operation}")

    def transfer_subtitles(
        self,
        org_name: str,
        new_name: str,
        operation: str,
        src_backend: StorageBackend | None = None,
        dst_backend: StorageBackend | None = None,
    ) -> None:
        backend = dst_backend or self._local
        src_b = src_backend or self._local
        _zhcn_sub_re = (
            r"([.\[\]](((zh[-_])?(cn|ch[si]|sg|sc))|zho?"
            r"|chinese|(cn|ch[si]|sg|zho?|eng)[-_&](cn|ch[si]|sg|zho?|eng)"
            r"|简[体中]?|JPSC)[.\]\)])"
            r"|([一-龥]{0,3}[中双][一-龥]{0,2}[字文语][一-龥]{0,3})"
            r"|简体|简中"
            r"|(?<![a-z0-9])gb(?![a-z0-9])"
        )
        _zhtw_sub_re = (
            r"([.\[\]](((zh[-_])?(hk|tw|cht|tc))"
            r"|繁[体中]?|JPTC)[.\]\)])"
            r"|繁体中[文字]|中[文字]繁体|繁体"
            r"|(?<![a-z0-9])big5(?![a-z0-9])"
        )
        _eng_sub_re = r"[.\[\]]eng[.\]\)]"

        dir_name = os.path.dirname(org_name)
        file_name = os.path.basename(org_name)
        file_list = (
            PathUtils.get_dir_level1_files(dir_name, RMT_SUBEXT)
            if src_backend is None
            else self._list_backend_files(src_b, dir_name, RMT_SUBEXT)
        )
        if not file_list:
            return

        metainfo = meta_info(title=file_name)
        for file_item in file_list:
            sub_file_name = re.sub(
                _zhtw_sub_re,
                ".",
                re.sub(_zhcn_sub_re, ".", os.path.basename(file_item), flags=re.IGNORECASE),
                flags=re.IGNORECASE,
            )
            sub_file_name = re.sub(_eng_sub_re, ".", sub_file_name, flags=re.IGNORECASE)
            sub_metainfo = meta_info(title=os.path.basename(file_item))
            if not self._subtitle_match(file_name, sub_file_name, metainfo, sub_metainfo):
                continue

            new_file_type = self._detect_subtitle_type(file_item, _zhcn_sub_re, _zhtw_sub_re, _eng_sub_re)
            file_ext = os.path.splitext(file_item)[-1]
            src_size = 0
            if src_backend is not None:
                st = src_b.stat(file_item)
                src_size = st.size if st else 0
            else:
                src_size = os.path.getsize(file_item)
            for tag in [new_file_type] + [f"{new_file_type}.{t}" for t in range(1, 6)]:
                new_file = os.path.splitext(new_name)[0] + tag + file_ext
                dst_stat = backend.stat(new_file)
                if dst_stat:
                    if dst_stat.size == src_size:
                        log.info(f"[Rmt]字幕 {new_file} 已存在")
                        break
                    # 同名但内容不同 → 尝试下一个序号标签，避免覆盖/硬链接冲突
                    continue
                try:
                    log.debug(f"[Rmt]正在处理字幕：{os.path.basename(file_item)}")
                    self._execute(file_item, new_file, operation, src_backend, dst_backend)
                    log.info(f"[Rmt]字幕 {os.path.basename(file_item)} {operation}完成")
                    break
                except Exception as e:
                    # 单个字幕失败不阻断主文件与其他字幕的转移
                    log.error(f"[Rmt]字幕 {file_name} {operation}失败：{e}")
                    break

    def transfer_audio_tracks(
        self,
        org_name: str,
        new_name: str,
        operation: str,
        over_flag: bool,
        src_backend: StorageBackend | None = None,
        dst_backend: StorageBackend | None = None,
    ) -> None:
        backend = dst_backend or self._local
        src_b = src_backend or self._local
        dir_name = os.path.dirname(org_name)
        file_pre = os.path.splitext(os.path.basename(org_name))[0]
        track_files = (
            PathUtils.get_dir_level1_files(dir_name, RMT_AUDIO_TRACK_EXT)
            if src_backend is None
            else self._list_backend_files(src_b, dir_name, RMT_AUDIO_TRACK_EXT)
        )
        for track_file in track_files:
            if os.path.splitext(os.path.basename(track_file))[0] != file_pre:
                continue
            new_track = os.path.splitext(new_name)[0] + os.path.splitext(track_file)[1].lower()
            if backend.exists(new_track):
                if not over_flag:
                    log.warn(f"[Rmt]音轨文件已存在：{new_track}")
                    continue
                backend.remove(new_track)
            log.info(f"[Rmt]正在转移音轨文件：{track_file} 到 {new_track}")
            self._execute(track_file, new_track, operation, src_backend, dst_backend)
            log.info(f"[Rmt]音轨文件 {os.path.basename(track_file)} {operation}完成")

    def _list_backend_files(self, backend: StorageBackend, dir_path: str, exts: list) -> list[str]:
        """列取后端目录下匹配扩展名的文件（一级）"""
        files = []
        try:
            for finfo in backend.list_dir(dir_path):
                if finfo.is_dir:
                    continue
                ext = os.path.splitext(finfo.path)[1].lower()
                if exts and ext not in exts:
                    continue
                files.append(finfo.path)
        except Exception as e:  # noqa: BLE001
            log.debug(f"[Rmt]后端目录列举失败: {e}")
        return files

    def transfer_dir(
        self,
        src_dir: str,
        target_dir: str,
        operation: str,
        record_blacklist: bool = True,
        dst_backend: StorageBackend | None = None,
    ) -> None:
        backend = dst_backend or self._local
        for file in PathUtils.get_dir_files(src_dir):
            new_file = file.replace(src_dir, target_dir)
            if not os.path.exists(new_file):
                if backend.exists(new_file):
                    log.warn(f"[Rmt]{new_file} 文件已存在")
                    continue
            backend.mkdir(os.path.dirname(new_file), parents=True)
            self._execute(file, new_file, operation, dst_backend)
            if record_blacklist:
                self._blacklist.insert(file)

    def transfer_bluray_dir(
        self, src_dir: str, target_dir: str, operation: str, dst_backend: StorageBackend | None = None
    ) -> None:
        self.transfer_dir(src_dir, target_dir, operation, record_blacklist=False, dst_backend=dst_backend)
        self._blacklist.insert(src_dir)

    def transfer(
        self,
        src: str,
        dst: str,
        operation: str,
        over_flag: bool = False,
        old_file: str | None = None,
        src_backend: StorageBackend | None = None,
        dst_backend: StorageBackend | None = None,
    ) -> None:
        dst_b = dst_backend or self._local
        if not over_flag and dst_b.exists(dst):
            log.warn(f"[Rmt]文件已存在：{dst}")
            return
        if over_flag and old_file:
            old_backend = src_backend or self._local
            if old_backend.exists(old_file):
                st = old_backend.stat(old_file)
                if st and not st.is_dir:
                    old_backend.remove(old_file)

        log.info(f"[Rmt]正在转移文件：{os.path.basename(src)} 到 {dst}")
        self._execute(src, dst, operation, src_backend, dst_backend)
        log.info(f"[Rmt]文件 {os.path.basename(src)} {operation}完成")
        self._blacklist.insert(src)

        self.transfer_subtitles(src, dst, operation, src_backend, dst_backend)
        self.transfer_audio_tracks(src, dst, operation, over_flag, src_backend, dst_backend)

    @staticmethod
    def _subtitle_match(file_name: str, sub_name: str, meta, sub_meta) -> bool:
        if os.path.splitext(file_name)[0] == os.path.splitext(sub_name)[0]:
            return True
        if sub_meta.cn_name and sub_meta.cn_name == meta.cn_name:
            return True
        if sub_meta.en_name and sub_meta.en_name == meta.en_name:
            return True
        if meta.get_season_string() and meta.get_season_string() != sub_meta.get_season_string():
            return False
        return not (meta.get_episode_string() and meta.get_episode_string() != sub_meta.get_episode_string())

    @staticmethod
    def _detect_subtitle_type(file_item: str, zhcn_re, zhtw_re, eng_re) -> str:
        if re.search(zhcn_re, file_item, re.IGNORECASE):
            return ".chi.zh-cn"
        if re.search(zhtw_re, file_item, re.IGNORECASE):
            return ".zh-tw"
        if re.search(eng_re, file_item, re.IGNORECASE):
            return ".eng"
        return ".und"
