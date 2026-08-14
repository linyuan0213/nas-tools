"""RAG 知识库自动更新事件处理器 — 媒体转移完成后节流重建 media_library 命名空间.

media_library 来源是聚合加载（统计 + 最近入库），因此转移完成时对整个命名空间 reindex，
并用节流窗口避免频繁转移导致重复重建。
"""

import threading
import time

import log
from app.agent.rag.namespaces import Namespace
from app.events import Event
from app.events.constants import MEDIA_TRANSFER_FINISHED
from app.events.payloads import MediaTransferFinishedPayload

# media_library 命名空间重建节流窗口（秒）
_KB_MEDIA_MIN_INTERVAL = 1800

_state: dict = {
    "last_media_reindex": 0.0,
    "knowledge_ingestor": None,
    "registered": False,
}
_state_lock = threading.Lock()


def _throttled_media_reindex(knowledge_ingestor) -> None:
    """节流执行 media_library 命名空间重建"""
    now = time.time()
    with _state_lock:
        if now - _state["last_media_reindex"] < _KB_MEDIA_MIN_INTERVAL:
            log.debug("[KB]media_library 重建跳过（节流窗口内）")
            return
        _state["last_media_reindex"] = now
    try:
        stats = knowledge_ingestor.reindex(namespace=Namespace.MEDIA_LIBRARY)
        log.info(f"[KB]媒体转移完成触发 media_library 重建: {stats}")
    except Exception as e:
        log.error(f"[KB]media_library 重建失败: {e}")


def register_kb_ingest_handler(event_bus, knowledge_ingestor, thread_executor=None) -> None:
    """注册媒体转移完成 → 知识库自动更新处理器（外部显式注入依赖）

    支持配置热重载后重复调用：仅首次订阅事件，后续只更新引用的 ingestor，
    避免重复注册导致同一事件触发多次重建。
    """
    if knowledge_ingestor is None or event_bus is None:
        return
    with _state_lock:
        _state["knowledge_ingestor"] = knowledge_ingestor
        if _state["registered"]:
            return
        _state["registered"] = True

    def _handler(event: Event) -> None:
        payload = event.payload
        if not isinstance(payload, MediaTransferFinishedPayload):
            payload = MediaTransferFinishedPayload(**payload)
        log.debug(f"[KB]收到媒体转移完成: {payload.dest or payload.target_path or payload.file}")
        with _state_lock:
            current = _state["knowledge_ingestor"]
        if current is None:
            return
        if thread_executor is not None:
            thread_executor.submit(_throttled_media_reindex, current)
        else:
            _throttled_media_reindex(current)

    event_bus.subscribe(MEDIA_TRANSFER_FINISHED, _handler)
    log.info("[KB]媒体转移完成 → 知识库自动更新处理器已注册")
