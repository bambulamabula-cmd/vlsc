from __future__ import annotations

import importlib.util
import logging
import os
import platform
import shutil
from dataclasses import dataclass
from pathlib import Path

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class RuntimeEnvironment:
    is_android: bool
    is_termux: bool
    termux_version: str | None


def detect_runtime_environment() -> RuntimeEnvironment:
    termux_version = os.environ.get("TERMUX_VERSION")
    system = platform.system().lower()
    release = platform.release().lower()
    is_android = "android" in system or "android" in release
    is_termux = termux_version is not None or "com.termux" in os.environ.get("PREFIX", "").lower()
    return RuntimeEnvironment(
        is_android=is_android or is_termux,
        is_termux=is_termux,
        termux_version=termux_version,
    )


def _has_sqlite3() -> bool:
    return importlib.util.find_spec("sqlite3") is not None


def _is_db_path_writable(sqlite_path: str) -> bool:
    db_path = Path(sqlite_path).expanduser()

    if db_path.exists():
        return os.access(db_path, os.W_OK)

    existing_parent = db_path.parent
    while not existing_parent.exists() and existing_parent != existing_parent.parent:
        existing_parent = existing_parent.parent

    return os.access(existing_parent, os.W_OK)


def run_preflight_checks(*, sqlite_path: str, xray_enabled: bool) -> bool:
    """Validate runtime environment and log actionable warnings without crashing startup."""

    env = detect_runtime_environment()
    is_healthy = True

    if env.is_termux:
        logger.info("Runtime environment detected: Termux%s", f" ({env.termux_version})" if env.termux_version else "")
    elif env.is_android:
        logger.info("Runtime environment detected: Android")

    if not _has_sqlite3():
        is_healthy = False
        if env.is_termux:
            logger.warning(
                "[environment] sqlite3 module is unavailable. Install/update Python with sqlite support in Termux: "
                "pkg update && pkg install python libsqlite"
            )
        else:
            logger.warning(
                "[environment] sqlite3 module is unavailable. Install Python with sqlite3 support before running VLSC."
            )

    if not _is_db_path_writable(sqlite_path):
        is_healthy = False
        logger.warning(
            "[environment] Database path is not writable: %s. Check directory permissions and ensure the process user can "
            "create/write this file.",
            sqlite_path,
        )

    if xray_enabled and shutil.which("xray") is None:
        is_healthy = False
        if env.is_termux:
            logger.warning(
                "[environment] Xray is enabled (VLSC_XRAY_ENABLED=true), but 'xray' binary is missing. "
                "Install it in Termux (for example: pkg install xray-core) or disable Xray checks."
            )
        else:
            logger.warning(
                "[environment] Xray is enabled (VLSC_XRAY_ENABLED=true), but 'xray' binary is missing in PATH. "
                "Install xray-core or disable Xray checks."
            )

    if not is_healthy:
        logger.warning(
            "[environment] Preflight finished with issues. Startup continues, but errors may be caused by host environment "
            "misconfiguration rather than application logic."
        )

    return is_healthy
