from __future__ import annotations

import logging
import os
import platform
import sqlite3
import shutil
from pathlib import Path

from app.config import settings


def _is_termux_or_android() -> bool:
    if os.getenv("TERMUX_VERSION"):
        return True

    system = platform.system().lower()
    release = platform.release().lower()
    if "android" in system or "android" in release:
        return True

    return "com.termux" in str(Path.home())


def collect_preflight_warnings() -> list[str]:
    warnings: list[str] = []

    if _is_termux_or_android():
        warnings.append(
            "Detected Android/Termux environment. If dependency installation fails on Python 3.12, "
            "install build tools: pkg install rust pkg-config make clang libffi openssl."
        )

    try:
        sqlite3.connect(":memory:").close()
    except sqlite3.Error as exc:
        warnings.append(f"sqlite3 runtime check failed: {exc}")

    db_path = Path(settings.sqlite_path)
    parent = db_path.parent if str(db_path.parent) else Path(".")
    if not parent.exists():
        warnings.append(f"SQLite directory does not exist: {parent}")
    elif not os.access(parent, os.W_OK):
        warnings.append(f"SQLite directory is not writable: {parent}")

    if settings.xray_enabled and shutil.which("xray") is None:
        warnings.append("VLSC_XRAY_ENABLED=true, but xray binary was not found in PATH")

    return warnings


def log_preflight_warnings(logger: logging.Logger | None = None) -> None:
    active_logger = logger or logging.getLogger("vlsc.preflight")
    for warning in collect_preflight_warnings():
        active_logger.warning("Preflight: %s", warning)
