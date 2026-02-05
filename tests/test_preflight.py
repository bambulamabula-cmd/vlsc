from __future__ import annotations

import sqlite3

import pytest

from app.utils import preflight


def test_collect_preflight_warnings_for_termux_and_missing_xray(monkeypatch: pytest.MonkeyPatch, tmp_path) -> None:
    db_dir = tmp_path / "db"
    db_dir.mkdir()

    monkeypatch.setattr(preflight, "_is_termux_or_android", lambda: True)
    monkeypatch.setattr(preflight.settings, "sqlite_path", str(db_dir / "vlsc.db"))
    monkeypatch.setattr(preflight.settings, "xray_enabled", True)
    monkeypatch.setattr(preflight.shutil, "which", lambda _binary: None)

    warnings = preflight.collect_preflight_warnings()

    assert any("Android/Termux" in warning for warning in warnings)
    assert any("xray binary" in warning for warning in warnings)


def test_collect_preflight_warnings_reports_sqlite_runtime_failure(monkeypatch: pytest.MonkeyPatch, tmp_path) -> None:
    db_dir = tmp_path / "db"
    db_dir.mkdir()

    monkeypatch.setattr(preflight, "_is_termux_or_android", lambda: False)
    monkeypatch.setattr(preflight.settings, "sqlite_path", str(db_dir / "vlsc.db"))
    monkeypatch.setattr(preflight.settings, "xray_enabled", False)

    def _broken_connect(*_args, **_kwargs):
        raise sqlite3.Error("sqlite unavailable")

    monkeypatch.setattr(preflight.sqlite3, "connect", _broken_connect)

    warnings = preflight.collect_preflight_warnings()

    assert any("sqlite3 runtime check failed" in warning for warning in warnings)
