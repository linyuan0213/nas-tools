"""
Plugin Registry - 插件注册表
管理插件的扫描、安装、卸载、启用/禁用
"""

import os
import shutil
import time
import zipfile
from typing import Any

import log
from app.core.settings import settings
from app.db.repositories.plugin_framework_repository import PluginFrameworkRepository
from app.domain.entities.plugin import PluginConfigEntity, PluginManifestEntity
from app.plugin_framework.dependency_manager import PluginDependencyManager
from app.schemas.plugin import PluginManifest, PluginState
from app.utils.json_utils import JsonUtils


class PluginRegistry:
    """插件注册表.

    由 lifespan 通过 AppContext 创建并管理生命周期。
    """

    def __init__(self, repo: PluginFrameworkRepository | None = None):
        self._repo = repo or PluginFrameworkRepository()
        self._plugins_dir = os.path.join(settings.data_path, "plugins")
        if not os.path.exists(self._plugins_dir):
            os.makedirs(self._plugins_dir)
        self._builtin_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "builtin_plugins")
        self._manifest_cache: dict[str, PluginManifest] = {}
        self._state_cache: dict[str, PluginState] = {}
        self._last_builtin_scan: float = 0.0
        self._load_all()
        self._scan_builtin_plugins()

    def _load_all(self):
        """从数据库加载所有已安装插件"""
        try:
            orm_list = self._repo.get_all_manifests()
            for orm_model in orm_list:
                try:
                    entity = PluginManifestEntity.from_orm(orm_model)
                    if not entity:
                        continue
                    manifest = PluginManifest.from_dict(JsonUtils.loads(entity.manifest_json or "{}"))
                    self._manifest_cache[manifest.id] = manifest
                    self._state_cache[manifest.id] = PluginState(
                        id=manifest.id,
                        enabled=entity.enabled,
                        installed=getattr(orm_model, "INSTALLED", True),
                        manifest=manifest,
                    )
                except Exception as e:
                    log.error(f"[PluginRegistry] 加载插件清单失败: {e}")
        except Exception as e:
            log.warn(f"[PluginRegistry] 加载插件清单表失败（可能表尚未创建）: {e}")

    def scan(self) -> list[PluginManifest]:
        """扫描 plugins 目录，返回所有已安装插件的清单"""
        if not self._manifest_cache:
            self._load_all()
        # 重新扫描内置插件（支持热新增），但限制频率避免每次 API 调用都读写数据库
        now = time.time()
        if now - self._last_builtin_scan > 60:
            self._scan_builtin_plugins()
            self._last_builtin_scan = now
        return list(self._manifest_cache.values())

    def get(self, plugin_id: str) -> PluginManifest | None:
        """获取指定插件的清单"""
        return self._manifest_cache.get(plugin_id)

    def get_state(self, plugin_id: str) -> PluginState | None:
        """获取插件状态"""
        return self._state_cache.get(plugin_id)

    def install(self, zip_path: str) -> PluginManifest:
        """安装插件包"""
        if not os.path.exists(zip_path):
            raise FileNotFoundError(f"插件包不存在: {zip_path}")

        extract_dir = os.path.join(self._plugins_dir, "__tmp_install")
        if os.path.exists(extract_dir):
            shutil.rmtree(extract_dir)
        os.makedirs(extract_dir)

        with zipfile.ZipFile(zip_path, "r") as z:
            z.extractall(extract_dir)

        manifest_path = os.path.join(extract_dir, "manifest.json")
        if not os.path.exists(manifest_path):
            shutil.rmtree(extract_dir)
            raise ValueError("插件包缺少 manifest.json")

        with open(manifest_path, encoding="utf-8") as f:
            manifest_data = JsonUtils.load(f)

        manifest = PluginManifest.from_dict(manifest_data)
        if not manifest.id or not manifest.name:
            shutil.rmtree(extract_dir)
            raise ValueError("manifest.json 缺少 id 或 name")

        target_dir = os.path.join(self._plugins_dir, f"{manifest.id}-{manifest.version}")
        if os.path.exists(target_dir):
            shutil.rmtree(target_dir)
        shutil.move(extract_dir, target_dir)

        # 安装插件依赖
        deps = manifest.backend.dependencies
        if deps:
            ok, err = PluginDependencyManager.install_dependencies(
                dependencies=deps,
                plugin_id=manifest.id,
                plugin_path=target_dir,
            )
            if not ok:
                # 依赖安装失败，回滚
                shutil.rmtree(target_dir)
                raise RuntimeError(f"插件依赖安装失败: {err}")

        self._save_manifest(manifest, target_dir, enabled=False)
        self._manifest_cache[manifest.id] = manifest
        self._state_cache[manifest.id] = PluginState(
            id=manifest.id,
            enabled=False,
            installed=True,
            manifest=manifest,
        )

        log.info(f"[PluginRegistry] 插件安装成功: {manifest.id}@{manifest.version}")
        return manifest

    def uninstall(self, plugin_id: str) -> None:
        """卸载插件"""
        state = self._state_cache.get(plugin_id)
        if not state:
            raise ValueError(f"插件未安装: {plugin_id}")
        if not state.manifest:
            raise ValueError(f"插件状态数据不完整: {plugin_id}")

        target_dir = os.path.join(self._plugins_dir, f"{plugin_id}-{state.manifest.version}")
        if os.path.exists(target_dir):
            shutil.rmtree(target_dir)

        self._repo.delete_manifest(plugin_id)
        self._repo.delete_config(plugin_id)

        self._manifest_cache.pop(plugin_id, None)
        self._state_cache.pop(plugin_id, None)

        log.info(f"[PluginRegistry] 插件卸载成功: {plugin_id}")

    def enable(self, plugin_id: str) -> None:
        """启用插件"""
        state = self._state_cache.get(plugin_id)
        if not state:
            raise ValueError(f"插件未安装: {plugin_id}")

        self._repo.set_manifest_enabled(plugin_id, True)
        state.enabled = True
        log.info(f"[PluginRegistry] 插件已启用: {plugin_id}")

    def disable(self, plugin_id: str) -> None:
        """禁用插件"""
        state = self._state_cache.get(plugin_id)
        if not state:
            raise ValueError(f"插件未安装: {plugin_id}")

        self._repo.set_manifest_enabled(plugin_id, False)
        state.enabled = False
        log.info(f"[PluginRegistry] 插件已禁用: {plugin_id}")

    def get_config(self, plugin_id: str) -> dict:
        """获取插件配置"""
        orm_model = self._repo.get_config(plugin_id)
        if orm_model:
            entity = PluginConfigEntity.from_orm(orm_model)
            return entity.config if entity else {}
        return {}

    def save_config(self, plugin_id: str, config: dict) -> None:
        """保存插件配置"""
        entity = PluginConfigEntity(plugin_id=plugin_id, config=config)
        self._repo.save_config(entity)

        state = self._state_cache.get(plugin_id)
        if state:
            state.config = config

    def _save_manifest(self, manifest: PluginManifest, path: str, enabled: bool = False, installed: bool = True):
        """保存插件清单到数据库（已存在同 id 记录时更新而非插入，避免重复安装/残留清单冲突）"""
        entity = PluginManifestEntity(
            id=manifest.id,
            name=manifest.name,
            version=manifest.version,
            author=manifest.author,
            description=manifest.description,
            category=manifest.category,
            tags=manifest.tags,
            icon=manifest.icon,
            color=manifest.color,
            manifest_json=JsonUtils.dumps(manifest.to_dict(), ensure_ascii=False),
            enabled=enabled,
            installed=installed,
            path=path,
        )
        existing = self._repo.get_manifest_by_id(manifest.id)
        if existing is not None:
            self._repo.update_manifest(entity)
        else:
            self._repo.insert_manifest(entity)

    @staticmethod
    def _normalize_manifest_dict(value: Any) -> Any:
        """递归移除 dict/list 中的 None 值，用于 manifest 比较."""
        if isinstance(value, dict):
            return {k: PluginRegistry._normalize_manifest_dict(v) for k, v in value.items() if v is not None}
        if isinstance(value, list):
            return [PluginRegistry._normalize_manifest_dict(v) for v in value if v is not None]
        return value

    def _scan_builtin_plugins(self):
        """扫描内置插件目录，自动注册或更新内置插件"""
        if not os.path.exists(self._builtin_dir):
            return
        for entry in os.listdir(self._builtin_dir):
            manifest_path = os.path.join(self._builtin_dir, entry, "manifest.json")
            if not os.path.exists(manifest_path):
                continue
            try:
                with open(manifest_path, encoding="utf-8") as f:
                    manifest_data = JsonUtils.load(f)
                manifest = PluginManifest.from_dict(manifest_data)
                if not manifest.id or not manifest.name:
                    continue
                plugin_dir = os.path.join(self._builtin_dir, entry)
                existing_state = self._state_cache.get(manifest.id)
                existing_orm = self._repo.get_manifest_by_id(manifest.id)
                if existing_state or existing_orm:
                    # 更新现有内置插件的 manifest
                    # 始终以数据库为准，缓存可能未及时同步
                    existing_enabled = (
                        bool(existing_orm.ENABLED)
                        if existing_orm
                        else (existing_state.enabled if existing_state else False)
                    )
                    existing_installed = (
                        bool(getattr(existing_orm, "INSTALLED", True))
                        if existing_orm
                        else (existing_state.installed if existing_state else True)
                    )
                    new_manifest_dict = manifest.to_dict()
                    stored_manifest_dict = JsonUtils.loads(existing_orm.MANIFEST_JSON or "{}")
                    normalized_stored = self._normalize_manifest_dict(stored_manifest_dict)
                    normalized_new = self._normalize_manifest_dict(new_manifest_dict)
                    if existing_orm and normalized_stored == normalized_new:
                        # manifest 未变化，跳过数据库写入，仅更新内存缓存
                        if existing_state:
                            existing_state.manifest = manifest
                            existing_state.enabled = existing_enabled
                            existing_state.installed = existing_installed
                        self._manifest_cache[manifest.id] = manifest
                        continue
                    if existing_state:
                        existing_state.manifest = manifest
                        existing_state.enabled = existing_enabled
                        existing_state.installed = existing_installed
                    self._manifest_cache[manifest.id] = manifest
                    self._repo.update_manifest(
                        PluginManifestEntity(
                            id=manifest.id,
                            name=manifest.name,
                            version=manifest.version,
                            author=manifest.author,
                            description=manifest.description,
                            category=manifest.category,
                            tags=manifest.tags,
                            icon=manifest.icon,
                            color=manifest.color,
                            manifest_json=JsonUtils.dumps(new_manifest_dict, ensure_ascii=False),
                            enabled=existing_enabled,
                            installed=existing_installed,
                            path=plugin_dir,
                        )
                    )
                    log.info(f"[PluginRegistry] 内置插件已更新: {manifest.id}@{manifest.version}")
                else:
                    # 新注册（默认未安装）
                    self._save_manifest(manifest, plugin_dir, enabled=False, installed=False)
                    self._manifest_cache[manifest.id] = manifest
                    self._state_cache[manifest.id] = PluginState(
                        id=manifest.id,
                        enabled=False,
                        installed=False,
                        manifest=manifest,
                    )
                    log.info(f"[PluginRegistry] 内置插件已注册: {manifest.id}@{manifest.version}")
            except Exception as e:
                log.error(f"[PluginRegistry] 扫描内置插件 {entry} 失败: {e}")

    def get_plugin_path(self, plugin_id: str) -> str | None:
        """获取插件目录路径"""
        state = self._state_cache.get(plugin_id)
        if not state:
            return None
        if not state.manifest:
            return None
        builtin_path = os.path.join(self._builtin_dir, f"{plugin_id}-{state.manifest.version}")
        if os.path.exists(builtin_path):
            return builtin_path
        builtin_path2 = os.path.join(self._builtin_dir, plugin_id)
        if os.path.exists(builtin_path2):
            return builtin_path2
        user_path = os.path.join(self._plugins_dir, f"{plugin_id}-{state.manifest.version}")
        if os.path.exists(user_path):
            return user_path
        log.warn(f"[PluginRegistry] 插件文件缺失: {plugin_id}，路径 {user_path} 不存在")
        return None
