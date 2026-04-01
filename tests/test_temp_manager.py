import os
import time
import pytest
import shutil
from datetime import datetime, timedelta
from unittest.mock import patch, MagicMock

from app.utils.temp_manager import TempManager, temp_manager, temp_file_context, temp_dir_context


class TestTempManager:
    """测试临时文件管理器"""
    
    @pytest.fixture
    def mock_config(self, tmp_path):
        """模拟配置返回临时目录"""
        with patch('app.utils.temp_manager.Config') as mock_cfg:
            mock_cfg.return_value.get_temp_path.return_value = str(tmp_path / "temp")
            yield mock_cfg
    
    @pytest.fixture
    def clean_manager(self, mock_config, tmp_path):
        """提供干净的 TempManager 实例"""
        # 重置单例状态
        TempManager._instance = None
        TempManager._initialized = False
        
        test_temp = tmp_path / "temp"
        test_temp.mkdir(exist_ok=True)
        
        manager = TempManager()
        yield manager
        
        # 清理
        if test_temp.exists():
            shutil.rmtree(test_temp)
        TempManager._instance = None
        TempManager._initialized = False
    
    def test_singleton_pattern(self, mock_config, tmp_path):
        """测试单例模式"""
        TempManager._instance = None
        TempManager._initialized = False
        
        manager1 = TempManager()
        manager2 = TempManager()
        
        assert manager1 is manager2
        
        # 清理
        TempManager._instance = None
        TempManager._initialized = False
    
    def test_get_temp_path(self, clean_manager):
        """测试获取临时路径"""
        # 获取目录路径
        temp_dir = clean_manager.get_temp_path()
        assert os.path.exists(temp_dir)
        
        # 获取文件路径
        file_path = clean_manager.get_temp_path("test.txt")
        assert file_path.endswith("test.txt")
        assert temp_dir in file_path
    
    def test_create_temp_file(self, clean_manager):
        """测试创建临时文件路径"""
        file_path = clean_manager.create_temp_file(prefix="test_", suffix=".txt")
        
        assert file_path.startswith(clean_manager.get_temp_path())
        assert "test_" in file_path
        assert file_path.endswith(".txt")
        assert not os.path.exists(file_path)  # 只是创建路径，不创建文件
    
    def test_create_subdir(self, clean_manager):
        """测试创建子目录"""
        subdir = clean_manager.create_subdir("test_subdir")
        
        assert os.path.exists(subdir)
        assert os.path.isdir(subdir)
        assert "test_subdir" in subdir
    
    def test_delete_file(self, clean_manager):
        """测试删除文件"""
        # 创建测试文件
        test_file = clean_manager.get_temp_path("test_delete.txt")
        with open(test_file, 'w') as f:
            f.write("test")
        
        assert os.path.exists(test_file)
        
        # 删除文件
        result = clean_manager.delete_file(test_file)
        assert result is True
        assert not os.path.exists(test_file)
    
    def test_delete_directory(self, clean_manager):
        """测试删除目录"""
        # 创建测试目录和文件
        test_dir = clean_manager.get_temp_path("test_dir")
        os.makedirs(test_dir)
        test_file = os.path.join(test_dir, "file.txt")
        with open(test_file, 'w') as f:
            f.write("test")
        
        # 删除目录
        result = clean_manager.delete_file(test_dir)
        assert result is True
        assert not os.path.exists(test_dir)
    
    def test_cleanup_old_files(self, clean_manager):
        """测试清理过期文件"""
        # 创建旧文件
        old_file = clean_manager.get_temp_path("old_file.txt")
        with open(old_file, 'w') as f:
            f.write("old")
        # 修改文件时间为 48 小时前
        old_time = time.time() - 48 * 3600
        os.utime(old_file, (old_time, old_time))
        
        # 创建新文件
        new_file = clean_manager.get_temp_path("new_file.txt")
        with open(new_file, 'w') as f:
            f.write("new")
        
        # 清理超过 24 小时的文件
        count = clean_manager.cleanup_old_files(max_age_hours=24)
        
        assert count == 1
        assert not os.path.exists(old_file)
        assert os.path.exists(new_file)
    
    def test_cleanup_with_exclude_patterns(self, clean_manager):
        """测试清理时排除指定模式"""
        # 创建普通旧文件
        old_file = clean_manager.get_temp_path("old_file.txt")
        with open(old_file, 'w') as f:
            f.write("old")
        old_time = time.time() - 48 * 3600
        os.utime(old_file, (old_time, old_time))
        
        # 创建需要保留的目录
        signin_dir = clean_manager.get_temp_path("signin")
        os.makedirs(signin_dir)
        signin_file = os.path.join(signin_dir, "data.json")
        with open(signin_file, 'w') as f:
            f.write("data")
        os.utime(signin_file, (old_time, old_time))
        
        # 清理时排除 signin 目录
        count = clean_manager.cleanup_old_files(
            max_age_hours=24,
            exclude_patterns=["signin"]
        )
        
        assert count == 1  # 只删除了 old_file.txt
        assert not os.path.exists(old_file)
        assert os.path.exists(signin_file)
    
    def test_get_temp_size(self, clean_manager):
        """测试获取临时目录大小"""
        # 创建测试文件
        test_file = clean_manager.get_temp_path("size_test.txt")
        content = "x" * 1000
        with open(test_file, 'w') as f:
            f.write(content)
        
        size = clean_manager.get_temp_size()
        assert size >= 1000
    
    def test_get_temp_size_human(self, clean_manager):
        """测试获取人类可读的大小"""
        test_file = clean_manager.get_temp_path("human_size.txt")
        with open(test_file, 'w') as f:
            f.write("x" * 1024)
        
        size_str = clean_manager.get_temp_size_human()
        assert "KB" in size_str or "B" in size_str
    
    def test_clear_all(self, clean_manager):
        """测试清空所有临时文件"""
        # 创建多个文件
        for i in range(5):
            file_path = clean_manager.get_temp_path(f"file_{i}.txt")
            with open(file_path, 'w') as f:
                f.write("test")
        
        # 清空
        count = clean_manager.clear_all()
        
        assert count == 5
        files = os.listdir(clean_manager.get_temp_path())
        assert len(files) == 0
    
    def test_clear_all_with_exclude(self, clean_manager):
        """测试清空时排除指定模式"""
        # 创建普通文件和排除文件
        normal_file = clean_manager.get_temp_path("normal.txt")
        with open(normal_file, 'w') as f:
            f.write("test")
        
        backup_dir = clean_manager.get_temp_path("backup_temp")
        os.makedirs(backup_dir)
        backup_file = os.path.join(backup_dir, "backup.zip")
        with open(backup_file, 'w') as f:
            f.write("backup")
        
        # 清空时排除 backup_temp
        count = clean_manager.clear_all(exclude_patterns=["backup_temp"])
        
        assert count == 1  # 只删除了 normal.txt
        assert not os.path.exists(normal_file)
        assert os.path.exists(backup_file)


class TestTempFileContext:
    """测试临时文件上下文管理器"""
    
    @pytest.fixture
    def mock_config(self, tmp_path):
        """模拟配置"""
        with patch('app.utils.temp_manager.Config') as mock_cfg:
            mock_cfg.return_value.get_temp_path.return_value = str(tmp_path / "temp")
            yield mock_cfg
    
    @pytest.fixture(autouse=True)
    def reset_manager(self, tmp_path, mock_config):
        """重置管理器"""
        TempManager._instance = None
        TempManager._initialized = False
        test_temp = tmp_path / "temp"
        test_temp.mkdir(exist_ok=True)
        yield
        TempManager._instance = None
        TempManager._initialized = False
    
    def test_temp_file_context_auto_delete(self, tmp_path):
        """测试临时文件上下文自动删除"""
        file_path = None
        
        with temp_file_context(suffix=".txt") as fp:
            file_path = fp
            # 创建文件
            with open(fp, 'w') as f:
                f.write("test")
            assert os.path.exists(fp)
        
        # 退出上下文后文件应被删除
        assert not os.path.exists(file_path)
    
    def test_temp_file_context_no_auto_delete(self, tmp_path):
        """测试临时文件上下文不自动删除"""
        with temp_file_context(suffix=".txt", auto_delete=False) as fp:
            with open(fp, 'w') as f:
                f.write("test")
            assert os.path.exists(fp)
        
        # 退出上下文后文件应保留
        assert os.path.exists(fp)
    
    def test_temp_file_context_with_filename(self, tmp_path):
        """测试指定文件名的临时文件上下文"""
        with temp_file_context(filename="myfile.txt") as fp:
            assert "myfile.txt" in fp
            with open(fp, 'w') as f:
                f.write("test")
            assert os.path.exists(fp)


class TestTempDirContext:
    """测试临时目录上下文管理器"""
    
    @pytest.fixture(autouse=True)
    def reset_manager(self, tmp_path):
        """重置管理器"""
        with patch('app.utils.temp_manager.Config') as mock_cfg:
            mock_cfg.return_value.get_temp_path.return_value = str(tmp_path / "temp")
            TempManager._instance = None
            TempManager._initialized = False
            (tmp_path / "temp").mkdir(exist_ok=True)
            yield
            TempManager._instance = None
            TempManager._initialized = False
    
    def test_temp_dir_context_auto_delete(self, tmp_path):
        """测试临时目录上下文自动删除"""
        dir_path = None
        
        with temp_dir_context() as dp:
            dir_path = dp
            # 创建文件
            test_file = os.path.join(dp, "file.txt")
            with open(test_file, 'w') as f:
                f.write("test")
            assert os.path.exists(dp)
            assert os.path.exists(test_file)
        
        # 退出上下文后目录应被删除
        assert not os.path.exists(dir_path)
    
    def test_temp_dir_context_no_auto_delete(self, tmp_path):
        """测试临时目录上下文不自动删除"""
        with temp_dir_context(auto_delete=False) as dp:
            test_file = os.path.join(dp, "file.txt")
            with open(test_file, 'w') as f:
                f.write("test")
            assert os.path.exists(dp)
        
        # 退出上下文后目录应保留
        assert os.path.exists(dp)


class TestGlobalTempManager:
    """测试全局 temp_manager 实例"""
    
    @pytest.fixture(autouse=True)
    def reset_singleton(self, tmp_path):
        """重置单例"""
        with patch('app.utils.temp_manager.Config') as mock_cfg:
            mock_cfg.return_value.get_temp_path.return_value = str(tmp_path / "temp")
            TempManager._instance = None
            TempManager._initialized = False
            (tmp_path / "temp").mkdir(exist_ok=True)
            yield
            TempManager._instance = None
            TempManager._initialized = False
    
    def test_global_instance(self, tmp_path):
        """测试全局实例可用"""
        assert temp_manager is not None
        
        # 基本功能测试
        path = temp_manager.get_temp_path("test.txt")
        assert path is not None
        assert "test.txt" in path
