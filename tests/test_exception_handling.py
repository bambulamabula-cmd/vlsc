import socket

import pytest

from app.checks.netprobe import HOST_COOLDOWN, TcpAttempt, classify_error, phase_a_dns_tcp, phase_b_multi_tcp, tcp_probe
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


@pytest.mark.parametrize(
    ("exc", "expected"),
    [
        (socket.gaierror(-2, "Name or service not known"), "dns_fail"),
        (ConnectionRefusedError("Connection refused"), "conn_refused"),
        (socket.timeout("timed out"), "timeout"),
        (TimeoutError("timed out"), "timeout"),
        (OSError(110, "Operation timed out"), "timeout"),
        (OSError(60, "Operation timed out"), "timeout"),
        (RuntimeError("boom"), "unknown"),
    ],
)
def test_classify_error_semantics(exc: BaseException, expected: str) -> None:
    assert classify_error(exc) == expected


def test_tcp_probe_does_not_catch_keyboard_interrupt(monkeypatch: pytest.MonkeyPatch) -> None:
    def _raise_keyboard_interrupt(*args, **kwargs):
        raise KeyboardInterrupt

    monkeypatch.setattr(socket, "create_connection", _raise_keyboard_interrupt)

    with pytest.raises(KeyboardInterrupt):
        tcp_probe("example.com", 443, timeout_s=1.0)


def test_phase_a_dns_tcp_does_not_catch_system_exit(monkeypatch: pytest.MonkeyPatch) -> None:
    def _raise_system_exit(*args, **kwargs):
        raise SystemExit(2)

    monkeypatch.setattr(socket, "getaddrinfo", _raise_system_exit)

    with pytest.raises(SystemExit):
        phase_a_dns_tcp("example.com", 443, timeout_s=1.0)


def test_run_xray_check_does_not_catch_keyboard_interrupt(monkeypatch: pytest.MonkeyPatch, tmp_path) -> None:
    class _DummyOpener:
        def open(self, req, timeout):
            raise KeyboardInterrupt

    monkeypatch.setattr("app.checks.xray_adapter.tempfile.TemporaryDirectory", lambda prefix: _DummyTempDir(str(tmp_path)))
    monkeypatch.setattr("app.checks.xray_adapter.subprocess.Popen", lambda *args, **kwargs: _DummyProcess())
    monkeypatch.setattr("app.checks.xray_adapter.request.build_opener", lambda *args, **kwargs: _DummyOpener())
    monkeypatch.setattr("app.checks.xray_adapter.time.sleep", lambda *_: None)

    adapter = XrayAdapter()
    adapter.xray_path = "xray"

    vless_config = {
        "host": "example.com",
        "port": 443,
        "id": "11111111-1111-1111-1111-111111111111",
        "security": "tls",
        "network": "tcp",
        "sni": "example.com",
        "fp": "chrome",
        "flow": "xtls-rprx-vision",
    }

    with pytest.raises(KeyboardInterrupt):
        adapter._run_xray_check("example.com", 80, vless_config=vless_config, timeout_s=1.0)


def test_run_xray_check_still_catches_regular_exceptions(monkeypatch: pytest.MonkeyPatch, tmp_path) -> None:
    class _DummyOpener:
        def open(self, req, timeout):
            raise OSError("network down")

    monkeypatch.setattr("app.checks.xray_adapter.tempfile.TemporaryDirectory", lambda prefix: _DummyTempDir(str(tmp_path)))
    monkeypatch.setattr("app.checks.xray_adapter.subprocess.Popen", lambda *args, **kwargs: _DummyProcess())
    monkeypatch.setattr("app.checks.xray_adapter.request.build_opener", lambda *args, **kwargs: _DummyOpener())
    monkeypatch.setattr("app.checks.xray_adapter.time.sleep", lambda *_: None)

    adapter = XrayAdapter()
    adapter.xray_path = "xray"

    vless_config = {
        "host": "example.com",
        "port": 443,
        "id": "11111111-1111-1111-1111-111111111111",
        "security": "tls",
        "network": "tcp",
        "sni": "example.com",
        "fp": "chrome",
        "flow": "xtls-rprx-vision",
    }

    result = adapter._run_xray_check("example.com", 80, vless_config=vless_config, timeout_s=1.0)

    assert result.success is False
    assert result.error_message == "network down"


def test_phase_b_cooldown_is_scoped_per_host_port(monkeypatch: pytest.MonkeyPatch) -> None:
    HOST_COOLDOWN._cooldown_until.clear()

    monkeypatch.setattr(
        "app.checks.netprobe.tcp_probe",
        lambda *args, **kwargs: TcpAttempt(success=False, rtt_ms=None, error_type="timeout"),
    )
    monkeypatch.setattr("app.checks.netprobe.time.sleep", lambda *_: None)

    first = phase_b_multi_tcp("example.com", 80, timeout_s=0.1, attempts=1, host_cooldown_s=60.0)
    second = phase_b_multi_tcp("example.com", 443, timeout_s=0.1, attempts=1, host_cooldown_s=60.0)

    assert first.attempts == 1
    assert first.successes == 0
    assert second.attempts == 1
    assert second.successes == 0

    HOST_COOLDOWN._cooldown_until.clear()
