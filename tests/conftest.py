from __future__ import annotations

import os
import time
from pathlib import Path

# Keep test database isolated from default runtime DB file.
os.environ.setdefault("VLSC_SQLITE_PATH", "./.pytest-vlsc.db")

from app.db import SessionLocal, init_db  # noqa: E402
from app.models import Job  # noqa: E402
from app.services.scan_runner import scan_runner_service  # noqa: E402


_DB_PATH = Path(os.environ["VLSC_SQLITE_PATH"])


def pytest_sessionstart(session):
    init_db()


def pytest_sessionfinish(session, exitstatus):
    _DB_PATH.unlink(missing_ok=True)


def pytest_runtest_setup(item):
    deadline = time.time() + 5.0
    while time.time() < deadline:
        if not scan_runner_service.has_active_jobs():
            break
        time.sleep(0.05)

    session = SessionLocal()
    try:
        running_jobs = session.query(Job).filter(Job.kind == "scan", Job.status == "running").all()
        for job in running_jobs:
            scan_runner_service.cancel(job.id)
            job.status = "stopped"
        session.commit()
    finally:
        session.close()
