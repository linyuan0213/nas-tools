"""
日志模块

提供基于 loguru 的日志记录、LogBuffer 代理以及便捷 API。
"""

import logging

from ._api import console, debug, error, info, warn
from ._buffer_proxy import LOG_BUFFER, LogBufferProxy, get_log_buffer
from ._compat import LOG_INDEX, LOG_QUEUE
from ._intercept import InterceptHandler
from ._logger_manager import Logger, get_logger_instance
from ._source import extract_source, normalize_source

# 抑制第三方库日志噪音
logging.getLogger("werkzeug").setLevel(logging.ERROR)
logging.getLogger("watchdog").setLevel(logging.WARNING)
logging.getLogger("watchdog.observers").setLevel(logging.WARNING)
logging.getLogger("watchdog.observers.inotify_buffer").setLevel(logging.WARNING)
# 抑制 watchfiles（uvicorn --reload 使用）日志
logging.getLogger("watchfiles").setLevel(logging.WARNING)
logging.getLogger("watchfiles.main").setLevel(logging.WARNING)
logging.getLogger("charset_normalizer").setLevel(logging.WARNING)
# 抑制 Agent SDK 的 HTTP 请求 DEBUG 日志
logging.getLogger("httpx").setLevel(logging.WARNING)
logging.getLogger("httpcore").setLevel(logging.WARNING)
logging.getLogger("httpx2").setLevel(logging.WARNING)
logging.getLogger("httpcore2").setLevel(logging.WARNING)
logging.getLogger("openai").setLevel(logging.WARNING)
logging.getLogger("urllib3").setLevel(logging.WARNING)
# 抑制 websockets 协议帧/keepalive DEBUG 日志（> PING/< PONG 刷屏）
logging.getLogger("websockets").setLevel(logging.WARNING)

__all__ = [
    # API
    "debug",
    "info",
    "error",
    "warn",
    "console",
    # 核心类
    "Logger",
    "get_logger_instance",
    "InterceptHandler",
    # Buffer 相关
    "LOG_BUFFER",
    "LogBufferProxy",
    "get_log_buffer",
    # 来源提取/归一化
    "extract_source",
    "normalize_source",
    # 兼容别名
    "LOG_QUEUE",
    "LOG_INDEX",
]
