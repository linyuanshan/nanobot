"""Runtime helpers for env-file loading."""

from __future__ import annotations

import os
from pathlib import Path


def load_env_file(path: str | Path | None = None) -> Path | None:
    candidate = Path(path or os.getenv("HATCHERY_ENV_FILE", "hatchery/.env"))
    if not candidate.exists():
        fallback = candidate.with_name(".env.example")
        if not fallback.exists():
            return None
        candidate = fallback

    for raw_line in candidate.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        os.environ.setdefault(key.strip(), value.strip())
    return candidate


__all__ = ["load_env_file"]

