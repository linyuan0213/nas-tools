"""
插件依赖管理器
负责解析和安装插件所需的第三方 Python 包
"""

import os
import re
import subprocess
import sys

import log

# 依赖说明符白名单：仅允许 包名+版本运算符 形式，拒绝 -/URL/git+/file:// 等注入
_DEPENDENCY_RE = re.compile(r"^[\w\-.]+(==|>=|<=|~=)[\w.\-]+$")


class PluginDependencyManager:
    """插件依赖管理器"""

    @staticmethod
    def _validate_dependency(spec: str) -> str | None:
        """校验依赖说明符是否合法，返回错误信息（None 表示合法）"""
        spec = spec.strip()
        if not spec:
            return "空依赖"
        if spec.startswith("-") or spec.startswith("@"):
            return f"依赖以非法前缀开头: {spec}"
        if any(marker in spec for marker in ("://", "git+", "file:", "extras", "{", "}", "[", "]")):
            return f"依赖含非法说明符: {spec}"
        if not _DEPENDENCY_RE.match(spec):
            return f"依赖格式非法: {spec}"
        return None

    @staticmethod
    def install_dependencies(
        dependencies: list[str],
        plugin_id: str,
        plugin_path: str | None = None,
    ) -> tuple[bool, str]:
        """
        安装插件依赖

        :param dependencies: 依赖列表，格式如 ["requests>=2.28.0", "numpy"]
        :param plugin_id: 插件 ID（用于日志）
        :param plugin_path: 插件目录路径（用于读取 requirements.txt fallback）
        :return: (是否成功, 错误信息)
        """
        reqs: list[str] = []

        # 1. 优先使用 manifest 中声明的 dependencies
        if dependencies:
            reqs.extend(dependencies)

        # 2. fallback：读取插件目录下的 requirements.txt
        if plugin_path and not reqs:
            req_file = os.path.join(plugin_path, "requirements.txt")
            if os.path.exists(req_file):
                with open(req_file, encoding="utf-8") as f:
                    for line in f:
                        line = line.strip()
                        if line and not line.startswith("#"):
                            reqs.append(line)

        # 3. 校验依赖说明符（白名单，防参数/供应链注入）
        for req in reqs:
            err = PluginDependencyManager._validate_dependency(req)
            if err:
                log.error(f"[PluginDeps] 插件 {plugin_id} 依赖校验失败: {err}")
                return False, f"依赖校验失败: {err}"

        if not reqs:
            return True, ""

        # 过滤已安装的依赖
        missing = [r for r in reqs if not PluginDependencyManager.check_dependency(r)]
        if not missing:
            log.info(f"[PluginDeps] 插件 {plugin_id} 所有依赖已满足")
            return True, ""

        log.info(f"[PluginDeps] 插件 {plugin_id} 需要安装依赖: {missing}")

        # 4. 使用 uv pip install 安装缺失依赖（python 路径取当前解释器，避免依赖 CWD）
        cmd = ["uv", "pip", "install", "--python", sys.executable] + missing
        try:
            result = subprocess.run(  # nosec B603
                cmd,
                capture_output=True,
                text=True,
                timeout=300,
                check=False,
            )
            if result.returncode != 0:
                err = result.stderr or result.stdout or "未知错误"
                log.error(f"[PluginDeps] 插件 {plugin_id} 依赖安装失败: {err}")
                return False, err

            log.info(f"[PluginDeps] 插件 {plugin_id} 依赖安装成功")
            return True, ""
        except subprocess.TimeoutExpired:
            log.error(f"[PluginDeps] 插件 {plugin_id} 依赖安装超时")
            return False, "依赖安装超时"
        except FileNotFoundError:
            log.error("[PluginDeps] uv 命令未找到，无法安装插件依赖")
            return False, "uv 命令未找到，请确保 uv 已安装"
        except Exception as e:
            log.error(f"[PluginDeps] 插件 {plugin_id} 依赖安装异常: {e}")
            return False, str(e)

    @staticmethod
    def check_dependency(package_spec: str) -> bool:
        """检查单个依赖是否已安装"""
        pkg_name = package_spec.split("[")[0].split("=")[0].split("<")[0].split(">")[0].strip()
        try:
            __import__(pkg_name.replace("-", "_"))
            return True
        except ImportError:
            return False

    @staticmethod
    def check_dependencies(dependencies: list[str]) -> dict[str, bool]:
        """批量检查依赖是否已安装"""
        return {dep: PluginDependencyManager.check_dependency(dep) for dep in dependencies}
