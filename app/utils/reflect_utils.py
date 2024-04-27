import importlib
import pkgutil

from app.conf import SystemConfig
from app.plugins import PluginManager


class ReflectUtils:

    @staticmethod
    def import_submodules(package, filter_func=lambda name, obj: True):
        """
        导入子模块
        :param package: 父包名
        :param filter_func: 子模块过滤函数，入参为模块名和模块对象，返回True则导入，否则不导入
        :return:
        """

        submodules = []
        packages = importlib.import_module(package).__path__
        for importer, package_name, _ in pkgutil.iter_modules(packages):
            full_package_name = f'{package}.{package_name}'
            if full_package_name.startswith('_'):
                continue
            module = importlib.import_module(full_package_name)
            for name, obj in module.__dict__.items():
                if name.startswith('_'):
                    continue
                if isinstance(obj, type) and filter_func(name, obj):
                    submodules.append(obj)

        return submodules

    @staticmethod
    def get_plugin_method(func_str):
        if len(func_str.split(".")) < 2:
            return
        class_name = func_str.split(".")[0]
        func_name = func_str.split(".")[1]
        plugins = ReflectUtils.import_submodules(
            "app.plugins.modules",
            filter_func=lambda _, obj: hasattr(obj, 'module_name')
        )
        plugin_manager = PluginManager()
        for plugin in plugins:
            if plugin.__name__ == class_name:
                pid = plugin.__name__
                return plugin_manager.get_plugin_method(pid, func_name)
        return None

    @staticmethod
    def get_plugin_config(pid):
        if not pid:
            return

        systemconfig = SystemConfig()
        return systemconfig.get(f"plugin.{pid}") or {}



    @staticmethod
    def get_class_by_name(lib_path, class_name):
        if not lib_path or not class_name:
            return
        package = importlib.import_module(lib_path)
        return getattr(package, class_name)

    @staticmethod
    def get_func_by_str(lib_path, func_str):
        if not str:
            return
        func = None
        if len(func_str.split(".")) == 2:
            class_name = func_str.split(".")[0]
            func_name = func_str.split(".")[1]
            cls = ReflectUtils.get_class_by_name(lib_path, class_name)
            func = getattr(cls(), func_name)
        else:
            func = ReflectUtils.get_class_by_name(lib_path, func_str)

        return func
