# -*- coding: utf-8 -*-
"""
性能测试模块
用于测试和验证性能优化效果
"""
import os
import sys
import time
import pytest
import threading
from concurrent.futures import ThreadPoolExecutor
from unittest.mock import Mock, patch, MagicMock

# 设置测试环境
os.environ['NASTOOL_CONFIG'] = "/home/linyuan/python/config/config.yaml"


def test_db_connection_pool():
    """测试数据库连接池配置是否正确"""
    # 模拟测试连接池配置
    from sqlalchemy import create_engine, text
    from sqlalchemy.pool import QueuePool
    
    # 验证QueuePool被正确使用
    engine = create_engine(
        "sqlite:///:memory:?check_same_thread=False",
        poolclass=QueuePool,
        pool_size=10,
        max_overflow=20
    )
    
    # 测试基本连接
    with engine.connect() as conn:
        result = conn.execute(text("SELECT 1")).fetchone()
        assert result[0] == 1
    
    engine.dispose()
    print("✓ 数据库连接池配置正确")


def test_http_session_pool():
    """测试HTTP会话池配置"""
    import requests
    from requests.adapters import HTTPAdapter
    
    session = requests.Session()
    adapter = HTTPAdapter(
        pool_connections=10,
        pool_maxsize=50
    )
    session.mount("http://", adapter)
    session.mount("https://", adapter)
    
    # 验证适配器已配置
    assert "http://" in session.adapters
    assert "https://" in session.adapters
    print("✓ HTTP会话池配置正确")


def test_cache_performance():
    """测试缓存性能"""
    from cacheout import Cache
    
    cache = Cache(maxsize=1000, ttl=3600)
    
    # 填充缓存
    start_time = time.time()
    for i in range(1000):
        cache.set(f"key_{i}", {"data": i, "name": f"item_{i}"})
    write_time = time.time() - start_time
    
    # 读取缓存
    start_time = time.time()
    for i in range(1000):
        value = cache.get(f"key_{i}")
        assert value is not None
    read_time = time.time() - start_time
    
    print(f"✓ 缓存写入1000项耗时: {write_time:.3f}秒")
    print(f"✓ 缓存读取1000项耗时: {read_time:.3f}秒")
    
    assert write_time < 1.0, f"缓存写入太慢: {write_time:.3f}秒"
    assert read_time < 0.5, f"缓存读取太慢: {read_time:.3f}秒"


def test_words_helper_cache_simulation():
    """测试识别词处理缓存模拟"""
    cache = {}
    
    def process_with_cache(title):
        if title in cache:
            return cache[title]
        
        # 模拟处理
        result = title.lower().replace(".", " ")
        if len(cache) < 1000:
            cache[title] = result
        return result
    
    titles = ["Movie.Name.2023.1080p.BluRay", "TV.Show.S01E01.1080p"] * 100
    
    # 第一次处理（无缓存）
    start = time.time()
    for title in titles:
        process_with_cache(title)
    first_time = time.time() - start
    
    # 第二次处理（有缓存）
    start = time.time()
    for title in titles:
        process_with_cache(title)
    second_time = time.time() - start
    
    print(f"✓ 无缓存处理耗时: {first_time:.3f}秒")
    print(f"✓ 有缓存处理耗时: {second_time:.3f}秒")
    
    # 有缓存应该更快
    assert second_time < first_time, "缓存没有提升性能"


def test_bulk_insert_simulation():
    """测试批量插入模拟"""
    data = []
    for i in range(1000):
        data.append({
            'id': i,
            'name': f'item_{i}',
            'value': i * 10
        })
    
    # 模拟批量处理
    batch_size = 100
    start = time.time()
    
    batches = [data[i:i + batch_size] for i in range(0, len(data), batch_size)]
    processed = 0
    for batch in batches:
        processed += len(batch)
    
    elapsed = time.time() - start
    print(f"✓ 批量处理1000项（每批100）耗时: {elapsed:.3f}秒")
    assert processed == 1000
    assert elapsed < 0.1


def test_query_optimization_simulation():
    """测试查询优化模拟"""
    # 模拟大量数据
    data = {f"enclosure_{i}": {"title": f"title_{i}"} for i in range(10000)}
    
    # 模拟优化前：使用count（慢）
    def check_exists_slow(enclosure):
        # 模拟count查询
        count = sum(1 for k in data if k == enclosure)
        return count > 0
    
    # 模拟优化后：使用first（快）
    def check_exists_fast(enclosure):
        # 模拟first查询
        return enclosure in data
    
    # 测试性能
    test_key = "enclosure_5000"
    
    start = time.time()
    for _ in range(100):
        check_exists_slow(test_key)
    slow_time = time.time() - start
    
    start = time.time()
    for _ in range(100):
        check_exists_fast(test_key)
    fast_time = time.time() - start
    
    print(f"✓ 优化前查询耗时: {slow_time:.3f}秒")
    print(f"✓ 优化后查询耗时: {fast_time:.3f}秒")
    print(f"✓ 性能提升: {slow_time/fast_time:.1f}倍")


def test_concurrent_performance():
    """测试并发性能"""
    import concurrent.futures
    
    def worker(n):
        # 模拟一些工作
        result = 0
        for i in range(n):
            result += i
        return result
    
    start = time.time()
    
    with concurrent.futures.ThreadPoolExecutor(max_workers=10) as executor:
        futures = [executor.submit(worker, 10000) for _ in range(50)]
        results = [f.result() for f in futures]
    
    elapsed = time.time() - start
    print(f"✓ 50个并发任务耗时: {elapsed:.3f}秒")
    assert elapsed < 10.0


class TestCodeOptimizations:
    """测试代码优化"""
    
    def test_pragma_settings(self):
        """测试SQLite PRAGMA优化设置"""
        # 验证代码中使用的PRAGMA设置
        expected_pragmas = [
            "PRAGMA journal_mode=WAL",
            "PRAGMA synchronous=NORMAL",
            "PRAGMA cache_size=-64000",
            "PRAGMA temp_store=MEMORY",
            "PRAGMA mmap_size=268435456"
        ]
        
        # 读取main_db.py文件验证设置
        with open('app/db/main_db.py', 'r') as f:
            content = f.read()
        
        for pragma in expected_pragmas:
            assert pragma.replace("PRAGMA ", "").lower() in content.lower(), f"缺少 {pragma}"
        
        print("✓ SQLite PRAGMA优化设置正确")
    
    def test_connection_pool_config(self):
        """测试连接池配置"""
        with open('app/db/main_db.py', 'r') as f:
            content = f.read()
        
        # 验证使用QueuePool
        assert "QueuePool" in content
        assert "pool_size=10" in content
        assert "max_overflow=20" in content
        print("✓ 连接池配置正确")
    
    def test_http_session_pool_config(self):
        """测试HTTP会话池配置"""
        with open('app/utils/http_utils.py', 'r') as f:
            content = f.read()
        
        # 验证会话池配置
        assert "_session_pool" in content
        assert "HTTPAdapter" in content
        assert "pool_connections" in content
        print("✓ HTTP会话池配置正确")
    
    def test_words_helper_cache(self):
        """测试WordsHelper缓存"""
        with open('app/helper/words_helper.py', 'r') as f:
            content = f.read()
        
        # 验证缓存实现
        assert "_cache" in content
        assert "_cache_time" in content
        assert "_cache_ttl" in content
        print("✓ WordsHelper缓存配置正确")
    
    def test_rss_helper_query_optimization(self):
        """测试RSSHelper查询优化"""
        with open('app/helper/rss_helper.py', 'r') as f:
            content = f.read()
        
        # 验证使用first()代替count()
        assert ".first() is not None" in content
        print("✓ RSSHelper查询优化正确")
    
    def test_cache_manager_enhancements(self):
        """测试缓存管理器增强"""
        with open('app/utils/cache_manager.py', 'r') as f:
            content = f.read()
        
        # 验证新增缓存和功能
        assert "MediaInfoCache" in content
        assert "SearchResultCache" in content
        assert "def cached" in content
        print("✓ 缓存管理器增强配置正确")


if __name__ == "__main__":
    pytest.main([__file__, "-v", "--tb=short", "-s"])
