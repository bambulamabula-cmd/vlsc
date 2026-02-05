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
    assert outbound["settings"]["vnext"][0]["users"][0]["flow"] == "xtls-rprx-vision"


def test_run_xray_check_omits_empty_flow_from_user_config(monkeypatch, tmp_path) -> None:
    class _DummyOpener:
        def open(self, req, timeout):
            raise OSError("intentional probe failure")

    monkeypatch.setattr("app.checks.xray_adapter.tempfile.TemporaryDirectory", lambda prefix: _DummyTempDir(str(tmp_path)))
    monkeypatch.setattr("app.checks.xray_adapter.subprocess.Popen", lambda *args, **kwargs: _DummyProcess())
    monkeypatch.setattr("app.checks.xray_adapter.request.build_opener", lambda *args, **kwargs: _DummyOpener())
    monkeypatch.setattr("app.checks.xray_adapter.time.sleep", lambda *_: None)

    adapter = XrayAdapter()
    adapter.xray_path = "xray"

    adapter._run_xray_check(
        "probe-target.example.com",
        80,
        vless_config={
            "host": "vless.example.com",
            "port": 443,
            "id": "11111111-1111-1111-1111-111111111111",
            "security": "none",
            "network": "tcp",
            "sni": None,
            "fp": None,
            "flow": "",
            "ws_path": None,
            "ws_host": None,
            "grpc_service_name": None,
        },
        timeout_s=1.0,
    )

    cfg = json.loads((tmp_path / "config.json").read_text(encoding="utf-8"))
    user = cfg["outbounds"][0]["settings"]["vnext"][0]["users"][0]
    assert "flow" not in user


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


def test_normalize_vless_defaults_network_to_tcp() -> None:
    normalized = XrayAdapter._normalize_vless_config(
        {
            "host": "vless.example.com",
            "port": 443,
            "id": "11111111-1111-1111-1111-111111111111",
        }
    )

    assert normalized["network"] == "tcp"
    assert normalized["security"] == "none"


def test_normalize_vless_accepts_security_none_without_sni_fp_or_flow() -> None:
    normalized = XrayAdapter._normalize_vless_config(
        {
            "host": "vless.example.com",
            "port": 443,
            "id": "11111111-1111-1111-1111-111111111111",
            "security": "none",
            "network": "tcp",
        }
    )

    assert normalized["security"] == "none"
    assert normalized["sni"] is None
    assert normalized["fp"] is None
    assert normalized["flow"] is None


def test_normalize_vless_ws_requires_path() -> None:
    try:
        XrayAdapter._normalize_vless_config(
            {
                "host": "vless.example.com",
                "port": 443,
                "id": "11111111-1111-1111-1111-111111111111",
                "security": "none",
                "network": "ws",
            }
        )
    except ValueError as exc:
        assert "path" in str(exc)
    else:
        raise AssertionError("Expected ValueError for missing ws path")


def test_normalize_vless_grpc_requires_service_name() -> None:
    try:
        XrayAdapter._normalize_vless_config(
            {
                "host": "vless.example.com",
                "port": 443,
                "id": "11111111-1111-1111-1111-111111111111",
                "security": "none",
                "network": "grpc",
            }
        )
    except ValueError as exc:
        assert "serviceName" in str(exc)
    else:
        raise AssertionError("Expected ValueError for missing grpc serviceName")
