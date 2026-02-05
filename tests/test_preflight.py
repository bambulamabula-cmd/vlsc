import logging

from app.utils import preflight


def test_detect_runtime_environment_termux(monkeypatch):
    monkeypatch.setenv("TERMUX_VERSION", "0.118")
    monkeypatch.setenv("PREFIX", "/data/data/com.termux/files/usr")
    monkeypatch.setattr("app.utils.preflight.platform.system", lambda: "Linux")
    monkeypatch.setattr("app.utils.preflight.platform.release", lambda: "5.10.0")

    env = preflight.detect_runtime_environment()

    assert env.is_termux is True
    assert env.is_android is True
    assert env.termux_version == "0.118"


def test_preflight_warns_about_environment_issues(monkeypatch, caplog):
    monkeypatch.setattr("app.utils.preflight._has_sqlite3", lambda: False)
    monkeypatch.setattr("app.utils.preflight._is_db_path_writable", lambda _: False)
    monkeypatch.setattr("app.utils.preflight.shutil.which", lambda _: None)
    monkeypatch.setattr(
        "app.utils.preflight.detect_runtime_environment",
        lambda: preflight.RuntimeEnvironment(is_android=True, is_termux=True, termux_version="0.118"),
    )

    with caplog.at_level(logging.WARNING):
        healthy = preflight.run_preflight_checks(sqlite_path="/root/blocked/vlsc.db", xray_enabled=True)

    assert healthy is False
    messages = "\n".join(caplog.messages)
    assert "pkg update && pkg install python libsqlite" in messages
    assert "Database path is not writable" in messages
    assert "pkg install xray-core" in messages
    assert "Preflight finished with issues" in messages


def test_preflight_returns_healthy_when_dependencies_ok(monkeypatch, caplog):
    monkeypatch.setattr("app.utils.preflight._has_sqlite3", lambda: True)
    monkeypatch.setattr("app.utils.preflight._is_db_path_writable", lambda _: True)
    monkeypatch.setattr("app.utils.preflight.shutil.which", lambda _: "/usr/bin/xray")
    monkeypatch.setattr(
        "app.utils.preflight.detect_runtime_environment",
        lambda: preflight.RuntimeEnvironment(is_android=False, is_termux=False, termux_version=None),
    )

    with caplog.at_level(logging.WARNING):
        healthy = preflight.run_preflight_checks(sqlite_path="./vlsc.db", xray_enabled=True)

    assert healthy is True
    assert not caplog.messages
