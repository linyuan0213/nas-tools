"""
领域接口导出
"""

from app.domain.interfaces.brush_repo import IBrushTaskRepository, IBrushTorrentRepository
from app.domain.interfaces.chat import ChatPort
from app.domain.interfaces.config_repo import (
    IDownloaderRepository,
    IFilterGroupRepository,
    IFilterRuleRepository,
    IMediaServerRepository,
    IMessageClientRepository,
    ITorrentRemoveTaskRepository,
)
from app.domain.interfaces.download_repo import (
    IDownloadHistoryRepository,
    IDownloadSettingRepository,
    IIndexerStatisticsRepository,
)
from app.domain.interfaces.intent import IntentResolver, SearchIntent
from app.domain.interfaces.plugin_repo import (
    IPluginHistoryRepository,
    ITmdbBlacklistRepository,
)
from app.domain.interfaces.rbac_repo import (
    IRBACLogRepository,
    IRBACMenuRepository,
    IRBACPermissionRepository,
    IRBACRoleRepository,
    IRBACUserRepository,
)
from app.domain.interfaces.rss_repo import (
    ISubscribeHistoryRepository,
    ISubscribeMovieRepository,
    ISubscribeTvEpisodeRepository,
    ISubscribeTvRepository,
)
from app.domain.interfaces.search_repo import ISearchRepository
from app.domain.interfaces.site_repo import (
    ISiteRepository,
    ISiteSeedingRepository,
    ISiteStatisticsRepository,
)
from app.domain.interfaces.storage_backend_repo import IStorageBackendRepository
from app.domain.interfaces.sync_repo import ISyncPathRepository
from app.domain.interfaces.transfer_repo import (
    ITransferBlacklistRepository,
    ITransferHistoryRepository,
    ITransferUnknownRepository,
)
from app.domain.interfaces.word_repo import (
    ICustomWordGroupRepository,
    ICustomWordRepository,
)

__all__ = [
    "ISiteRepository",
    "ISiteStatisticsRepository",
    "ISiteSeedingRepository",
    "IDownloadHistoryRepository",
    "IDownloadSettingRepository",
    "IIndexerStatisticsRepository",
    "ISubscribeMovieRepository",
    "ISubscribeTvRepository",
    "ISubscribeTvEpisodeRepository",
    "ISubscribeHistoryRepository",
    "ITransferHistoryRepository",
    "ITransferUnknownRepository",
    "ITransferBlacklistRepository",
    "IBrushTaskRepository",
    "IBrushTorrentRepository",
    "ISyncPathRepository",
    "IStorageBackendRepository",
    "IMessageClientRepository",
    "IDownloaderRepository",
    "IFilterGroupRepository",
    "IFilterRuleRepository",
    "IMediaServerRepository",
    "ITorrentRemoveTaskRepository",
    "ISearchRepository",
    "IRBACUserRepository",
    "IRBACRoleRepository",
    "IRBACPermissionRepository",
    "IRBACMenuRepository",
    "IRBACLogRepository",
    "SearchIntent",
    "IntentResolver",
    "ChatPort",
]
