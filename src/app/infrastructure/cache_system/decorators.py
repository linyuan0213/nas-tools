"""
缓存装饰器
提供便捷的函数级缓存功能
"""

from __future__ import annotations

import contextlib
import functools
import inspect
import threading
from collections.abc import Callable

import log

from .adapters import MemoryCacheAdapter, get_cache_value
from .base import CacheAdapter
from .cache_manager import CacheManager


def cached(cache_instance: CacheAdapter | str | None = None, key_func: Callable | None = None, ttl: int | None = None):
    """
    缓存装饰器

    使用方法:
        @cached()  # 使用默认缓存
        def get_data(id):
            return fetch_from_db(id)

        @cached(cache_instance=my_cache, ttl=3600)
        def get_user(user_id):
            return User.query.get(user_id)

        @cached(key_func=lambda self, x: f"custom:{x}")
        def compute(self, x):
            return expensive_calculation(x)

    :param cache_instance: 缓存实例、缓存名称或None（使用默认内存缓存）
    :param key_func: 自定义缓存键生成函数
    :param ttl: 过期时间（秒）
    """

    def decorator(func: Callable) -> Callable:
        @functools.wraps(func)
        def wrapper(*args, **kwargs):
            # 获取缓存实例
            cache = _get_cache_instance(cache_instance)
            if cache is None:
                # 缓存不可用，直接执行
                return func(*args, **kwargs)

            # 生成缓存键
            if key_func:
                cache_key = key_func(*args, **kwargs)
            else:
                cache_key = _default_key_builder(func, *args, **kwargs)

            # 尝试从缓存获取
            try:
                found, result = get_cache_value(cache, cache_key)
                if found:
                    log.debug(f"[Cache]缓存命中: {cache_key}")
                    return result
                else:
                    log.debug(f"[Cache]缓存未命中: {cache_key}")
            except Exception as e:
                log.error(f"[Cache]获取缓存失败: {e}")

            # 执行函数
            result = func(*args, **kwargs)

            # 缓存结果（包括 None）
            try:
                cache.set(cache_key, result, ttl)
                log.debug(f"[Cache]缓存设置: {cache_key}")
            except Exception as e:
                log.error(f"[Cache]设置缓存失败: {e}")

            return result

        # 添加缓存操作方法
        wrapper.cache_clear = lambda: _clear_cache(cache_instance)  # type: ignore[attr-defined]
        wrapper.cache_delete = lambda key: _delete_cache(cache_instance, key)  # type: ignore[attr-defined]

        return wrapper

    return decorator


def cached_with_lock(
    cache_instance: CacheAdapter | str | None = None,
    lock: threading.Lock | None = None,
    key_func: Callable | None = None,
    ttl: int | None = None,
):
    """
    带锁的缓存装饰器（防止缓存穿透）

    使用方法:
        @cached_with_lock()
        def get_expensive_data(key):
            return expensive_query(key)

    :param cache_instance: 缓存实例、缓存名称或None
    :param lock: 可选的自定义锁
    :param key_func: 自定义缓存键生成函数
    :param ttl: 过期时间（秒）
    """
    if lock is None:
        lock = threading.Lock()

    def decorator(func: Callable) -> Callable:
        @functools.wraps(func)
        def wrapper(*args, **kwargs):
            # 获取缓存实例
            cache = _get_cache_instance(cache_instance)
            if cache is None:
                return func(*args, **kwargs)

            # 生成缓存键
            if key_func:
                cache_key = key_func(*args, **kwargs)
            else:
                cache_key = _default_key_builder(func, *args, **kwargs)

            # 先尝试从缓存获取
            try:
                found, result = get_cache_value(cache, cache_key)
                if found:
                    return result
            except Exception as e:  # noqa: BLE001
                log.debug(f"[Cache]忽略异常: {e}")

            # 加锁后再次检查（防止并发穿透）
            with lock:
                try:
                    found, result = get_cache_value(cache, cache_key)
                    if found:
                        return result
                except Exception as e:  # noqa: BLE001
                    log.debug(f"[Cache]忽略异常: {e}")

                # 执行函数
                result = func(*args, **kwargs)

                # 缓存结果（包括 None）
                with contextlib.suppress(Exception):
                    cache.set(cache_key, result, ttl)

                return result

        return wrapper

    return decorator


def cached_method(cache_name: str | None = None, ttl: int | None = None):
    """
    类方法缓存装饰器

    自动处理self参数，为每个实例提供独立的缓存

    使用方法:
        class MyService:
            @cached_method(ttl=3600)
            def get_user(self, user_id):
                return User.query.get(user_id)
    """

    def decorator(func: Callable) -> Callable:
        @functools.wraps(func)
        def wrapper(self, *args, **kwargs):
            # 获取或创建实例缓存
            cache_attr = f"_cache_{func.__name__}"
            if not hasattr(self, cache_attr):
                setattr(self, cache_attr, MemoryCacheAdapter())

            cache = getattr(self, cache_attr)
            cache_key = _default_key_builder(func, self, *args, **kwargs)

            # 尝试获取缓存
            found, result = get_cache_value(cache, cache_key)
            if found:
                return result

            # 执行并缓存（包括 None）
            result = func(self, *args, **kwargs)
            cache.set(cache_key, result, ttl)

            return result

        return wrapper

    return decorator


def lru_cache_with_ttl(maxsize: int = 128, ttl: int | None = None):
    """
    带TTL的LRU缓存装饰器（兼容functools.lru_cache风格）

    使用方法:
        @lru_cache_with_ttl(maxsize=256, ttl=3600)
        def get_data(key):
            return fetch_data(key)
    """

    def decorator(func: Callable) -> Callable:

        cache = MemoryCacheAdapter(maxsize=maxsize)

        @functools.wraps(func)
        def wrapper(*args, **kwargs):
            cache_key = _default_key_builder(func, *args, **kwargs)

            found, result = get_cache_value(cache, cache_key)
            if found:
                return result

            result = func(*args, **kwargs)
            cache.set(cache_key, result, ttl)
            return result

        wrapper.cache_info = cache.get_stats  # type: ignore[attr-defined]
        wrapper.cache_clear = cache.clear  # type: ignore[attr-defined]

        return wrapper

    return decorator


def _get_cache_instance(cache_instance: CacheAdapter | str | None) -> CacheAdapter | None:
    """获取缓存实例"""
    if cache_instance is None:
        # 使用默认缓存
        return None
    elif isinstance(cache_instance, str):
        # 通过名称获取缓存
        manager = CacheManager()
        return manager.get_or_create(cache_instance)
    else:
        # 直接使用缓存实例
        return cache_instance


def _default_key_builder(func: Callable, *args, **kwargs) -> str:
    """默认缓存键构建器

    使用函数签名绑定参数，确保不同调用方式（位置参数/关键字参数）
    生成一致的缓存键
    """
    # 检查并跳过 self/cls 参数
    bind_args = args
    bind_kwargs = kwargs

    if args:
        first_arg = args[0]
        func_qualname = func.__qualname__
        if "." in func_qualname:
            class_name = func_qualname.split(".")[0]

            # 检查是否是实例方法 (self)
            if (
                hasattr(first_arg, "__class__")
                and first_arg.__class__.__name__ == class_name
                or isinstance(first_arg, type)
                and first_arg.__name__ == class_name
            ):
                bind_args = args[1:]

    # 获取实际函数的签名（通过 __wrapped__ 链）
    # func 可能是 wrapper，需要获取原始函数
    actual_func = func
    while hasattr(actual_func, "__wrapped__"):
        actual_func = getattr(actual_func, "__wrapped__")

    try:
        # 获取原始函数签名
        sig = inspect.signature(actual_func)
        params = list(sig.parameters.values())

        # 如果第一个参数是 self/cls 且已经被跳过，创建新签名去掉它
        if params and params[0].name in ("self", "cls"):
            # 去掉第一个参数（self/cls）
            new_params = params[1:]
            sig = sig.replace(parameters=new_params)

        bound = sig.bind(*bind_args, **bind_kwargs)
        bound.apply_defaults()
        arguments = dict(bound.arguments)

    except (TypeError, ValueError):
        # 绑定失败，使用位置参数索引
        arguments = {}
        for i, arg in enumerate(bind_args):
            arguments[f"arg{i}"] = arg
        arguments.update(bind_kwargs)

    # 构建缓存键
    key_parts = [func.__qualname__]

    # 按参数名排序，确保一致性
    for param_name in sorted(arguments.keys()):
        value = arguments[param_name]
        key_parts.append(f"{param_name}={value}")

    return ":".join(key_parts)


def _clear_cache(cache_instance: CacheAdapter | str | None):
    """清除缓存"""
    cache = _get_cache_instance(cache_instance)
    if cache:
        cache.clear()


def _delete_cache(cache_instance: CacheAdapter | str | None, key: str):
    """删除缓存键"""
    cache = _get_cache_instance(cache_instance)
    if cache:
        cache.delete(key)
