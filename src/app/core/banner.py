"""Nexus Media 启动 Banner."""

import log

BANNER_LINES = [
    " _  _   ___  __  __  _   _   ___         __  __   ___   ___    ___     _",
    "| \\| | | __| \\ \\/ / | | | | / __|       |  \\/  | | __| |   \\  |_ _|   /_\\",
    "| .` | | _|   >  <  | |_| | \\__ \\       | |\\/| | | _|  | |) |  | |   / _ \\",
    "|_|\\_| |___| /_/\\_\\  \\___/  |___/       |_|  |_| |___| |___/  |___| /_/ \\_\\",
]


def print_startup_banner() -> None:
    """输出启动 Banner（逐行 log.info）."""
    for line in BANNER_LINES:
        log.info(line)
