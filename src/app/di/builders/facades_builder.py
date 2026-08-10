"""业务 Facade Builder — 创建 Layer 3 对象。"""

from app.agent.agents.recognizer_adapter import MediaRecognizerParser
from app.agent.service import AgentService
from app.di.models import BusinessFacades, InfrastructureObjects
from app.downloader.client_factory import DownloadClientFactory
from app.media.lookup.tmdb_client import TmdbClient
from app.media.lookup.tmdb_lookup import TmdbLookup
from app.media.service import MediaService
from app.mediaserver.media_server import MediaServer
from app.services.download_monitor import DownloadMonitor


def build_business_facades(infra: InfrastructureObjects) -> BusinessFacades:
    """创建 Layer 3 业务 Facade。"""
    tmdb_client = TmdbClient()

    agent_service = AgentService()
    media_recognizer = agent_service.media_recognizer
    search_intent_agent = agent_service.search_intent_agent

    media_service = MediaService(
        tmdb_lookup=TmdbLookup(client=tmdb_client),
        llm_parser=MediaRecognizerParser(recognizer=media_recognizer),
    )

    # 回填 plugin_sandbox 的媒体服务引用
    infra.plugin_sandbox._media_service = media_service

    media_server = MediaServer(
        media_service=media_service,
        message=infra.message,
        message_queue=infra.message_queue,
    )

    download_monitor = DownloadMonitor(
        client_factory=DownloadClientFactory(),
        event_bus=infra.event_bus,
    )

    return BusinessFacades(
        media_service=media_service,
        media_server=media_server,
        tmdb_client=tmdb_client,
        agent_service=agent_service,
        media_recognizer=media_recognizer,
        search_intent_agent=search_intent_agent,
        download_monitor=download_monitor,
    )
