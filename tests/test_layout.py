from pathlib import Path

from fastapi.testclient import TestClient

from app.main import app


REQUIRED_DIRS = [
    "app",
    "app/vless",
    "app/checks",
    "app/services",
    "app/web",
    "app/web/templates",
    "app/web/static",
    "app/utils",
    "tests",
]


REQUIRED_FILES = [
    "app/main.py",
    "app/config.py",
    "app/db.py",
    "app/models.py",
    "app/web/routes.py",
]


def test_required_directories_exist() -> None:
    for directory in REQUIRED_DIRS:
        assert Path(directory).is_dir(), f"Missing directory: {directory}"


def test_required_files_exist() -> None:
    for file_path in REQUIRED_FILES:
        assert Path(file_path).is_file(), f"Missing file: {file_path}"


def test_templates_and_static_resolve_from_any_cwd(tmp_path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_path)

    with TestClient(app) as client:
        dashboard = client.get("/")
        scan = client.get("/scan")

    assert dashboard.status_code == 200
    assert scan.status_code == 200
