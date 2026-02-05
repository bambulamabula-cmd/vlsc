import pytest

pytest.importorskip("fastapi")
from fastapi.testclient import TestClient

from app.main import app


def test_health_check() -> None:
    client = TestClient(app)
    response = client.get("/health")
    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] == "ok"
    assert payload["xray"]["enabled"] in {True, False}
    assert payload["xray"]["binary_found"] in {True, False}
