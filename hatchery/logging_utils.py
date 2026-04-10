"""Logging setup for hatchery runtime services."""

from __future__ import annotations

import logging
from logging.handlers import RotatingFileHandler
from pathlib import Path


def configure_runtime_logging(
    *,
    service_name: str,
    log_dir: Path,
    level: str = "INFO",
    max_bytes: int = 2_000_000,
    backup_count: int = 5,
) -> Path:
    log_dir.mkdir(parents=True, exist_ok=True)
    log_path = log_dir / f"{service_name}.log"

    logger = logging.getLogger()
    logger.setLevel(getattr(logging, level.upper(), logging.INFO))

    for handler in list(logger.handlers):
        if getattr(handler, "_hatchery_managed", False):
            logger.removeHandler(handler)
            handler.close()

    formatter = logging.Formatter(
        "%(asctime)s %(levelname)s %(name)s %(message)s",
        datefmt="%Y-%m-%dT%H:%M:%S",
    )

    file_handler = RotatingFileHandler(
        log_path,
        maxBytes=max_bytes,
        backupCount=backup_count,
        encoding="utf-8",
    )
    file_handler.setFormatter(formatter)
    file_handler._hatchery_managed = True  # type: ignore[attr-defined]

    stream_handler = logging.StreamHandler()
    stream_handler.setFormatter(formatter)
    stream_handler._hatchery_managed = True  # type: ignore[attr-defined]

    logger.addHandler(file_handler)
    logger.addHandler(stream_handler)
    return log_path


__all__ = ["configure_runtime_logging"]
