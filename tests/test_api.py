from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
import time
from io import BytesIO
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from app.db import SessionLocal
from app.main import app
from app.models import Check, DailyAggregate, Job, Server, ServerAlias


@pytest.fixture(autouse=True)
def clean_db() -> None:
    session = SessionLocal()
    try:
        session.query(Check).delete()
        session.query(DailyAggregate).delete()
        session.query(ServerAlias).delete()
        session.query(Server).delete()
        session.query(Job).delete()
        session.commit()
    finally:
        session.close()


def _make_uri(host: str, port: int) -> str:
    return f"vless://{uuid4()}@{host}:{port}?security=tls&type=ws#srv"




def _wait_for_job_status(job_id: int, expected: set[str], timeout_s: float = 3.0) -> str:
    deadline = time.time() + timeout_s
    while time.time() < deadline:
        session = SessionLocal()
        try:
            job = session.query(Job).filter(Job.id == job_id).first()
            if job and job.status in expected:
                return job.status
        finally:
            session.close()
        time.sleep(0.05)
    raise AssertionError(f"Job {job_id} did not reach one of {expected} in {timeout_s}s")


def test_import_and_servers_listing() -> None:
    with TestClient(app) as client:
        text = "\n".join([
            _make_uri("alpha.example.com", 443),
            "bad-uri",
            _make_uri("beta.example.com", 8443),
        ])

        resp = client.post("/api/import", data={"uris_text": text})
        assert resp.status_code == 200
        payload = resp.json()
        assert payload["accepted"] == 2
        assert payload["created"] >= 2
        assert payload["skipped_duplicates"] == 0
        assert len(payload["errors"]) == 1

        servers = client.get("/api/servers?sort=name_asc&top=1")
        assert servers.status_code == 200
        body = servers.json()
        assert body["total"] == 2
        assert len(body["items"]) == 1
        assert body["items"][0]["host"] in {"alpha.example.com", "beta.example.com"}


def test_import_rejects_empty_payload() -> None:
    with TestClient(app) as client:
        response = client.post("/api/import", data={"uris_text": "   "})
        assert response.status_code == 400
        assert response.json()["detail"] == "No URIs provided"


def test_import_txt_file_support_and_duplicate_skip() -> None:
    with TestClient(app) as client:
        uri = _make_uri("gamma.example.com", 9443)

        first = client.post(
            "/api/import",
            files={"uris_file": ("uris.txt", BytesIO(uri.encode("utf-8")), "text/plain")},
        )
        assert first.status_code == 200
        assert first.json()["accepted"] == 1
        assert first.json()["created"] == 1

        second = client.post(
            "/api/import",
            files={"uris_file": ("uris.txt", BytesIO(uri.encode("utf-8")), "text/plain")},
        )
        assert second.status_code == 200
        assert second.json()["accepted"] == 1
        assert second.json()["created"] == 0
        assert second.json()["skipped_duplicates"] == 1


def test_import_is_atomic_under_duplicate_concurrency() -> None:
    uri = _make_uri("race.example.com", 443)

    with TestClient(app) as client:
        def _import_once() -> dict[str, int]:
            response = client.post("/api/import", data={"uris_text": uri})
            assert response.status_code == 200
            payload = response.json()
            return {
                "created": payload["created"],
                "skipped_duplicates": payload["skipped_duplicates"],
            }

        with ThreadPoolExecutor(max_workers=2) as pool:
            results = list(pool.map(lambda _: _import_once(), range(2)))

    created_total = sum(item["created"] for item in results)
    skipped_total = sum(item["skipped_duplicates"] for item in results)

    assert created_total == 1
    assert skipped_total == 1

    session = SessionLocal()
    try:
        duplicates = session.query(Server).filter(Server.host == "race.example.com", Server.port == 443).all()
        assert len(duplicates) == 1
    finally:
        session.close()


def test_import_large_payload_counts_duplicates_correctly() -> None:
    unique_items = [_make_uri(f"bulk-{idx}.example.com", 443) for idx in range(300)]
    duplicated_items = unique_items[:120]
    text = "\n".join(unique_items + duplicated_items)

    with TestClient(app) as client:
        response = client.post("/api/import", data={"uris_text": text})
        assert response.status_code == 200
        payload = response.json()

    assert payload["accepted"] == len(unique_items) + len(duplicated_items)
    assert payload["created"] == len(unique_items)
    assert payload["skipped_duplicates"] == len(duplicated_items)

    session = SessionLocal()
    try:
        assert session.query(Server).count() == len(unique_items)
    finally:
        session.close()


def test_import_is_atomic_under_high_concurrency() -> None:
    shared_payload = "\n".join([
        _make_uri("concurrent-a.example.com", 443),
        _make_uri("concurrent-b.example.com", 8443),
        _make_uri("concurrent-c.example.com", 2053),
    ])

    def _import_once() -> dict[str, int]:
        with TestClient(app) as client:
            response = client.post("/api/import", data={"uris_text": shared_payload})
            assert response.status_code == 200
            payload = response.json()
            return {
                "created": payload["created"],
                "skipped_duplicates": payload["skipped_duplicates"],
            }

    with ThreadPoolExecutor(max_workers=6) as pool:
        results = list(pool.map(lambda _: _import_once(), range(6)))

    created_total = sum(item["created"] for item in results)
    skipped_total = sum(item["skipped_duplicates"] for item in results)

    assert created_total == 3
    assert skipped_total == (6 * 3) - 3

    session = SessionLocal()
    try:
        rows = session.query(Server).filter(Server.host.like("concurrent-%.example.com")).all()
        assert len(rows) == 3
        assert {(row.host, row.port) for row in rows} == {
            ("concurrent-a.example.com", 443),
            ("concurrent-b.example.com", 8443),
            ("concurrent-c.example.com", 2053),
        }
    finally:
        session.close()


def test_import_rejects_non_txt_file() -> None:
    with TestClient(app) as client:
        response = client.post(
            "/api/import",
            files={"uris_file": ("uris.csv", BytesIO(b"abc"), "text/csv")},
        )
        assert response.status_code == 400


def test_scan_start_stop_and_job_details(monkeypatch) -> None:
    def _slow_scan_server(self, db, server, attempts=5):
        time.sleep(0.2)
        check = Check(server_id=server.id, status="ok", score=42)
        db.add(check)
        db.commit()
        db.refresh(check)
        return check

    monkeypatch.setattr("app.services.scan_runner.ScannerService.scan_server", _slow_scan_server)

    with TestClient(app) as client:
        imported = client.post("/api/import", data={"uris_text": _make_uri("start-stop.example.com", 443)})
        assert imported.status_code == 200

        started = client.post("/api/scan/start", data={"mode": "full"})
        assert started.status_code == 200
        job_id = started.json()["job_id"]

        duplicate_start = client.post("/api/scan/start", data={"mode": "quick"})
        assert duplicate_start.status_code == 409

        job = client.get(f"/api/jobs/{job_id}")
        assert job.status_code == 200
        assert job.json()["status"] in {"running", "completed"}

        stopped = client.post("/api/scan/stop")
        assert stopped.status_code == 200
        assert stopped.json()["scan_state"]["running"] is False
        assert stopped.json()["stopped_job_id"] in {job_id, None}

    _wait_for_job_status(job_id, {"stopped", "completed", "failed"})


def test_export_endpoint_returns_csv() -> None:
    with TestClient(app) as client:
        response = client.get("/api/export")
        assert response.status_code == 200
        assert response.headers["content-type"].startswith("text/csv")
        assert "id,name,host,port,enabled,updated_at" in response.text


def test_scan_start_is_atomic_under_concurrency(monkeypatch) -> None:
    def _slow_scan_server(self, db, server, attempts=5):
        time.sleep(0.2)
        check = Check(server_id=server.id, status="ok", score=64)
        db.add(check)
        db.commit()
        db.refresh(check)
        return check

    monkeypatch.setattr("app.services.scan_runner.ScannerService.scan_server", _slow_scan_server)

    with TestClient(app) as client:
        imported = client.post("/api/import", data={"uris_text": _make_uri("atomic.example.com", 443)})
        assert imported.status_code == 200

        def _start() -> int:
            return client.post("/api/scan/start", data={"mode": "quick"}).status_code

        with ThreadPoolExecutor(max_workers=2) as pool:
            statuses = list(pool.map(lambda _: _start(), range(2)))

        assert sorted(statuses) == [200, 409]

        session = SessionLocal()
        try:
            jobs = session.query(Job).filter(Job.kind == "scan").all()
            assert len(jobs) == 1
            running_job_id = jobs[0].id
        finally:
            session.close()

        stop = client.post("/api/scan/stop")
        assert stop.status_code == 200

    _wait_for_job_status(running_job_id, {"stopped", "completed", "failed"})


def test_scan_stop_uses_db_state_after_client_recreation() -> None:
    with TestClient(app) as client:
        started = client.post("/api/scan/start", data={"mode": "full"})
        assert started.status_code == 200
        job_id = started.json()["job_id"]

    with TestClient(app) as new_client:
        stop = new_client.post("/api/scan/stop")
        assert stop.status_code == 200
        payload = stop.json()
        assert payload["stopped_job_id"] in {job_id, None}
        assert payload["scan_state"]["running"] is False
        assert payload["scan_state"]["job_id"] is None

        duplicate_stop = new_client.post("/api/scan/stop")
        assert duplicate_stop.status_code == 200
        assert duplicate_stop.json()["stopped_job_id"] is None
        assert duplicate_stop.json()["scan_state"]["running"] is False


def test_servers_listing_uses_latest_check_per_server() -> None:
    with TestClient(app) as client:
        import_payload = "\n".join([
            _make_uri("latest-a.example.com", 443),
            _make_uri("latest-b.example.com", 8443),
        ])
        imported = client.post("/api/import", data={"uris_text": import_payload})
        assert imported.status_code == 200

    session = SessionLocal()
    try:
        server_a = session.query(Server).filter(Server.host == "latest-a.example.com").one()
        server_b = session.query(Server).filter(Server.host == "latest-b.example.com").one()

        session.add_all([
            Check(server_id=server_a.id, status="ok", score=20, checked_at=datetime(2024, 1, 1, 10, 0, 0)),
            Check(server_id=server_a.id, status="fail", score=99, checked_at=datetime(2024, 1, 1, 11, 0, 0)),
            Check(server_id=server_b.id, status="ok", score=55, checked_at=datetime(2024, 1, 1, 9, 0, 0)),
        ])
        session.commit()
    finally:
        session.close()

    with TestClient(app) as client:
        response = client.get("/api/servers")
        assert response.status_code == 200

        by_host = {item["host"]: item for item in response.json()["items"]}
        assert by_host["latest-a.example.com"]["score"] == 99
        assert by_host["latest-a.example.com"]["alive"] is False
        assert by_host["latest-b.example.com"]["score"] == 55


def test_scan_runner_creates_checks_and_completes(monkeypatch) -> None:
    def _fake_scan_server(self, db, server, attempts=5):
        check = Check(server_id=server.id, status="ok", score=77, latency_ms=12.0)
        db.add(check)
        db.commit()
        db.refresh(check)
        return check

    monkeypatch.setattr("app.services.scan_runner.ScannerService.scan_server", _fake_scan_server)

    with TestClient(app) as client:
        payload = "\n".join([
            _make_uri("runner-a.example.com", 443),
            _make_uri("runner-b.example.com", 8443),
        ])
        imported = client.post("/api/import", data={"uris_text": payload})
        assert imported.status_code == 200

        started = client.post("/api/scan/start", data={"mode": "quick"})
        assert started.status_code == 200
        job_id = started.json()["job_id"]

    final_status = _wait_for_job_status(job_id, {"completed", "failed"})
    assert final_status == "completed"

    session = SessionLocal()
    try:
        server_ids = {server.id for server in session.query(Server).filter(Server.host.in_(["runner-a.example.com", "runner-b.example.com"]))}
        checks = session.query(Check).filter(Check.server_id.in_(server_ids)).all()
        assert len(checks) == 2

        job = session.query(Job).filter(Job.id == job_id).one()
        assert job.status == "completed"
        assert job.finished_at is not None
        assert isinstance(job.result, dict)
        assert job.result["processed"] == 2
    finally:
        session.close()


def test_scan_runner_sets_failed_status_on_exception(monkeypatch) -> None:
    def _broken_scan_server(self, db, server, attempts=5):
        raise RuntimeError("scan exploded")

    monkeypatch.setattr("app.services.scan_runner.ScannerService.scan_server", _broken_scan_server)

    with TestClient(app) as client:
        imported = client.post("/api/import", data={"uris_text": _make_uri("fail.example.com", 443)})
        assert imported.status_code == 200

        started = client.post("/api/scan/start", data={"mode": "quick"})
        assert started.status_code == 200
        job_id = started.json()["job_id"]

    final_status = _wait_for_job_status(job_id, {"failed"})
    assert final_status == "failed"

    session = SessionLocal()
    try:
        job = session.query(Job).filter(Job.id == job_id).one()
        assert isinstance(job.result, dict)
        assert "scan exploded" in job.result.get("error", "")
    finally:
        session.close()


def test_scan_stop_interrupts_further_servers(monkeypatch) -> None:
    processed_hosts: list[str] = []

    def _slow_scan_server(self, db, server, attempts=5):
        processed_hosts.append(server.host)
        time.sleep(0.2)
        check = Check(server_id=server.id, status="ok", score=50)
        db.add(check)
        db.commit()
        db.refresh(check)
        return check

    monkeypatch.setattr("app.services.scan_runner.ScannerService.scan_server", _slow_scan_server)

    with TestClient(app) as client:
        payload = "\n".join([
            _make_uri("stop-a.example.com", 443),
            _make_uri("stop-b.example.com", 8443),
            _make_uri("stop-c.example.com", 2053),
        ])
        imported = client.post("/api/import", data={"uris_text": payload})
        assert imported.status_code == 200

        started = client.post("/api/scan/start", data={"mode": "quick"})
        assert started.status_code == 200
        job_id = started.json()["job_id"]

        time.sleep(0.08)
        stopped = client.post("/api/scan/stop")
        assert stopped.status_code == 200
        assert stopped.json()["stopped_job_id"] in {job_id, None}

    _wait_for_job_status(job_id, {"stopped"})

    session = SessionLocal()
    try:
        server_ids = {server.id for server in session.query(Server).filter(Server.host.like("stop-%.example.com"))}
        checks = session.query(Check).filter(Check.server_id.in_(server_ids)).all()
        assert len(checks) < 3

        job = session.query(Job).filter(Job.id == job_id).one()
        assert job.status == "stopped"
        assert isinstance(job.result, dict)
        assert job.result.get("cancelled") is True
    finally:
        session.close()

    assert len(processed_hosts) < 3
