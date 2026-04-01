# -*- coding: utf-8 -*-
import time
import threading
import functools

from cacheout import CacheManager, LRUCache, Cache

CACHES = {
    "tmdb_supply": {'maxsize': 500}  # 增加缓存大小
}

cacheman = CacheManager(CACHES, cache_class=LRUCache)

TokenCache = Cache(maxsize=512, ttl=4*3600, timer=time.time, default=None)

ConfigLoadCache = Cache(maxsize=1, ttl=60, timer=time.time, default=None)

CategoryLoadCache = Cache(maxsize=2, ttl=3, timer=time.time, default=None)

OpenAISessionCache = Cache(maxsize=200, ttl=3600, timer=time.time, default=None)

# 新增缓存实例
MediaInfoCache = Cache(maxsize=1000, ttl=3600, timer=time.time, default=None)  # 媒体信息缓存
SearchResultCache = Cache(maxsize=500, ttl=1800, timer=time.time, default=None)  # 搜索结果缓存
SiteInfoCache = Cache(maxsize=100, ttl=300, timer=time.time, default=None)  # 站点信息缓存


def cached(cache_instance, key_func=None):
    """
    装饰器：为函数添加缓存功能
    :param cache_instance: 缓存实例
    :param key_func: 自定义缓存键生成函数
    """
    def decorator(func):
        @functools.wraps(func)
        def wrapper(*args, **kwargs):
            # 生成缓存键
            if key_func:
                cache_key = key_func(*args, **kwargs)
            else:
                # 使用函数名和参数作为缓存键
                cache_key = f"{func.__name__}:{str(args)}:{str(kwargs)}"
            
            # 尝试从缓存获取
            result = cache_instance.get(cache_key)
            if result is not None:
                return result
            
            # 执行函数并缓存结果
            result = func(*args, **kwargs)
            if result is not None:
                cache_instance.set(cache_key, result)
            
            return result
        
        # 添加清除缓存的方法
        wrapper.cache_clear = lambda: cache_instance.clear()
        wrapper.cache_delete = lambda key: cache_instance.delete(key)
        
        return wrapper
    return decorator


def cached_with_lock(cache_instance, lock=None):
    """
    装饰器：为函数添加带锁的缓存功能，防止缓存穿透
    """
    if lock is None:
        lock = threading.Lock()
    
    def decorator(func):
        @functools.wraps(func)
        def wrapper(*args, **kwargs):
            cache_key = f"{func.__name__}:{str(args)}:{str(kwargs)}"
            
            # 先尝试从缓存获取
            result = cache_instance.get(cache_key)
            if result is not None:
                return result
            
            # 加锁后再次检查（防止并发穿透）
            with lock:
                result = cache_instance.get(cache_key)
                if result is not None:
                    return result
                
                # 执行函数
                result = func(*args, **kwargs)
                if result is not None:
                    cache_instance.set(cache_key, result)
                
                return result
        
        return wrapper
    return decorator
