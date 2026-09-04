"""
Plugin Framework Service
插件框架 v2 业务服务层
"""

import contextlib
import os
import shutil
import tempfile
import threading
import zipfile

import log
from app.core.error_codes import ErrorCode
from app.core.exceptions import (
    PluginError,
    PluginHotReloadError,
    PluginInstallingError,
    PluginManifestInvalidError,
    PluginNotInstalledError,
)
from app.core.settings import settings
from app.db.repositories.plugin_framework_repository import PluginFrameworkRepository
from app.db.repositories.rbac_repo_adapter import RBACMenuRepositoryAdapter, RBACRoleRepositoryAdapter
from app.domain.entities.plugin import PluginConfigEntity, PluginManifestEntity
from app.infrastructure.distributed_lock.lock_manager import get_lock_manager
from app.plugin_framework.registry import PluginRegistry
from app.plugin_framework.sandbox import PluginSandbox
from app.schemas.plugin import PluginManifest
from app.utils.json_utils import JsonUtils


class PluginFrameworkService:
    """插件框架业务服务"""

    def __init__(
        self,
        repo: PluginFrameworkRepository,
        menu_repo: RBACMenuRepositoryAdapter,
        role_repo: RBACRoleRepositoryAdapter,
        plugin_registry: PluginRegistry,
        plugin_sandbox: PluginSandbox,
        hook_system=None,
    ):
        self._repo = repo
        self._menu_repo = menu_repo
        self._role_repo = role_repo
        self._plugin_registry = plugin_registry
        self._plugin_sandbox = plugin_sandbox
        self._hook_system = hook_system
        self._plugins_dir = os.path.join(settings.data_path, "plugins")
        if not os.path.exists(self._plugins_dir):
            os.makedirs(self._plugins_dir)

    def _get_hook_system(self):
        return self._hook_system or self._get_hook_system()

    def _get_plugin_parent_menu(self):
        """获取 Plugin 父菜单"""
        return self._menu_repo.get_menu_by_code("Plugin")

    def _sync_plugin_menus(self, plugin_id: str) -> None:
        """
        为插件 frontend routes 创建 RBAC 菜单，并分配给有 Plugin 权限的角色。
        """
        manifest = self.get_manifest(plugin_id)
        if not manifest or not manifest.frontend or not manifest.frontend.routes:
            return

        root_parent = self._get_plugin_parent_menu()
        if not root_parent:
            log.warn("[PluginFrameworkService] Plugin 父菜单不存在，跳过菜单同步")
            return

        # 1. 为插件创建父菜单（作为收起项）
        plugin_parent_code = f"Plugin_{plugin_id}"
        plugin_parent = self._menu_repo.get_menu_by_code(plugin_parent_code)
        if not plugin_parent:
            result = self._menu_repo.create_menu(
                menu_name=manifest.name,
                menu_code=plugin_parent_code,
                parent_id=root_parent.id,
                path=f"/plugin/{plugin_id}",
                icon=manifest.icon or "lucide:puzzle",
                component="",
                sort_order=100,
                menu_level=2,
                permission_code="plugin:view",
                hide_in_menu=0,
            )
            plugin_parent = result if hasattr(result, "id") else self._menu_repo.get_menu_by_code(plugin_parent_code)
        else:
            # 与默认菜单一致：仅确保启用与技术路由，保留用户自定义（名称/图标/排序/显隐/父级）
            parent_updates: dict = {"status": 1}
            if plugin_parent.path != f"/plugin/{plugin_id}":
                parent_updates["path"] = f"/plugin/{plugin_id}"
            self._menu_repo.update_menu(plugin_parent.id, **parent_updates)

        if not plugin_parent:
            return

        new_menu_ids = [plugin_parent.id]
        for idx, route in enumerate(manifest.frontend.routes):
            if not route.menu:
                continue

            safe_path = route.path.strip("/").replace("/", "_") or "index"
            menu_code = f"Plugin_{plugin_id}_{safe_path}"
            menu_name = route.title or manifest.name
            menu_icon = route.icon or "lucide:puzzle"
            base_path = f"/plugin/{plugin_id}"
            full_path = route.path if route.path.startswith("/") else f"{base_path}/{route.path}"

            existing = self._menu_repo.get_menu_by_code(menu_code)
            if existing:
                # 与默认菜单一致：仅确保启用与技术路由，保留用户自定义（名称/图标/排序/显隐/父级）
                child_updates: dict = {"status": 1}
                if existing.path != full_path:
                    child_updates["path"] = full_path
                self._menu_repo.update_menu(existing.id, **child_updates)
                new_menu_ids.append(existing.id)
                continue

            result = self._menu_repo.create_menu(
                menu_name=menu_name,
                menu_code=menu_code,
                parent_id=plugin_parent.id,
                path=full_path,
                icon=menu_icon,
                component="",
                sort_order=100 + idx,
                menu_level=3,
                permission_code="plugin:view",
                hide_in_menu=0,
            )
            menu = result if hasattr(result, "id") else self._menu_repo.get_menu_by_code(menu_code)
            if menu:
                new_menu_ids.append(menu.id)
                log.info(f"[PluginFrameworkService] 创建插件菜单: {menu_code} -> {full_path}")

        if len(new_menu_ids) > 1:
            self._assign_menus_to_authorized_roles(new_menu_ids)

    def _remove_plugin_menus(self, plugin_id: str) -> None:
        """
        删除插件对应的 RBAC 菜单（含插件父菜单及子路由菜单）。
        """
        plugin_parent_code = f"Plugin_{plugin_id}"
        plugin_parent = self._menu_repo.get_menu_by_code(plugin_parent_code)
        removed = 0
        if plugin_parent:
            children = self._menu_repo.get_children_menus(plugin_parent.id)
            for child in children:
                self._menu_repo.delete_menu(child.id)
                removed += 1
            self._menu_repo.delete_menu(plugin_parent.id)
            removed += 1
        else:
            # 兼容旧版：路由菜单直接挂在 Plugin 下
            root = self._get_plugin_parent_menu()
            if root:
                children = self._menu_repo.get_children_menus(root.id)
                prefix = f"Plugin_{plugin_id}_"
                for child in children:
                    if child.menu_code.startswith(prefix):
                        self._menu_repo.delete_menu(child.id)
                        removed += 1
        if removed:
            log.info(f"[PluginFrameworkService] 共删除 {removed} 个插件菜单")

    def _assign_menus_to_authorized_roles(self, menu_ids: list[int]) -> None:
        """
        将菜单分配给拥有 Plugin 父菜单权限的角色。
        """
        if not menu_ids:
            return

        parent_menu = self._get_plugin_parent_menu()
        if not parent_menu:
            return

        roles = self._role_repo.get_all_roles(status=1)
        for role in roles:
            if not role.menus:
                continue
            # 检查该角色是否拥有 Plugin 父菜单
            has_plugin = any(m.get("menu_code") == "Plugin" or m.get("id") == parent_menu.id for m in role.menus)
            if not has_plugin:
                continue

            # 收集角色当前所有菜单 ID（去重）
            current_ids = {int(mid) for m in role.menus if (mid := m.get("id")) is not None}
            current_ids.update(menu_ids)
            self._role_repo.assign_menus_to_role(role.id, list(current_ids))
            log.info(f"[PluginFrameworkService] 为角色 '{role.role_name}' 分配 {len(menu_ids)} 个插件菜单")

    def list_plugins(self) -> list[dict]:
        """列出所有已安装插件"""
        # 先扫描内置插件（热新增）

        self._plugin_registry.scan()
        orm_list = self._repo.get_all_manifests()
        plugins = []
        for orm_model in orm_list:
            try:
                manifest = PluginManifest.from_dict(JsonUtils.loads(str(orm_model.MANIFEST_JSON or "{}")))
                plugins.append(
                    {
                        "id": manifest.id,
                        "name": manifest.name,
                        "version": manifest.version,
                        "author": manifest.author,
                        "description": manifest.description,
                        "category": manifest.category,
                        "tags": manifest.tags,
                        "icon": manifest.icon,
                        "color": manifest.color,
                        "enabled": bool(orm_model.ENABLED),
                        "is_builtin": bool(orm_model.PATH and "builtin_plugins" in orm_model.PATH),
                        "installed": bool(getattr(orm_model, "INSTALLED", True)),
                        "supports_run": manifest.backend.supports_run,
                        "has_config": bool(
                            manifest.frontend and manifest.frontend.settings and manifest.frontend.settings.fields
                        ),
                        "backend": {
                            "entry": manifest.backend.entry,
                            "api_prefix": manifest.backend.api_prefix,
                            "hooks": manifest.backend.hooks,
                            "supports_run": manifest.backend.supports_run,
                        },
                        "frontend": {
                            "routes": [
                                {
                                    "path": r.path,
                                    "component": r.component,
                                    "title": r.title,
                                    "icon": r.icon,
                                    "menu": r.menu,
                                }
                                for r in manifest.frontend.routes
                            ],
                            "slots": [
                                {"target": s.target, "position": s.position, "component": s.component}
                                for s in manifest.frontend.slots
                            ],
                        },
                    }
                )
            except Exception as e:
                log.error(f"[PluginFrameworkService] 解析插件清单失败: {e}")
        return plugins

    def list_enabled_agent_tools(self) -> list[dict]:
        """已启用插件声明的 Agent 工具（供 ToolExecutor 动态合并，作为能力清单）"""
        tools: list[dict] = []
        try:
            orm_list = self._repo.get_all_manifests()
        except Exception as e:  # noqa: BLE001
            log.warn(f"[PluginFrameworkService]读取插件清单失败，插件工具不可用: {e}")
            return tools
        for orm_model in orm_list:
            if not bool(getattr(orm_model, "ENABLED", False)):
                continue
            try:
                manifest = PluginManifest.from_dict(JsonUtils.loads(str(orm_model.MANIFEST_JSON or "{}")))
            except Exception:  # noqa: BLE001
                continue
            for t in manifest.backend.tools:
                if not t.name:
                    continue
                tools.append(
                    {
                        "plugin_id": manifest.id,
                        "name": t.name,
                        "description": t.description,
                        "parameters": t.parameters or {},
                        "level": t.level,
                        "permission": t.permission,
                    }
                )
        return tools

    def call_agent_tool(self, plugin_id: str, name: str, arguments: dict):
        """调用插件 backend.agent_tool(name, arguments)

        插件返回约定为 {success: bool, data: …, error: str}（data 缺省视为成功数据），
        由 ToolExecutor 统一转换为 ToolResult。
        """
        return self._plugin_sandbox.call(plugin_id, "agent_tool", name, arguments)

    def get_manifest(self, plugin_id: str) -> PluginManifest | None:
        """获取插件完整 manifest"""
        orm_model = self._repo.get_manifest_by_id(plugin_id)
        if not orm_model:
            return None
        return PluginManifest.from_dict(JsonUtils.loads(str(orm_model.MANIFEST_JSON or "{}")))

    def get_config(self, plugin_id: str) -> dict:
        """获取插件配置"""
        orm_model = self._repo.get_config(plugin_id)
        if orm_model and str(orm_model.CONFIG or ""):
            try:
                return JsonUtils.loads(str(orm_model.CONFIG))
            except Exception as e:  # noqa: BLE001
                log.debug(f"[PluginFrameworkService]忽略异常: {e}")
        return {}

    def get_config_fields(self, plugin_id: str) -> list[dict]:
        """获取插件配置字段定义"""
        manifest = self.get_manifest(plugin_id)
        fields = []
        if manifest and manifest.frontend and manifest.frontend.settings:
            for f in manifest.frontend.settings.fields:
                fields.append(
                    {
                        "key": f.key,
                        "type": f.type,
                        "label": f.label,
                        "default": f.default,
                        "placeholder": f.placeholder,
                        "options": f.options,
                        "source": f.source,
                        "multiple": f.multiple,
                        "required": f.required,
                        "help": f.help,
                    }
                )
        return fields

    def save_config(self, plugin_id: str, config: dict) -> None:
        """保存插件配置"""
        entity = PluginConfigEntity(plugin_id=plugin_id, config=config)
        self._repo.save_config(entity)
        self._get_hook_system().emit("plugin.config_changed", {"plugin_id": plugin_id, "config": config})

    def install(self, zip_path: str) -> PluginManifest:
        """安装插件包（多实例部署时通过分布式锁保证只有一个实例执行安装）"""
        if not os.path.exists(zip_path):
            raise FileNotFoundError(f"插件包不存在: {zip_path}")

        lock_key = f"plugin:install:{os.path.basename(zip_path)}"
        lock = get_lock_manager().create_lock(lock_key, ttl_seconds=300)
        acquired = lock.acquire()
        if not acquired:
            log.info(f"[Plugin]插件安装正在进行中，跳过: {zip_path}")
            raise PluginInstallingError("插件安装正在执行中，请稍后再试")

        try:
            return self._do_install(zip_path)
        finally:
            lock.release()

    def _do_install(self, zip_path: str) -> PluginManifest:
        """实际安装逻辑"""
        extract_dir = os.path.join(self._plugins_dir, "__tmp_install")
        if os.path.exists(extract_dir):
            shutil.rmtree(extract_dir)
        os.makedirs(extract_dir)

        with zipfile.ZipFile(zip_path, "r") as z:
            z.extractall(extract_dir)

        manifest_path = os.path.join(extract_dir, "manifest.json")
        # zip 命令压缩文件夹后，解压出来的根目录是一个子文件夹（如 hello_world/）
        if not os.path.exists(manifest_path):
            for entry in os.listdir(extract_dir):
                subdir = os.path.join(extract_dir, entry)
                if os.path.isdir(subdir):
                    candidate = os.path.join(subdir, "manifest.json")
                    if os.path.exists(candidate):
                        manifest_path = candidate
                        break

        if not os.path.exists(manifest_path):
            shutil.rmtree(extract_dir)
            raise PluginManifestInvalidError("插件包缺少 manifest.json")

        with open(manifest_path, encoding="utf-8") as f:
            manifest_data = JsonUtils.load(f)

        manifest = PluginManifest.from_dict(manifest_data)
        if not manifest.id or not manifest.name:
            shutil.rmtree(extract_dir)
            raise PluginManifestInvalidError("manifest.json 缺少 id 或 name")

        # manifest 所在的真实目录（处理 macOS 压缩的子文件夹情况）
        plugin_root = os.path.dirname(manifest_path)
        target_dir = os.path.join(self._plugins_dir, f"{manifest.id}-{manifest.version}")
        if os.path.exists(target_dir):
            shutil.rmtree(target_dir)
        os.makedirs(target_dir)
        # 将插件内容移到目标目录
        for item in os.listdir(plugin_root):
            shutil.move(os.path.join(plugin_root, item), target_dir)
        # 清理临时目录
        if os.path.exists(extract_dir):
            shutil.rmtree(extract_dir)

        # 检查是否已存在同名插件
        existing = self._repo.get_manifest_by_id(manifest.id)
        new_manifest_json = JsonUtils.dumps(manifest.to_dict(), ensure_ascii=False)

        if existing:
            existing_manifest_json = str(existing.MANIFEST_JSON or "{}")
            if existing_manifest_json == new_manifest_json:
                # manifest 完全相同，无需重复安装
                if os.path.exists(target_dir):
                    shutil.rmtree(target_dir)
                log.info(f"[PluginFrameworkService] 插件 {manifest.id} 已存在且 manifest 一致，跳过安装")
                return manifest

            # manifest 不同，视为版本更新
            if bool(existing.ENABLED):
                self.disable(manifest.id)
            old_path = str(existing.PATH or "")
            if old_path and os.path.exists(old_path) and old_path != target_dir:
                shutil.rmtree(old_path)
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
                manifest_json=new_manifest_json,
                enabled=False,
                path=target_dir,
            )
            ok = self._repo.update_manifest(entity)
            if not ok:
                raise PluginError("插件清单更新数据库失败", errcode=ErrorCode.DATABASE_ERROR, http_status=500)
            log.info(f"[PluginFrameworkService] 插件更新成功: {manifest.id}@{manifest.version}")
        else:
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
                enabled=False,
                path=target_dir,
            )
            ok = self._repo.insert_manifest(entity)
            if not ok:
                raise PluginError("插件清单写入数据库失败", errcode=ErrorCode.DATABASE_ERROR, http_status=500)
            log.info(f"[PluginFrameworkService] 插件安装成功: {manifest.id}@{manifest.version}")

        self._get_hook_system().emit("plugin.install", {"plugin_id": manifest.id})
        return manifest

    def uninstall(self, plugin_id: str) -> None:
        """卸载插件（多实例部署时通过分布式锁保证只有一个实例执行）"""
        lock_key = f"plugin:uninstall:{plugin_id}"
        lock = get_lock_manager().create_lock(lock_key, ttl_seconds=300)
        acquired = lock.acquire()
        if not acquired:
            log.info(f"[Plugin]插件卸载正在进行中，跳过: {plugin_id}")
            raise PluginInstallingError("插件卸载正在执行中，请稍后再试")

        try:
            self._do_uninstall(plugin_id)
        finally:
            lock.release()

    def _do_uninstall(self, plugin_id: str) -> None:
        """实际卸载逻辑"""
        orm_model = self._repo.get_manifest_by_id(plugin_id)
        if not orm_model:
            raise PluginNotInstalledError(f"插件未安装: {plugin_id}")

        old_path = str(orm_model.PATH or "")
        target_dir = old_path
        is_builtin = bool(target_dir and "builtin_plugins" in target_dir)

        if is_builtin:
            # 内置插件软卸载：禁用 + 标记为未安装（不删除文件）
            if bool(orm_model.ENABLED):
                self.disable(plugin_id)
            self._repo.set_manifest_installed(plugin_id, False)
            # 同步更新 Registry 缓存，避免扫描时覆盖数据库

            state = self._plugin_registry.get_state(plugin_id)
            if state:
                state.installed = False
                state.enabled = False
            self._get_hook_system().emit("plugin.uninstall", {"plugin_id": plugin_id})
            log.info(f"[PluginFrameworkService] 内置插件软卸载: {plugin_id}")
            return

        # 第三方插件硬卸载：物理删除
        if target_dir and os.path.exists(str(target_dir)):
            shutil.rmtree(str(target_dir))

        sandbox = self._plugin_sandbox
        sandbox.unload(plugin_id)
        self._get_hook_system().unregister_all(plugin_id)

        # 删除插件菜单
        self._remove_plugin_menus(plugin_id)

        self._repo.delete_manifest(plugin_id)
        self._repo.delete_config(plugin_id)

        self._get_hook_system().emit("plugin.uninstall", {"plugin_id": plugin_id})
        log.info(f"[PluginFrameworkService] 插件卸载成功: {plugin_id}")

    def install_market_plugin(self, zip_bytes: bytes, enabled: bool = True) -> dict:
        """市场来源安装：写临时 zip → registry.install（默认禁用落盘）→ 可选启用加载

        返回 {plugin_id, name, version}；安装器已做 sha256/SAST 门禁，这里不再重复。
        """
        fd, tmp_path = tempfile.mkstemp(suffix=".zip", prefix="nexus_market_")
        try:
            with os.fdopen(fd, "wb") as f:
                f.write(zip_bytes)
            manifest = self._plugin_registry.install(tmp_path)
        finally:
            if os.path.exists(tmp_path):
                with contextlib.suppress(OSError):
                    os.unlink(tmp_path)
        if enabled:
            self.enable(manifest.id)
            threading.Thread(target=self._do_enable, args=(manifest.id,), daemon=True).start()
        return {"plugin_id": manifest.id, "name": manifest.name, "version": manifest.version}

    def update_market_plugin(self, zip_bytes: bytes, plugin_id: str) -> dict:
        """市场来源更新：卸载旧实例（配置保留）→ 装新版本 → 启用加载

        PLUGIN_CONFIG 按 plugin_id 存储且安装不删除，配置天然跨版本保留。
        """
        sandbox = self._plugin_sandbox
        if sandbox.get_plugin_instance(plugin_id) is not None:
            sandbox.unload(plugin_id)
        return self.install_market_plugin(zip_bytes, enabled=True)

    def _do_enable(self, plugin_id: str) -> None:
        """后台线程执行插件加载和初始化"""
        try:
            log.info(f"[PluginFrameworkService] 开始加载插件: {plugin_id}")
            sandbox = self._plugin_sandbox
            ok = sandbox.load(plugin_id)
            if ok:
                self._get_hook_system().emit("plugin.enable", {"plugin_id": plugin_id})
                log.info(f"[PluginFrameworkService] 插件已启用: {plugin_id}")
            else:
                log.error(f"[PluginFrameworkService] 插件加载返回失败: {plugin_id}")
        except Exception as e:
            log.error(f"[PluginFrameworkService] 插件后台加载异常 {plugin_id}: {e}")

    def refresh_plugin_menus_at_startup(self) -> None:
        """启动时：同步已启用插件的菜单，清理已卸载插件的残留菜单."""
        enabled_ids = self._repo.get_enabled_plugin_ids()
        enabled_codes = {f"Plugin_{pid}" for pid in enabled_ids}

        # 1. 同步已启用插件的菜单
        for plugin_id in enabled_ids:
            self._sync_plugin_menus(plugin_id)

        # 2. 清理已卸载/禁用插件的残留菜单（含插件父菜单）
        parent_menu = self._get_plugin_parent_menu()
        if not parent_menu:
            return
        children = self._menu_repo.get_children_menus(parent_menu.id)
        for child in children:
            if not child.menu_code.startswith("Plugin_"):
                continue
            belongs_to_enabled = any(child.menu_code.startswith(c) for c in enabled_codes)
            if not belongs_to_enabled:
                self._menu_repo.delete_menu(child.id)
                log.info(f"[PluginFrameworkService] 清理残留菜单: {child.menu_code}")

    def enable(self, plugin_id: str) -> None:
        """启用插件（更新数据库和注册表缓存）"""
        orm_model = self._repo.get_manifest_by_id(plugin_id)
        if not orm_model:
            raise PluginNotInstalledError(f"插件未安装: {plugin_id}")

        # 首次启用时标记为已安装
        if not getattr(orm_model, "INSTALLED", True):
            self._repo.set_manifest_installed(plugin_id, True)

        self._repo.set_manifest_enabled(plugin_id, True)

        # 同步插件菜单到 RBAC
        self._sync_plugin_menus(plugin_id)

        # 同步更新注册表缓存，否则后台线程加载时缓存仍为 False

        state = self._plugin_registry.get_state(plugin_id)
        if state:
            state.enabled = True
            state.installed = True

    def disable(self, plugin_id: str) -> None:
        """禁用插件"""
        orm_model = self._repo.get_manifest_by_id(plugin_id)
        if not orm_model:
            raise PluginNotInstalledError(f"插件未安装: {plugin_id}")

        sandbox = self._plugin_sandbox
        sandbox.unload(plugin_id)
        self._repo.set_manifest_enabled(plugin_id, False)

        # 删除插件菜单
        self._remove_plugin_menus(plugin_id)

        # 同步更新注册表缓存

        state = self._plugin_registry.get_state(plugin_id)
        if state:
            state.enabled = False

        self._get_hook_system().emit("plugin.disable", {"plugin_id": plugin_id})
        log.info(f"[PluginFrameworkService] 插件已禁用: {plugin_id}")

    def get_logs(self, plugin_id: str, page: int = 1, page_size: int = 20) -> dict:
        """获取插件日志"""
        records = self._repo.get_logs_by_plugin(plugin_id, page, page_size)
        total = self._repo.count_logs_by_plugin(plugin_id)

        items = []
        for r in records:
            items.append(
                {
                    "id": r.ID,
                    "level": r.LEVEL,
                    "message": r.MESSAGE,
                    "created_at": r.CREATED_AT,
                }
            )

        return {"total": total, "items": items}

    def clear_logs(self, plugin_id: str) -> None:
        """清空插件日志"""
        self._repo.clear_logs_by_plugin(plugin_id)

    def get_readme(self, plugin_id: str) -> str:
        """获取插件 README"""
        orm_model = self._repo.get_manifest_by_id(plugin_id)
        plugin_path = str(orm_model.PATH or "") if orm_model else ""
        if not plugin_path:
            return ""

        readme_path = os.path.join(plugin_path, "README.md")
        if not os.path.exists(readme_path):
            return ""

        with open(readme_path, encoding="utf-8") as f:
            return f.read()

    def get_plugin_path(self, plugin_id: str) -> str | None:
        """获取插件目录路径.

        优先使用数据库中记录的安装路径；若该路径已不存在，
        回退到 PluginRegistry 的实时路径解析，避免数据目录变更后插件丢失。
        """
        orm_model = self._repo.get_manifest_by_id(plugin_id)
        if orm_model and orm_model.PATH and os.path.exists(orm_model.PATH):
            return str(orm_model.PATH)
        return self._plugin_registry.get_plugin_path(plugin_id)

    def run_plugin(self, plugin_id: str) -> None:
        """立即运行插件（临时加载并调用 run 方法）"""
        lock_key = f"plugin:run:{plugin_id}"
        lock = get_lock_manager().create_lock(lock_key, ttl_seconds=300)
        acquired = lock.acquire()
        if not acquired:
            log.info(f"[Plugin]插件 {plugin_id} 正在运行中，跳过")
            return

        try:
            self._do_run_plugin(plugin_id)
        finally:
            lock.release()

    def _do_run_plugin(self, plugin_id: str) -> None:
        """实际运行插件逻辑（委托 sandbox 进行依赖注入）。"""
        request_client = self.__dict__.get("_request_client") or self.__class__.__dict__.get("_request_client")
        if request_client:
            request_client.close()
        if not self._plugin_sandbox.load(plugin_id):
            raise PluginError(f"插件 {plugin_id} 加载失败", errcode=ErrorCode.PLUGIN_LOAD_FAILED)

        instance = self._plugin_sandbox._instances.get(plugin_id)
        if not instance:
            raise PluginNotInstalledError(f"插件 {plugin_id} 实例不存在")

        if not hasattr(instance, "run"):
            raise PluginError(f"插件 {plugin_id} 未实现 run() 方法")

        threading.Thread(target=instance.run, daemon=True).start()
        log.info(f"[PluginFrameworkService] 插件 {plugin_id} 立即运行任务已启动")

    def reload_plugin(self, plugin_id: str) -> None:
        """热重载插件（清理缓存后重新加载）"""
        orm_model = self._repo.get_manifest_by_id(plugin_id)
        if not orm_model:
            raise PluginNotInstalledError(f"插件未安装: {plugin_id}")

        sandbox = self._plugin_sandbox
        if not sandbox.reload(plugin_id):
            raise PluginHotReloadError(f"插件 {plugin_id} 热重载失败")
