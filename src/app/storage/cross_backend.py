"""跨后端复制引擎。"""

import log
from app.storage.backends.base import StorageBackend


def cross_copy(
    src_backend: StorageBackend,
    src_path: str,
    dst_backend: StorageBackend,
    dst_path: str,
    chunk_size: int = 8 * 1024 * 1024,
) -> None:
    """
    跨后端复制文件。

    策略（按优先级）：
    1. 服务端 COPY：dst_backend 支持从 src_backend 快速复制
    2. 流式传输：src.read_stream → dst.write_stream

    chunk_size 透传给 dst_backend.write_stream，后端按自身能力使用；
    本地后端使用 chunk_size 控制 shutil.copyfileobj 的缓冲区，避免大文件小 IO。
    """
    try:
        if src_backend.can_fast_cross_copy(dst_backend):
            src_backend.cross_copy_to(src_path, dst_backend, dst_path)
            return
    except Exception as e:  # noqa: BLE001
        log.debug(f"[CrossBackend]忽略异常: {e}")

    stream = src_backend.read_stream(src_path)
    try:
        dst_backend.write_stream(dst_path, stream, chunk_size=chunk_size)
    finally:
        stream.close()


def cross_move(
    src_backend: StorageBackend,
    src_path: str,
    dst_backend: StorageBackend,
    dst_path: str,
) -> None:
    """跨后端移动 = 跨后端复制 + 源端删除。"""
    cross_copy(src_backend, src_path, dst_backend, dst_path)
    src_backend.remove(src_path)
