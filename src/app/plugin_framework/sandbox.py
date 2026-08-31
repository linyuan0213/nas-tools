"""
Plugin Sandbox - 插件沙箱运行环境
动态加载插件后端模块，提供隔离的运行上下文
"""

import contextlib
import importlib
import importlib.util
import inspect
import os
import sys
from typing import Any

import log
from app.core.exceptions import PluginError
from app.message import Message
from app.plugin_framework import api_registry
from app.plugin_framework.context import PluginContext
from app.plugin_framework.dependency_manager import PluginDependencyManager
from app.plugin_framework.registry import PluginRegistry


class PluginSandbox:
    """插件沙箱，管理插件后端模块的加载和运行.

    由 lifespan 通过 AppContext 创建并管理生命周期。
    """

    def __init__(
        self,
        plugin_registry: PluginRegistry,
        message: Message,
        scheduler_core: Any,
        hook_system: Any,
        site_engine: Any,
        media_service: Any,
        plugin_log_repo: Any | None = None,
        site_cache: Any | None = None,
        downloader_core: Any | None = None,
        media_server: Any | None = None,
        subscribe_service: Any | None = None,
        searcher: Any | None = None,
        sync_engine: Any | None = None,
        site_resolver: Any | None = None,
        indexer_helper: Any | None = None,
        agent_service: Any | None = None,
        filetransfer_service: Any | None = None,
        site_service: Any | None = None,
        event_bus: Any | None = None,
        app_context: Any | None = None,
    ):
        self._instances: dict[str, Any] = {}
        self._registry = plugin_registry
        self._message = message
        self._scheduler_core = scheduler_core
        self._hook_system = hook_system
        self._site_engine = site_engine
        self._media_service = media_service
        self._plugin_log_repo = plugin_log_repo
        self._site_cache = site_cache
        self._downloader_core = downloader_core
        self._media_server = media_server
        self._subscribe_service = subscribe_service
        self._searcher = searcher
        self._sync_engine = sync_engine
        self._site_resolver = site_resolver
        self._indexer_helper = indexer_helper
        self._agent_service = agent_service
        self._filetransfer_service = filetransfer_service
        self._site_service = site_service
        self._event_bus = event_bus
        self._app_context = app_context

    @staticmethod
    def _filter_kwargs(plugin_class: Any, deps: dict[str, Any]) -> dict[str, Any]:
        """根据插件类构造函数的参数名过滤依赖。"""
        try:
            params = inspect.signature(plugin_class.__init__).parameters
        except (TypeError, ValueError):
            return {}
        return {k: v for k, v in deps.items() if k in params}

    def _get_module_path(self, plugin_id: str) -> str | None:
        """根据插件 entry 计算 module_path"""
        manifest = self._registry.get(plugin_id)
        if not manifest or not manifest.backend.entry:
            return None
        return manifest.backend.entry.split(":")[0]

    def _get_plugin_path(self, plugin_id: str) -> str | None:
        """获取插件根目录"""
        return self._registry.get_plugin_path(plugin_id)

    def _cleanup_modules(self, plugin_id: str) -> None:
        """清理插件相关的 sys.modules 缓存"""
        module_path = self._get_module_path(plugin_id)
        plugin_path = self._get_plugin_path(plugin_id)

        # 收集需要清理的模块名
        to_remove = []
        for key in list(sys.modules.keys()):
            # 1. 精确匹配入口模块
            if module_path and key == module_path:
                to_remove.append(key)
                continue
            # 2. 入口模块的子模块（backend.xxx）
            if module_path and key.startswith(module_path + "."):
                to_remove.append(key)
                continue
            # 3. 遗留兼容：plugin_{id} 前缀
            if key.startswith(f"plugin_{plugin_id}"):
                to_remove.append(key)

        for key in to_remove:
            try:
                del sys.modules[key]
                log.debug(f"[Sandbox] 清理模块缓存: {key}")
            except KeyError:
                pass

        # 从 sys.path 移除插件根目录（下次 load 会重新插入）
        if plugin_path and plugin_path in sys.path:
            sys.path.remove(plugin_path)

        # 使 importlib 缓存失效
        importlib.invalidate_caches()

    def load(self, plugin_id: str) -> bool:
        """加载并初始化插件后端"""
        manifest = self._registry.get(plugin_id)
        if not manifest:
            log.error(f"[Sandbox] 插件未找到: {plugin_id}")
            return False

        state = self._registry.get_state(plugin_id)
        if not state:
            log.error(f"[Sandbox] 插件状态未找到: {plugin_id}")
            return False
        if not state.enabled:
            log.info(f"[Sandbox] 插件未启用，跳过加载: {plugin_id}")
            return False

        # 加载前安装 manifest 声明的依赖（缺失时才安装，幂等）
        deps = manifest.backend.dependencies
        if deps:
            ok, err = PluginDependencyManager.install_dependencies(dependencies=deps, plugin_id=plugin_id)
            if not ok:
                log.error(f"[Sandbox] 插件 {plugin_id} 依赖安装失败: {err}")
                if self._plugin_log_repo is not None:
                    try:
                        self._plugin_log_repo.insert(plugin_id, "ERROR", f"依赖安装失败: {err}")
                    except Exception:  # noqa: S110 - 日志写入失败不影响主流程
                        pass
                return False

        try:
            plugin_path = self._get_plugin_path(plugin_id)
            if not plugin_path:
                return False

            entry = manifest.backend.entry
            if not entry:
                log.warn(f"[Sandbox] 插件未声明后端入口: {plugin_id}")
                return False

            module_path, class_name = entry.split(":")
            file_path = os.path.join(plugin_path, module_path.replace(".", "/") + ".py")

            if not os.path.exists(file_path):
                log.error(f"[Sandbox] 插件入口文件不存在: {file_path}")
                return False

            # 动态加载模块
            if plugin_path not in sys.path:
                sys.path.insert(0, plugin_path)
            spec = importlib.util.spec_from_file_location(module_path, file_path)
            if not spec or not spec.loader:
                log.error(f"[Sandbox] 无法加载插件模块: {module_path}")
                return False
            module = importlib.util.module_from_spec(spec)
            sys.modules[module_path] = module
            spec.loader.exec_module(module)

            plugin_class = getattr(module, class_name)
            if not plugin_class:
                log.error(f"[Sandbox] 插件类未找到: {class_name}")
                return False

            # 创建上下文
            ctx = PluginContext(
                plugin_id,
                plugin_name=manifest.name,
                plugin_log_repo=self._plugin_log_repo,
                message=self._message,
                scheduler_core=self._scheduler_core,
                hook_system=self._hook_system,
                site_engine=self._site_engine,
                media_service=self._media_service,
            )
            deps = {
                "sites": self._site_cache,
                "site_resolver": self._site_resolver,
                "index_helper": self._indexer_helper,
                "mediaserver": self._media_server,
                "downloader": self._downloader_core,
                "searcher": self._searcher,
                "subscribe": self._subscribe_service,
                "site_cache": self._site_cache,
                "agent_service": self._agent_service,
                "sync": self._sync_engine,
                "filetransfer": self._filetransfer_service,
                "site_service": self._site_service,
                "event_bus": self._event_bus,
                "app_context": self._app_context,
            }
            instance = plugin_class(ctx, **self._filter_kwargs(plugin_class, deps))

            self._instances[plugin_id] = instance

            # 注册 manifest 声明的事件钩子
            hooks = getattr(manifest.backend, "hooks", None) or []
            for event in hooks:
                if event:
                    self._hook_system.register(event, plugin_id)

            # 调用生命周期方法
            if hasattr(instance, "on_enable"):
                instance.on_enable()

            log.info(f"[Sandbox] 插件加载成功: {plugin_id}")
            return True

        except PluginError as e:
            log.error(f"[Sandbox] 插件加载失败 {plugin_id}: {e}")
            return False
        except Exception as e:  # noqa: BLE001
            log.error(f"[Sandbox] 插件加载失败 {plugin_id}: {e}")
            return False

    def unload(self, plugin_id: str) -> None:
        """卸载插件"""
        instance = self._instances.get(plugin_id)
        if instance:
            try:
                if hasattr(instance, "on_disable"):
                    instance.on_disable()
            except PluginError as e:
                log.error(f"[Sandbox] 插件禁用失败 {plugin_id}: {e}")

            self._instances.pop(plugin_id, None)
            self._cleanup_modules(plugin_id)

            # 注销该插件的所有事件钩子
            self._hook_system.unregister_all(plugin_id)

            # 注销该插件的所有自定义 API 与公开回调
            api_registry.unregister_plugin_all(plugin_id)

            # 自动注销该插件的所有消息命令
            self._message.clear_plugin_commands(plugin_id)

            log.info(f"[Sandbox] 插件卸载: {plugin_id}")

    def reload(self, plugin_id: str) -> bool:
        """热重载插件：清理缓存后重新加载"""
        manifest = self._registry.get(plugin_id)
        if not manifest:
            log.error(f"[Sandbox] 重载失败，插件未找到: {plugin_id}")
            return False

        log.info(f"[Sandbox] 开始热重载插件: {plugin_id}")

        # 1. 卸载现有实例
        self.unload(plugin_id)

        # 2. 强制清理所有模块缓存
        self._cleanup_modules(plugin_id)

        # 3. 重新加载
        ok = self.load(plugin_id)
        if ok:
            log.info(f"[Sandbox] 插件热重载成功: {plugin_id}")
        else:
            log.error(f"[Sandbox] 插件热重载失败: {plugin_id}")
        return ok

    def call(self, plugin_id: str, method: str, *args, **kwargs) -> Any:
        """调用插件方法"""
        instance = self._instances.get(plugin_id)
        if not instance:
            raise RuntimeError(f"插件未加载: {plugin_id}")

        func = getattr(instance, method, None)
        if not func:
            raise AttributeError(f"插件 {plugin_id} 没有方法: {method}")

        return func(*args, **kwargs)

    def call_hook(self, plugin_id: str, event: str, data: dict | None = None) -> None:
        """调用插件的 hook 处理器"""
        instance = self._instances.get(plugin_id)
        if not instance:
            return

        if hasattr(instance, "on_hook"):
            try:
                instance.on_hook(event, data)
            except PluginError as e:
                log.error(f"[Sandbox] 插件 {plugin_id} 处理 hook {event} 失败: {e}")

    def get_plugin_instance(self, plugin_id: str) -> Any | None:
        """获取插件实例"""
        return self._instances.get(plugin_id)

    def load_all(self) -> None:
        """加载所有已启用的插件，批量注册消息命令并统一刷新菜单。"""
        command_manager = getattr(self._message, "_command_manager", None)
        with command_manager.suppress_refresh() if command_manager else contextlib.nullcontext():
            for plugin_id, state in self._registry._state_cache.items():
                if state.enabled:
                    self.load(plugin_id)
