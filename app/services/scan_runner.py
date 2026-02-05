from __future__ import annotations

import threading
from datetime import datetime, timezone

from app.db import SessionLocal
from app.models import Job, Server
from app.services.scanner import ScannerService


class ScanRunnerService:
    def __init__(self) -> None:
        self._cancelled_job_ids: set[int] = set()
        self._active_job_ids: set[int] = set()
        self._lock = threading.Lock()

    def start(self, job_id: int, attempts: int = 5) -> None:
        worker = threading.Thread(
            target=self._run_job,
            kwargs={"job_id": job_id, "attempts": attempts},
            daemon=True,
            name=f"scan-runner-{job_id}",
        )
        worker.start()

    def cancel(self, job_id: int) -> None:
        with self._lock:
            self._cancelled_job_ids.add(job_id)

    def _is_cancelled(self, job_id: int) -> bool:
        with self._lock:
            return job_id in self._cancelled_job_ids

    def _clear_cancelled(self, job_id: int) -> None:
        with self._lock:
            self._cancelled_job_ids.discard(job_id)

    def has_active_jobs(self) -> bool:
        with self._lock:
            return bool(self._active_job_ids)

    def _mark_active(self, job_id: int) -> None:
        with self._lock:
            self._active_job_ids.add(job_id)

    def _mark_inactive(self, job_id: int) -> None:
        with self._lock:
            self._active_job_ids.discard(job_id)

    def _run_job(self, job_id: int, attempts: int = 5) -> None:
        self._mark_active(job_id)
        scanner = ScannerService()
        db = SessionLocal()
        try:
            job = db.query(Job).filter(Job.id == job_id).first()
            if not job or job.status != "running":
                return

            servers = db.query(Server).filter(Server.enabled.is_(True)).order_by(Server.id.asc()).all()
            total_servers = len(servers)
            processed = 0
            checks: list[dict[str, object]] = []
            base_result = job.result if isinstance(job.result, dict) else {}
            job.result = {
                **base_result,
                "processed": processed,
                "total_servers": total_servers,
            }
            db.commit()

            for server in servers:
                db.refresh(job)
                if self._is_cancelled(job_id) or job.status != "running":
                    if job.status == "running":
                        job.status = "stopped"
                        job.finished_at = datetime.now(timezone.utc)
                        existing_result = job.result if isinstance(job.result, dict) else {}
                        job.result = {
                            **existing_result,
                            "processed": processed,
                            "total_servers": total_servers,
                            "checks": checks,
                            "cancelled": True,
                        }
                        db.commit()
                    return

                check = scanner.scan_server(db, server, attempts=attempts)
                processed += 1
                checks.append({"server_id": server.id, "check_id": check.id, "status": check.status})
                existing_result = job.result if isinstance(job.result, dict) else {}
                job.result = {
                    **existing_result,
                    "processed": processed,
                    "total_servers": total_servers,
                    "last_server_id": server.id,
                }
                db.commit()

            db.refresh(job)
            if job.status == "running":
                job.status = "completed"
                job.finished_at = datetime.now(timezone.utc)
                existing_result = job.result if isinstance(job.result, dict) else {}
                job.result = {
                    **existing_result,
                    "processed": processed,
                    "total_servers": total_servers,
                    "checks": checks,
                    "cancelled": False,
                }
                db.commit()
        except Exception as exc:  # noqa: BLE001
            db.rollback()
            job = db.query(Job).filter(Job.id == job_id).first()
            if job and job.status == "running":
                job.status = "failed"
                job.finished_at = datetime.now(timezone.utc)
                job.result = {"error": str(exc)}
                db.commit()
        finally:
            self._clear_cancelled(job_id)
            self._mark_inactive(job_id)
            db.close()


scan_runner_service = ScanRunnerService()
