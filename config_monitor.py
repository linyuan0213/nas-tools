import os
from signal import SIGINT, SIGTERM, signal
import time
import subprocess
from loguru import logger
from cacheout import Cache
from watchdog.events import FileSystemEventHandler
from watchdog.observers import Observer


_observer = Observer(timeout=10)

ConfigLoadCache = Cache(maxsize=1, ttl=20, timer=time.time, default=None)
CategoryLoadCache = Cache(maxsize=2, ttl=3, timer=time.time, default=None)


class ConfigMonitor(FileSystemEventHandler):
    """
    配置文件变化响应
    """

    def __init__(self):
        FileSystemEventHandler.__init__(self)

    def on_modified(self, event):
        if event.is_directory:
            return
        src_path = event.src_path
        file_name = os.path.basename(src_path)
        file_head, file_ext = os.path.splitext(os.path.basename(file_name))
        if file_ext != ".yaml":
            return
        # 配置文件20秒内只能加载一次
        if file_name == "config.yaml" and not ConfigLoadCache.get(src_path):
            ConfigLoadCache.set(src_path, True)
            CategoryLoadCache.set("ConfigLoadBlock", True, ConfigLoadCache.ttl)
            logger.warning("检测到系统配置文件已修改，正在重新加载...")

            logger.info("Nastool 重启中...")
            res = subprocess.run(['bash', './restart-server.sh'], cwd='.')
            if res.returncode == 0:
                logger.info("Nastool 重启成功...")
            else:
                logger.info(f"Nastool 重启失败: {res.stderr.decode()}")


def start_config_monitor():
    """
    启动服务
    """
    global _observer
    # 配置文件监听
    _observer.schedule(ConfigMonitor(), path=os.environ.get('NASTOOL_CONFIG'), recursive=False)
    _observer.daemon = True
    _observer.start()
    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        pass
    _observer.join()


def stop_config_monitor():
    """
    停止服务
    """
    global _observer
    try:
        if _observer:
            _observer.stop()
            _observer.join()
    except Exception as err:
        print(str(err))


def signal_handler(sig, frame):
    logger.info('收到 SIGTERM 信号, 停止监控...')
    stop_config_monitor()
    logger.info('监控停止，退出中...')
    exit(0)


if __name__ == "__main__":
    signal(SIGTERM, signal_handler)
    signal(SIGINT, signal_handler)

    logger.info('配置文件监控启动...')
    start_config_monitor()
