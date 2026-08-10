"""向量库工厂

路径解析规则（与项目 settings.data_path 约定一致）：
- 配置为空 → 默认 {settings.data_path}/vectordb/...
- 配置为绝对路径 → 原样使用
- 配置为相对路径 → 基于 settings.data_path 解析

注意：lancedb 预编译原生库要求 AVX2 CPU，不支持的机器 import 即 SIGILL（无法 try/except 防护），
因此仅在通过 CPU 探测后惰性加载 lancedb_store（可选原生依赖隔离，属约定例外）。
"""

import os
import platform
from importlib import import_module

import log
from app.agent.rag.sqlite_vec_store import SQLiteVecStore
from app.agent.rag.vector_store import VectorStore
from app.core.settings import settings


def resolve_store_path(path_setting: str, default_name: str) -> str:
    """按项目路径约定解析向量库存储路径"""
    if not path_setting:
        return os.path.join(settings.data_path, "vectordb", default_name)
    if os.path.isabs(path_setting):
        return path_setting
    return os.path.join(settings.data_path, path_setting)


def _cpu_supports_avx2() -> bool:
    """不导入 lancedb 的 CPU 特性预检（SIGILL 无法用 try/except 拦截）"""
    if platform.system() != "Linux":
        return True  # 非 Linux 无法简单探测，交由用户自负
    try:
        with open("/proc/cpuinfo", encoding="utf-8") as f:
            return "avx2" in f.read()
    except OSError:
        return True


def create_vector_store(cfg: dict, dimension: int = 0) -> VectorStore:
    """按配置创建向量库实例"""
    store_type = cfg.get("type", "sqlite")
    if store_type == "lancedb":
        if not _cpu_supports_avx2():
            raise RuntimeError("当前 CPU 不支持 AVX2，lancedb 不可用，请改用 vector_store: sqlite")
        # 可选原生依赖隔离：lancedb 在不支持的 CPU 上 import 即 SIGILL，只能在探测后惰性加载
        module = import_module("app.agent.rag.lancedb_store")
        path = resolve_store_path((cfg.get("lancedb") or {}).get("path", ""), "lancedb")
        return module.LanceDBStore(path, dimension)
    if store_type != "sqlite":
        log.warn(f"[VectorStore]未知类型 {store_type}，回退 sqlite")
    path = resolve_store_path((cfg.get("sqlite") or {}).get("path", ""), "kb.sqlite")
    return SQLiteVecStore(path, dimension)
