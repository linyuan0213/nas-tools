"""
Logger 管理器与 loguru 配置。
"""

import logging
import threading

from loguru import logger

from ._config import build_handlers, purge_expired_logs
from ._intercept import InterceptHandler

__all__ = ["Logger", "get_logger_instance"]

# 使用 RLock 支持重入，减少死锁风险
_lock = threading.RLock()

# 模块级实例缓存
_instances: dict[str, "Logger"] = {}


class Logger:
    """基于 loguru 的按模块日志管理器。"""

    def __init__(self, module: str):
        self._module = module
        # 启动兜底：清理超过保留期的轮转日志（loguru retention 仅在轮转时触发）
        purge_expired_logs(module)
        handlers = build_handlers(module)
        logger.configure(handlers=handlers)  # type: ignore[reportArgumentType]
        logging.basicConfig(handlers=[InterceptHandler()], level=0)
        # 屏蔽 redis-py 8.x 的 MAINT_NOTIFICATIONS 兼容性告警
        logging.getLogger("redis").setLevel(logging.WARNING)
        self._log = logger

    @property
    def log(self):
        return self._log

    @classmethod
    def get_instance(cls, module: str) -> "Logger":
        if not module:
            module = "nexus-media"
        instance = _instances.get(module)
        if instance is not None:
            return instance
        with _lock:
            instance = _instances.get(module)
            if instance is not None:
                return instance
            instance = cls(module)
            _instances[module] = instance
        return instance


def get_logger_instance(module: str) -> Logger:
    return Logger.get_instance(module)
