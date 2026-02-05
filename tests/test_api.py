from io import BytesIO
from uuid import uuid4

from fastapi.testclient import TestClient

from app.main import app


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
        assert len(payload["errors"]) == 1

        servers = client.get("/api/servers?sort=name_asc&top=1")
        assert servers.status_code == 200
        body = servers.json()
        assert body["total"] == 1
        assert body["items"][0]["host"] in {"alpha.example.com", "beta.example.com"}


def test_scan_start_stop_and_job_details() -> None:
    with TestClient(app) as client:
        started = client.post("/api/scan/start", data={"mode": "full"})
        assert started.status_code == 200
        job_id = started.json()["job_id"]

        job = client.get(f"/api/jobs/{job_id}")
        assert job.status_code == 200
        assert job.json()["status"] == "running"

        stopped = client.post("/api/scan/stop")
        assert stopped.status_code == 200
        assert stopped.json()["scan_state"]["running"] is False


def test_import_txt_file_support() -> None:
    with TestClient(app) as client:
        uri = _make_uri("gamma.example.com", 9443)

        response = client.post(
            "/api/import",
            files={"uris_file": ("uris.txt", BytesIO(uri.encode("utf-8")), "text/plain")},
        )
        assert response.status_code == 200
        assert response.json()["accepted"] == 1
