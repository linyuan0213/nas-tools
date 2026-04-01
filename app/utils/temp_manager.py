import os
import time
import shutil
import threading
from datetime import datetime, timedelta
from typing import Optional, List, Callable
from contextlib import contextmanager

import log
from config import Config
from .exception_utils import ExceptionUtils


class TempManager:
    """
    临时文件管理器
    用于统一管理临时文件，支持自动清理、定期清理和上下文管理
    """
    
    _instance = None
    _lock = threading.Lock()
    
    # 默认临时文件保留时间（24小时）
    DEFAULT_MAX_AGE_HOURS = 24
    # 默认清理间隔（6小时）
    DEFAULT_CLEANUP_INTERVAL_HOURS = 6
    
    def __new__(cls, *args, **kwargs):
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    cls._instance = super(TempManager, cls).__new__(cls)
                    cls._instance._initialized = False
        return cls._instance
    
    def __init__(self):
        if self._initialized:
            return
        self._initialized = True
        self._temp_path = Config().get_temp_path()
        self._cleanup_callbacks: List[Callable] = []
        self._ensure_temp_dir()
    
    def _ensure_temp_dir(self):
        """确保临时目录存在"""
        if not os.path.exists(self._temp_path):
            os.makedirs(self._temp_path)
    
    def get_temp_path(self, filename: Optional[str] = None) -> str:
        """
        获取临时文件路径
        :param filename: 文件名，如果为None则返回临时目录路径
        :return: 完整路径
        """
        self._ensure_temp_dir()
        if filename:
            return os.path.join(self._temp_path, filename)
        return self._temp_path
    
    def create_temp_file(self, prefix: str = "tmp_", suffix: str = "") -> str:
        """
        创建一个临时文件路径（不实际创建文件）
        :param prefix: 文件名前缀
        :param suffix: 文件名后缀
        :return: 临时文件完整路径
        """
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
        filename = f"{prefix}{timestamp}{suffix}"
        return self.get_temp_path(filename)
    
    def create_subdir(self, subdir_name: str) -> str:
        """
        创建临时目录下的子目录
        :param subdir_name: 子目录名称
        :return: 子目录完整路径
        """
        subdir_path = os.path.join(self._temp_path, subdir_name)
        if not os.path.exists(subdir_path):
            os.makedirs(subdir_path)
        return subdir_path
    
    def delete_file(self, file_path: str, ignore_errors: bool = True) -> bool:
        """
        删除单个文件
        :param file_path: 文件路径
        :param ignore_errors: 是否忽略错误
        :return: 是否删除成功
        """
        try:
            if os.path.exists(file_path):
                if os.path.isfile(file_path):
                    os.remove(file_path)
                    log.debug(f"【TempManager】已删除文件: {file_path}")
                elif os.path.isdir(file_path):
                    shutil.rmtree(file_path)
                    log.debug(f"【TempManager】已删除目录: {file_path}")
                return True
        except Exception as e:
            if not ignore_errors:
                raise
            log.warn(f"【TempManager】删除失败 {file_path}: {str(e)}")
        return False
    
    def cleanup_old_files(self, max_age_hours: Optional[int] = None, 
                         exclude_patterns: Optional[List[str]] = None) -> int:
        """
        清理指定时间之前的临时文件
        :param max_age_hours: 最大保留时间（小时），默认24小时
        :param exclude_patterns: 排除的文件名模式列表
        :return: 清理的文件数量
        """
        if max_age_hours is None:
            max_age_hours = self.DEFAULT_MAX_AGE_HOURS
        
        if exclude_patterns is None:
            exclude_patterns = []
        
        cutoff_time = time.time() - (max_age_hours * 3600)
        deleted_count = 0
        
        try:
            if not os.path.exists(self._temp_path):
                return 0
            
            for item in os.listdir(self._temp_path):
                # 检查排除模式
                if any(pattern in item for pattern in exclude_patterns):
                    continue
                
                item_path = os.path.join(self._temp_path, item)
                try:
                    # 获取文件/目录的修改时间
                    mtime = os.path.getmtime(item_path)
                    if mtime < cutoff_time:
                        self.delete_file(item_path)
                        deleted_count += 1
                except Exception as e:
                    log.warn(f"【TempManager】检查 {item} 时出错: {str(e)}")
            
            if deleted_count > 0:
                log.info(f"【TempManager】已清理 {deleted_count} 个过期临时文件")
            
        except Exception as e:
            ExceptionUtils.exception_traceback(e)
        
        # 执行注册的回调函数
        for callback in self._cleanup_callbacks:
            try:
                callback(max_age_hours, exclude_patterns)
            except Exception as e:
                log.warn(f"【TempManager】清理回调执行失败: {str(e)}")
        
        return deleted_count
    
    def register_cleanup_callback(self, callback: Callable):
        """
        注册额外的清理回调函数
        :param callback: 回调函数，接收 max_age_hours 和 exclude_patterns 参数
        """
        self._cleanup_callbacks.append(callback)
    
    def get_temp_size(self) -> int:
        """
        获取临时目录总大小（字节）
        :return: 总大小
        """
        total_size = 0
        if not os.path.exists(self._temp_path):
            return 0
        
        for dirpath, dirnames, filenames in os.walk(self._temp_path):
            for f in filenames:
                fp = os.path.join(dirpath, f)
                try:
                    total_size += os.path.getsize(fp)
                except:
                    pass
        return total_size
    
    def get_temp_size_human(self) -> str:
        """
        获取临时目录大小（人类可读格式）
        :return: 如 "1.5 MB"
        """
        size_bytes = self.get_temp_size()
        for unit in ['B', 'KB', 'MB', 'GB', 'TB']:
            if size_bytes < 1024.0:
                return f"{size_bytes:.2f} {unit}"
            size_bytes /= 1024.0
        return f"{size_bytes:.2f} PB"
    
    def clear_all(self, exclude_patterns: Optional[List[str]] = None) -> int:
        """
        清空所有临时文件（谨慎使用）
        :param exclude_patterns: 排除的文件名模式列表
        :return: 清理的文件数量
        """
        if exclude_patterns is None:
            exclude_patterns = []
        
        deleted_count = 0
        try:
            if not os.path.exists(self._temp_path):
                return 0
            
            for item in os.listdir(self._temp_path):
                if any(pattern in item for pattern in exclude_patterns):
                    continue
                
                item_path = os.path.join(self._temp_path, item)
                if self.delete_file(item_path):
                    deleted_count += 1
            
            log.info(f"【TempManager】已清空 {deleted_count} 个临时文件")
            
        except Exception as e:
            ExceptionUtils.exception_traceback(e)
        
        return deleted_count


# 全局实例
temp_manager = TempManager()


@contextmanager
def temp_file_context(filename: Optional[str] = None, 
                     prefix: str = "tmp_", 
                     suffix: str = "",
                     auto_delete: bool = True):
    """
    临时文件上下文管理器
    使用示例:
        with temp_file_context(suffix=".torrent") as tmp_path:
            # 使用 tmp_path 下载文件
            download_file(url, tmp_path)
            # 处理完成后文件会自动删除
    
    :param filename: 指定文件名，如果为None则自动生成
    :param prefix: 自动生成文件名时的前缀
    :param suffix: 自动生成文件名时的后缀
    :param auto_delete: 是否自动删除文件
    :yield: 临时文件路径
    """
    if filename:
        file_path = temp_manager.get_temp_path(filename)
    else:
        file_path = temp_manager.create_temp_file(prefix=prefix, suffix=suffix)
    
    try:
        yield file_path
    finally:
        if auto_delete:
            temp_manager.delete_file(file_path)


@contextmanager
def temp_dir_context(dir_name: Optional[str] = None,
                     prefix: str = "tmpdir_",
                     auto_delete: bool = True):
    """
    临时目录上下文管理器
    使用示例:
        with temp_dir_context() as tmp_dir:
            # 使用 tmp_dir 解压文件
            unzip_file(zip_path, tmp_dir)
            # 处理完成后目录会自动删除
    
    :param dir_name: 指定目录名，如果为None则自动生成
    :param prefix: 自动生成目录名时的前缀
    :param auto_delete: 是否自动删除目录
    :yield: 临时目录路径
    """
    if dir_name:
        dir_path = temp_manager.create_subdir(dir_name)
    else:
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
        dir_path = temp_manager.create_subdir(f"{prefix}{timestamp}")
    
    try:
        yield dir_path
    finally:
        if auto_delete:
            temp_manager.delete_file(dir_path)
