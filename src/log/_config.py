"""日志配置读取与 handlers 构建。"""

import json
import os
import re
import sys
import time
from typing import Any, TextIO

from app.core.settings import settings

__all__ = ["build_handlers", "purge_expired_logs"]

_DEFAULT_RETENTION = "5 days"

_VALID_LEVELS = {"TRACE", "DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"}


def _resolve_log_level(log_cfg: dict[str, Any]) -> str:
    """解析日志级别，默认 INFO；兼容小写（info/debug/error）与非法值兜底."""
    raw = str(log_cfg.get("level") or "info").strip().upper()
    return raw if raw in _VALID_LEVELS else "INFO"


def _parse_retention_days(retention: str | None) -> float:
    """把 '5 days' / '7 days' / '2 weeks' / '30 days' 解析为天数（失败回退默认 5 天）."""
    text = (retention or _DEFAULT_RETENTION).strip().lower()
    match = re.match(r"(\d+)\s*(day|days|d|week|weeks|w)?", text)
    if not match:
        return 5.0
    number = float(match.group(1))
    unit = match.group(2) or "d"
    if unit.startswith("w"):
        return number * 7.0
    return number


def purge_expired_logs(module: str) -> None:
    """启动时清理超过保留期的轮转日志.

    loguru 的 retention 只在轮转触发时删除旧文件；日志量骤降后可能长时间不轮转，
    这里在初始化时主动兜底删除超期文件，避免磁盘被历史轮转文件占满。
    """
    log_cfg = settings.get("log") or {}
    if (log_cfg.get("type") or "console") != "file":
        return
    retention_days = _parse_retention_days(log_cfg.get("retention"))
    logpath = log_cfg.get("path") or ""
    if not logpath:
        logpath = os.path.join(settings.data_path, "logs")
    if not os.path.isdir(logpath):
        return
    cutoff = time.time() - retention_days * 86400
    prefix = f"{module}."
    removed = 0
    for name in os.listdir(logpath):
        if not name.startswith(prefix) or not name.endswith(".log"):
            continue
        full = os.path.join(logpath, name)
        try:
            if os.path.getmtime(full) < cutoff:
                os.remove(full)
                removed += 1
        except OSError:
            continue
    if removed:
        print(f"[Log]清理超期日志 {removed} 个（保留 {int(retention_days)} 天）")


_JSON_FORMAT = os.environ.get("LOG_FORMAT", "").lower() == "json"


def _json_sink_factory(target: TextIO) -> Any:
    """返回一个 loguru sink callable，将记录序列化为 JSON 行并写入 target。"""

    def _sink(message: Any) -> None:
        record = message.record
        log_entry = {
            "timestamp": record["time"].strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z",
            "level": record["level"].name,
            "module": record.get("module", ""),
            "function": record.get("function", ""),
            "file": record.get("name") or "",
            "line": record.get("line", 0),
            "message": record["message"],
        }
        exc = record.get("exception")
        if exc:
            log_entry["exception"] = "{}: {}".format(
                exc.type.__name__ if exc.type else "",
                exc.value or "",
            )
        target.write(json.dumps(log_entry, ensure_ascii=False, default=str) + "\n")
        target.flush()

    return _sink


_HUMAN_FORMAT = "{time:YYYY-MM-DD HH:mm:ss.SSS} |{level:8}| {file} : {module}.{function}:{line:4} | - {message}"
_HUMAN_FORMAT_COLOR = (
    "{time:YYYY-MM-DD HH:mm:ss.SSS} |<lvl>{level:8}</>| {file} : {module}.{function}:{line:4} | - <lvl>{message}</>"
)


def _is_json_enabled(log_cfg: dict[str, Any]) -> bool:
    return _JSON_FORMAT or log_cfg.get("format") == "json"


def build_handlers(module: str) -> list[dict[str, Any]]:
    """根据全局 Config 生成 loguru handlers 配置。"""
    log_cfg = settings.get("log") or {}
    logtype = log_cfg.get("type") or "console"
    use_json = _is_json_enabled(log_cfg)
    log_level = _resolve_log_level(log_cfg)
    handlers: list[dict[str, Any]] = []

    if logtype == "file":
        logpath = log_cfg.get("path") or ""
        if not logpath:
            logpath = os.path.join(settings.data_path, "logs")
            os.makedirs(logpath, exist_ok=True)
        if logpath:
            if not os.path.exists(logpath):
                os.makedirs(logpath)
            filepath = os.path.join(logpath, module + ".log")
            if use_json:
                handlers.append(
                    {
                        "sink": _json_sink_factory(open(filepath, "a")),
                        "format": "{message}",
                        "level": log_level,
                    }
                )
            else:
                handlers.append(
                    {
                        "sink": filepath,
                        "rotation": log_cfg.get("rotation") or "5 MB",
                        "format": _HUMAN_FORMAT,
                        "colorize": False,
                        "retention": log_cfg.get("retention") or "5 days",
                        "level": log_level,
                    }
                )

    # 始终添加 stderr 终端输出
    if use_json:
        handlers.append(
            {
                "sink": _json_sink_factory(sys.stderr),
                "format": "{message}",
                "level": log_level,
            }
        )
    else:
        handlers.append(
            {
                "sink": sys.stderr,
                "format": _HUMAN_FORMAT_COLOR,
                "colorize": True,
                "level": log_level,
            }
        )
    return handlers
