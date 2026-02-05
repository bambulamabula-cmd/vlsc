from pathlib import Path


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
