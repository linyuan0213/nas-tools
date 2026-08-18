#!/usr/bin/env python3
"""Nexus Media 启动入口 — Granian 异步服务器

用法:
    python run.py                    # 生产模式
    python run.py --dev              # 开发模式（热重载）
    python run.py -w 4               # 指定 worker 数
"""  # noqa: EXE001

import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent / "src"))

from granian import Granian
from granian.constants import Interfaces, Loops
from granian.log import LogLevels

import log
from app.core.banner import print_startup_banner
from app.core.settings import settings
from version import APP_VERSION


def main():
    args = set(sys.argv[1:])
    dev = "--dev" in args
    workers = 1
    for a in args:
        if a.startswith("-w"):
            workers = int(a.split("=", 1)[-1] if "=" in a else sys.argv[sys.argv.index(a) + 1])

    print_startup_banner()
    log.console("Nexus Media FastAPI 启动中...")
    log.console(f"模式: {'dev' if dev else 'prod'}, workers={workers}")
    log.console(f"当前版本号：{APP_VERSION}")

    app_conf = settings.get("app") or {}
    host = app_conf.get("web_host", "::").replace("[", "").replace("]", "")
    port = int(app_conf.get("web_port", 3000))
    log.console(f"监听地址：{host}:{port}")

    ssl_kwargs = {}
    if (ssl_cert := app_conf.get("ssl_cert")) and (ssl_key := app_conf.get("ssl_key")):
        ssl_kwargs["ssl_cert"] = ssl_cert
        ssl_kwargs["ssl_key"] = ssl_key
        log.console("SSL 已启用")

    # 确保 PID 文件目录存在
    os.makedirs(Path(settings.data_path), exist_ok=True)

    server = Granian(
        "api.main:app",
        address=host,
        port=port,
        interface=Interfaces.ASGI,
        loop=Loops.auto,
        workers=workers,
        reload=dev,
        reload_ignore_dirs=[
            "logs",
            "__pycache__",
            ".venv",
            ".git",
            "alembic",
            "data",
            "static",
            "uploads",
            "temp",
            "docs",
            "tests",
            "config",
        ],
        log_enabled=True,
        log_level=LogLevels.info if dev else LogLevels.warning,
        log_access=dev,
        pid_file=Path(settings.data_path or ".") / "granian.pid",
        workers_kill_timeout=5,
        **ssl_kwargs,
    )

    def _on_shutdown():
        log.console("服务器已关闭")

    server.on_shutdown(_on_shutdown)
    server.serve()


if __name__ == "__main__":
    main()
