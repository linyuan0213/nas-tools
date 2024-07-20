import logging
import os
import sys
import re
import threading
import time
import inspect
from collections import deque
from html import escape
from loguru import logger

from config import Config

logging.getLogger('werkzeug').setLevel(logging.ERROR)
logging.getLogger('watchdog').setLevel(logging.INFO)
lock = threading.Lock()

LOG_QUEUE = deque(maxlen=200)
LOG_INDEX = 0


class InterceptHandler(logging.Handler):
    def emit(self, record):
        # Get corresponding Loguru level if it exists
        try:
            level = logger.level(record.levelname).name
        except ValueError:
            level = record.levelno

        # Find caller from where originated the logged message
        frame, depth = logging.currentframe(), 1
        while frame.f_code.co_filename == logging.__file__ or frame.f_code.co_filename == __file__:
            frame = frame.f_back
            depth += 1

        logger.opt(depth=depth, exception=record.exc_info).log(level, record.getMessage())


class Logger:
    logger = None
    __instance = {}
    __config = None

    def __init__(self, module):
        self.logger = logger
        self.__config = Config()
        logtype = self.__config.get_config('app').get('logtype') or "console"
        loglevel = self.__config.get_config('app').get('loglevel') or "info"
        handlers = []
        self.logger.level(loglevel.upper())
        if logtype == "server":
            logserver = self.__config.get_config('app').get('logserver', '').split(':')
            if logserver:
                logip = logserver[0]
                if len(logserver) > 1:
                    logport = int(logserver[1] or '514')
                else:
                    logport = 514

                handler = {
                        "sink": f"tcp://{logip}:{logport}",
                        "format": "{time:YYYY-MM-DD HH:mm:ss.SSS} |{level:8}| {file} : {module}.{function}:{line:4} | - {message}",
                        "colorize": False
                    }
                handlers.append(handler)

        elif logtype == "file":
            # 记录日志到文件
            logpath = os.environ.get('NASTOOL_LOG') or self.__config.get_config('app').get('logpath') or ""
            if logpath:
                if not os.path.exists(logpath):
                    os.makedirs(logpath)

                handler = {
                        "sink": os.path.join(logpath, module + ".log"),
                        "rotation": "5 MB",
                        "format": "{time:YYYY-MM-DD HH:mm:ss.SSS} |{level:8}| {file} : {module}.{function}:{line:4} | - {message}",
                        "colorize": False,
                        "retention": "5 days"
                    }
                handlers.append(handler)
        # 记录日志到终端
        handler = {
            "sink": sys.stderr,
            "format": "{time:YYYY-MM-DD HH:mm:ss.SSS} |<lvl>{level:8}</>| {file} : {module}.{function}:{line:4} | - <lvl>{message}</>",
            "colorize": True
        }
        handlers.append(handler)
        logger.configure(handlers=handlers)
        logging.basicConfig(handlers=[InterceptHandler()], level=0)

    @staticmethod
    def get_instance(module):
        if not module:
            module = "run"
        if Logger.__instance.get(module):
            return Logger.__instance.get(module)
        with lock:
            Logger.__instance[module] = Logger(module)
        return Logger.__instance.get(module)


def __append_log_queue(level, text):
    global LOG_INDEX, LOG_QUEUE
    with lock:
        text = escape(text)
        if text.startswith("【"):
            source = re.findall(r"(?<=【).*?(?=】)", text)[0]
            text = text.replace(f"【{source}】", "")
        else:
            source = "System"
        LOG_QUEUE.append({
            "time": time.strftime('%H:%M:%S', time.localtime(time.time())),
            "level": level,
            "source": source,
            "text": text})
        LOG_INDEX += 1


def debug(text, module=None):
    frame, depth = inspect.currentframe(), 0
    while frame and (depth == 0 or frame.f_code.co_filename == __file__):
        frame = frame.f_back
        depth += 1
    return Logger.get_instance(module).logger.opt(depth=depth).debug(text)


def info(text, module=None):
    frame, depth = inspect.currentframe(), 0
    while frame and (depth == 0 or frame.f_code.co_filename == __file__):
        frame = frame.f_back
        depth += 1
    __append_log_queue("INFO", text)
    return Logger.get_instance(module).logger.opt(depth=depth).info(text)


def error(text, module=None):
    frame, depth = inspect.currentframe(), 0
    while frame and (depth == 0 or frame.f_code.co_filename == __file__):
        frame = frame.f_back
        depth += 1
    __append_log_queue("ERROR", text)
    return Logger.get_instance(module).logger.opt(depth=depth).error(text)


def warn(text, module=None):
    frame, depth = inspect.currentframe(), 0
    while frame and (depth == 0 or frame.f_code.co_filename == __file__):
        frame = frame.f_back
        depth += 1
    __append_log_queue("WARN", text)
    return Logger.get_instance(module).logger.opt(depth=depth).warning(text)


def console(text):
    __append_log_queue("INFO", text)
    print(text)
