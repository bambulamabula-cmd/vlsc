from __future__ import annotations

import logging
from logging.handlers import RotatingFileHandler
from pathlib import Path


def configure_logging(log_path: str = "./vlsc.log") -> None:
    """Configure root logger with stdout + rotating file handlers."""

    root_logger = logging.getLogger()
    if root_logger.handlers:
        return

    root_logger.setLevel(logging.INFO)

    formatter = logging.Formatter(
        "%(asctime)s | %(levelname)s | %(name)s | %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    stream_handler = logging.StreamHandler()
    stream_handler.setFormatter(formatter)
    root_logger.addHandler(stream_handler)

    log_file = Path(log_path)
    log_file.parent.mkdir(parents=True, exist_ok=True)
    file_handler = RotatingFileHandler(log_file, maxBytes=1_000_000, backupCount=5)
    file_handler.setFormatter(formatter)
    root_logger.addHandler(file_handler)
