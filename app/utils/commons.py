# -*- coding: utf-8 -*-
import threading
import time

class SingletonMeta(type):
    """
    定义一个元类，用来实现单例模式
    """
    _instances = {}
    _lock = threading.RLock()

    def __call__(cls, *args, **kwargs):
        # 实现单例，检查是否已经有实例存在
        if cls not in cls._instances:
            with cls._lock:
                if cls not in cls._instances:
                    # 使用父类的 __call__ 创建类的实例
                    cls._instances[cls] = super().__call__(*args, **kwargs)
        return cls._instances[cls]


# 重试装饰器
def retry(ExceptionToCheck, tries=3, delay=3, backoff=2, logger=None):
    """
    :param ExceptionToCheck: 需要捕获的异常
    :param tries: 重试次数
    :param delay: 延迟时间
    :param backoff: 延迟倍数
    :param logger: 日志对象
    """

    def deco_retry(f):
        def f_retry(*args, **kwargs):
            mtries, mdelay = tries, delay
            while mtries > 1:
                try:
                    return f(*args, **kwargs)
                except ExceptionToCheck as e:
                    msg = f"{str(e)}, {mdelay} 秒后重试 ..."
                    if logger:
                        logger.warn(msg)
                    else:
                        print(msg)
                    time.sleep(mdelay)
                    mtries -= 1
                    mdelay *= backoff
            return f(*args, **kwargs)

        return f_retry

    return deco_retry
