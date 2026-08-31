"""媒体服务器插件的共享生命周期逻辑."""

import log
from app.db.repositories.config_repo_adapter import MediaServerRepositoryAdapter


def disable_mediaserver_record(server_type: str) -> None:
    """禁用指定类型的媒体服务器记录（插件禁用时随动停用，配置保留，重新启用时恢复）"""
    try:
        repo = MediaServerRepositoryAdapter()
        for s in repo.get_media_servers() or []:
            if getattr(s, "NAME", None) == server_type and getattr(s, "ENABLED", False):
                repo.update_media_server(
                    sid=s.ID, name=s.NAME, enabled=0, config=s.CONFIG, is_default=s.IS_DEFAULT
                )
    except Exception as e:  # noqa: BLE001
        log.error(f"[Plugin]禁用媒体服务器记录失败 {server_type}: {e}")
