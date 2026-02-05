import json

from app.checks.xray_adapter import XrayAdapter


class _DummyProcess:
    def poll(self):
        return None

    def terminate(self):
        return None

    def wait(self, timeout=None):
        return None


class _DummyTempDir:
    def __init__(self, path: str) -> None:
        self.path = path

    def __enter__(self):
        return self.path

    def __exit__(self, exc_type, exc, tb):
        return False


def test_run_xray_check_generates_vless_outbound_config(monkeypatch, tmp_path) -> None:
    class _DummyOpener:
        def open(self, req, timeout):
            raise OSError("intentional probe failure")

    monkeypatch.setattr("app.checks.xray_adapter.tempfile.TemporaryDirectory", lambda prefix: _DummyTempDir(str(tmp_path)))
    monkeypatch.setattr("app.checks.xray_adapter.subprocess.Popen", lambda *args, **kwargs: _DummyProcess())
    monkeypatch.setattr("app.checks.xray_adapter.request.build_opener", lambda *args, **kwargs: _DummyOpener())
    monkeypatch.setattr("app.checks.xray_adapter.time.sleep", lambda *_: None)

    adapter = XrayAdapter()
    adapter.xray_path = "xray"

    result = adapter._run_xray_check(
        "probe-target.example.com",
        80,
        vless_config={
            "host": "vless.example.com",
            "port": 443,
            "id": "11111111-1111-1111-1111-111111111111",
            "security": "tls",
            "network": "ws",
            "sni": "cdn.example.com",
            "fp": "chrome",
            "flow": "xtls-rprx-vision",
            "ws_path": "/ws",
            "ws_host": "cdn.example.com",
            "grpc_service_name": None,
        },
        timeout_s=1.0,
    )

    assert result.success is False
    cfg = json.loads((tmp_path / "config.json").read_text(encoding="utf-8"))
    outbound = cfg["outbounds"][0]
    assert outbound["protocol"] == "vless"
    assert outbound["settings"]["vnext"][0]["address"] == "vless.example.com"


def test_phase_c_http_check_returns_diagnostic_error_for_incomplete_vless_metadata() -> None:
    adapter = XrayAdapter()
    adapter.xray_path = "xray"

    result = adapter.phase_c_http_check(
        target_host="target.example.com",
        target_port=80,
        vless_config={"host": "vless.example.com"},
        timeout_s=1.0,
        enabled=True,
    )

    assert result.success is False
    assert result.error_message is not None
    assert "phase_c_vless_config_error" in result.error_message
    assert "required VLESS fields are missing" in result.error_message
