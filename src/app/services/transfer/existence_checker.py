"""MediaExistenceChecker - 媒体文件存在性检查."""

import os

import log
from app.core.constants import RMT_FAVTYPE, RMT_MEDIAEXT
from app.domain.mediatypes import MediaType
from app.utils import PathUtils


class MediaExistenceChecker:
    """负责检查媒体文件是否已存在于目标目录（支持本地和远程后端）."""

    def __init__(self, path_resolver, media_service=None):
        self._path_resolver = path_resolver
        self._media = media_service

    def _exists(self, path: str, backend_id: str = "local") -> bool:
        """根据后端检查路径是否存在."""
        if backend_id == "local":
            return os.path.exists(path)
        backend = self._path_resolver.resolve_backend_by_id(backend_id)
        if not backend:
            return False
        return backend.exists(path)

    def _get_dir_files(self, path: str, backend_id: str = "local", exts: str | list | None = None) -> list[str]:
        """根据后端获取目录下匹配扩展名的文件列表."""
        if not path:
            return []
        _exts = exts or ""
        if backend_id == "local":
            return PathUtils.get_dir_files(path, _exts)
        backend = self._path_resolver.resolve_backend_by_id(backend_id)
        if not backend:
            return []
        files = []
        try:
            for finfo in backend.list_dir(path):
                if finfo.is_dir:
                    continue
                if exts:
                    ext = os.path.splitext(finfo.path)[1].lower()
                    if ext not in exts:
                        continue
                files.append(finfo.path)
        except Exception as e:  # noqa: BLE001
            log.debug(f"[FileTransfer]忽略异常: {e}")
        return files

    def is_media_exists(self, media_dest, media, dst_backend=None):
        """
        判断媒体文件是否已存在.
        :return: (dir_exist_flag, ret_dir_path, file_exist_flag, ret_file_path)
        """
        backend = dst_backend

        def _exists(path: str) -> bool:
            if backend is not None:
                return backend.exists(path)
            return os.path.exists(path)

        dir_exist_flag = False
        file_exist_flag = False
        ret_dir_path = None
        ret_file_path = None

        if media.type == MediaType.MOVIE:
            dir_name, file_name = self._path_resolver.get_movie_dest_path(media, self._media)
            file_path = os.path.join(media_dest, dir_name)
            if self._path_resolver.movie_category_flag:
                file_path = os.path.join(media_dest, media.category, dir_name)
                for m_type in [RMT_FAVTYPE, media.category]:
                    type_path = os.path.join(media_dest, m_type, dir_name)
                    if _exists(type_path):
                        file_path = type_path
                        break
            ret_dir_path = file_path
            if _exists(file_path):
                dir_exist_flag = True
            file_dest = os.path.join(file_path, file_name)
            ret_file_path = file_dest
            for ext in RMT_MEDIAEXT:
                ext_dest = f"{file_dest}{ext}"
                if _exists(ext_dest):
                    file_exist_flag = True
                    ret_file_path = ext_dest
                    break
        else:
            dir_name, season_name, file_name = self._path_resolver.get_tv_dest_path(media, self._media)
            if (media.type == MediaType.TV and self._path_resolver.tv_category_flag) or (
                media.type == MediaType.ANIME and self._path_resolver.anime_category_flag
            ):
                media_path = os.path.join(media_dest, media.category, dir_name)
            else:
                media_path = os.path.join(media_dest, dir_name)
            if media.get_season_list():
                season_dir = os.path.join(media_path, season_name)
                ret_dir_path = season_dir
                if _exists(season_dir):
                    dir_exist_flag = True
                episodes = media.get_episode_list()
                if episodes:
                    file_path = os.path.join(season_dir, file_name)
                    ret_file_path = file_path
                    for ext in RMT_MEDIAEXT:
                        ext_dest = f"{file_path}{ext}"
                        if _exists(ext_dest):
                            file_exist_flag = True
                            ret_file_path = ext_dest
                            break
        return dir_exist_flag, ret_dir_path, file_exist_flag, ret_file_path

    def get_no_exists_medias(self, meta_info_obj, meta_info_fn, season=None, total_num=None):
        """
        根据媒体库目录结构，判断媒体是否存在.
        :return: 电影返回已存在的电影清单，剧集返回不存在的集的清单.
        """
        if meta_info_obj.type == MediaType.MOVIE:
            dir_name, _ = self._path_resolver.get_movie_dest_path(meta_info_obj, self._media)
            backends = self._path_resolver._movie_backend or []
            for idx, dest_path in enumerate(self._path_resolver.movie_path):
                backend_id = backends[idx] if idx < len(backends) else "local"
                fav_path = os.path.join(dest_path, RMT_FAVTYPE, dir_name)
                fav_files = self._get_dir_files(fav_path, backend_id, RMT_MEDIAEXT)
                if self._path_resolver.movie_category_flag:
                    check_path = os.path.join(dest_path, meta_info_obj.category, dir_name)
                else:
                    check_path = os.path.join(dest_path, dir_name)
                files = self._get_dir_files(check_path, backend_id, RMT_MEDIAEXT)
                if len(files) > 0 or len(fav_files) > 0:
                    return [{"title": meta_info_obj.title, "year": meta_info_obj.year}]
            return []
        else:
            dir_name, season_name, _ = self._path_resolver.get_tv_dest_path(meta_info_obj, self._media)
            if not season or not total_num:
                return []
            if meta_info_obj.type == MediaType.ANIME:
                dest_paths = self._path_resolver.anime_path
                category_flag = self._path_resolver.anime_category_flag
                backends = self._path_resolver._anime_backend or []
            else:
                dest_paths = self._path_resolver.tv_path
                category_flag = self._path_resolver.tv_category_flag
                backends = self._path_resolver._tv_backend or []
            total_episodes = list(range(1, total_num + 1))
            exists_episodes = []
            for idx, dest_path in enumerate(dest_paths):
                backend_id = backends[idx] if idx < len(backends) else "local"
                if category_flag:
                    check_path = os.path.join(dest_path, meta_info_obj.category, dir_name, season_name)
                else:
                    check_path = os.path.join(dest_path, dir_name, season_name)
                if not self._exists(check_path, backend_id):
                    continue
                files = self._get_dir_files(check_path, backend_id, RMT_MEDIAEXT)
                for file in files:
                    file_meta_info = meta_info_fn(title=os.path.basename(file))
                    if not file_meta_info.get_season_list() or not file_meta_info.get_episode_list():
                        continue
                    # 同时比对 cn_name / en_name / title（兼容多语言场景）
                    target_names = {
                        (meta_info_obj.cn_name or "").strip(),
                        (meta_info_obj.en_name or "").strip(),
                        (meta_info_obj.title or "").strip(),
                    }
                    target_names.discard("")
                    file_name = (file_meta_info.get_name() or "").strip()
                    if file_name and not any(
                        fn == tn or fn in tn or tn in fn for tn in target_names for fn in [file_name]
                    ):
                        continue
                    if not file_meta_info.is_in_season(season):
                        continue
                    exists_episodes = list(set(exists_episodes).union(set(file_meta_info.get_episode_list())))
            return list(set(total_episodes).difference(set(exists_episodes)))
