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
        assert body["total"] == 1
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


def test_import_rejects_non_txt_file() -> None:
    with TestClient(app) as client:
        response = client.post(
            "/api/import",
            files={"uris_file": ("uris.csv", BytesIO(b"abc"), "text/csv")},
        )
        assert response.status_code == 400


def test_scan_start_stop_and_job_details() -> None:
    with TestClient(app) as client:
        started = client.post("/api/scan/start", data={"mode": "full"})
        assert started.status_code == 200
        job_id = started.json()["job_id"]

        duplicate_start = client.post("/api/scan/start", data={"mode": "quick"})
        assert duplicate_start.status_code == 409

        job = client.get(f"/api/jobs/{job_id}")
        assert job.status_code == 200
        assert job.json()["status"] == "running"

        stopped = client.post("/api/scan/stop")
        assert stopped.status_code == 200
        assert stopped.json()["scan_state"]["running"] is False
        assert stopped.json()["stopped_job_id"] == job_id


def test_export_endpoint_returns_csv() -> None:
    with TestClient(app) as client:
        response = client.get("/api/export")
        assert response.status_code == 200
        assert response.headers["content-type"].startswith("text/csv")
        assert "id,name,host,port,enabled,updated_at" in response.text
