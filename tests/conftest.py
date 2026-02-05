from __future__ import annotations

import os
from pathlib import Path

# Keep test database isolated from default runtime DB file.
os.environ.setdefault("VLSC_SQLITE_PATH", "./.pytest-vlsc.db")

from app.db import init_db  # noqa: E402


_DB_PATH = Path(os.environ["VLSC_SQLITE_PATH"])


def pytest_sessionstart(session):
    init_db()


def pytest_sessionfinish(session, exitstatus):
    _DB_PATH.unlink(missing_ok=True)
