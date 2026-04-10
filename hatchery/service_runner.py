"""Executable service runner for the hatchery API."""

from __future__ import annotations

import argparse

import uvicorn

from hatchery.logging_utils import configure_runtime_logging
from hatchery.runtime_env import load_env_file
from hatchery.settings import HatcherySettings


def main() -> None:
    load_env_file()
    settings = HatcherySettings.from_env()
    configure_runtime_logging(
        service_name=settings.service_name,
        log_dir=settings.log_dir,
        level=settings.log_level,
        max_bytes=settings.log_max_bytes,
        backup_count=settings.log_backup_count,
    )
    parser = argparse.ArgumentParser(description="Run the hatchery phase-1 service")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8090)
    args = parser.parse_args()

    uvicorn.run("hatchery.app:create_app", factory=True, host=args.host, port=args.port)


if __name__ == "__main__":
    main()
