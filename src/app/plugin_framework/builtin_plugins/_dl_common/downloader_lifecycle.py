"""下载器插件的共享生命周期逻辑."""


import log
from app.db.repositories.config_repo_adapter import DownloaderRepositoryAdapter


def disable_downloader_records(dtype: str) -> None:
    """禁用指定类型的下载器记录（插件禁用时随动停用，配置保留，重新启用时恢复）"""
    try:
        repo = DownloaderRepositoryAdapter()
        for d in repo.get_downloaders() or []:
            if getattr(d, "TYPE", None) == dtype and getattr(d, "ENABLED", False):
                repo.update_downloader(
                    did=d.ID,
                    name=d.NAME,
                    enabled=0,
                    dtype=d.TYPE,
                    transfer=d.TRANSFER,
                    only_nexus_media=d.ONLY_NEXUS_MEDIA,
                    match_path=d.MATCH_PATH,
                    rmt_mode=d.RMT_MODE,
                    config=d.CONFIG,
                    download_dir=d.DOWNLOAD_DIR,
                )
    except Exception as e:  # noqa: BLE001
        log.error(f"[Plugin]禁用下载器记录失败 {dtype}: {e}")
