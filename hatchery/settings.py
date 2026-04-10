"""Runtime settings for the hatchery phase-1 service."""

from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from pathlib import Path

from hatchery.runtime_env import load_env_file


def _read_bool(name: str, default: bool) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


def _read_json_dict(name: str) -> dict[str, str]:
    raw = os.getenv(name)
    if not raw:
        return {}
    try:
        loaded = json.loads(raw)
    except json.JSONDecodeError:
        return {}
    return {str(key): str(value) for key, value in loaded.items()} if isinstance(loaded, dict) else {}


def _read_relay_map() -> dict[str, str]:
    relay_map = _read_json_dict("HATCHERY_REAL_RELAY_MAP_JSON")
    relay_map_path = os.getenv("HATCHERY_REAL_RELAY_MAP_PATH")
    if not relay_map_path:
        return relay_map
    candidate = Path(relay_map_path)
    if not candidate.exists():
        return relay_map
    try:
        loaded = json.loads(candidate.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return relay_map
    if isinstance(loaded, dict):
        relay_map.update({str(key): str(value) for key, value in loaded.items()})
    return relay_map


@dataclass(slots=True)
class HatcherySettings:
    database_path: Path = Path("workspace/hatchery/hatchery.db")
    approval_provider: str = "local"
    scheduler_interval_sec: float = 1.0
    enable_scheduler: bool = True
    service_name: str = "hatchery-service"
    mqtt_enabled: bool = False
    mqtt_host: str = "127.0.0.1"
    mqtt_port: int = 1883
    mqtt_keepalive_sec: int = 30
    mqtt_client_id: str = "hatchery-phase1"
    mqtt_topic_prefix: str = "hatchery"
    mqtt_qos: int = 1
    mqtt_retain: bool = False
    auth_enabled: bool = False
    auth_tokens: dict[str, str] = field(default_factory=dict)
    log_dir: Path = Path("workspace/hatchery/logs")
    log_level: str = "INFO"
    log_max_bytes: int = 2_000_000
    log_backup_count: int = 5
    real_adapter_enabled: bool = False
    real_default_timeout_sec: int = 30
    real_relay_map: dict[str, str] = field(default_factory=dict)
    real_strict_mapping: bool = False

    @classmethod
    def from_env(cls, env_file: str | Path | None = None) -> "HatcherySettings":
        load_env_file(env_file)
        return cls(
            database_path=Path(os.getenv("HATCHERY_DATABASE_PATH", "workspace/hatchery/hatchery.db")),
            approval_provider=os.getenv("HATCHERY_APPROVAL_PROVIDER", "local"),
            scheduler_interval_sec=float(os.getenv("HATCHERY_SCHEDULER_INTERVAL_SEC", "1.0")),
            enable_scheduler=_read_bool("HATCHERY_ENABLE_SCHEDULER", True),
            service_name=os.getenv("HATCHERY_SERVICE_NAME", "hatchery-service"),
            mqtt_enabled=_read_bool("HATCHERY_MQTT_ENABLED", False),
            mqtt_host=os.getenv("HATCHERY_MQTT_HOST", "127.0.0.1"),
            mqtt_port=int(os.getenv("HATCHERY_MQTT_PORT", "1883")),
            mqtt_keepalive_sec=int(os.getenv("HATCHERY_MQTT_KEEPALIVE_SEC", "30")),
            mqtt_client_id=os.getenv("HATCHERY_MQTT_CLIENT_ID", "hatchery-phase1"),
            mqtt_topic_prefix=os.getenv("HATCHERY_MQTT_TOPIC_PREFIX", "hatchery"),
            mqtt_qos=int(os.getenv("HATCHERY_MQTT_QOS", "1")),
            mqtt_retain=_read_bool("HATCHERY_MQTT_RETAIN", False),
            auth_enabled=_read_bool("HATCHERY_AUTH_ENABLED", False),
            auth_tokens=_read_json_dict("HATCHERY_AUTH_TOKENS_JSON"),
            log_dir=Path(os.getenv("HATCHERY_LOG_DIR", "workspace/hatchery/logs")),
            log_level=os.getenv("HATCHERY_LOG_LEVEL", "INFO"),
            log_max_bytes=int(os.getenv("HATCHERY_LOG_MAX_BYTES", "2000000")),
            log_backup_count=int(os.getenv("HATCHERY_LOG_BACKUP_COUNT", "5")),
            real_adapter_enabled=_read_bool("HATCHERY_REAL_ADAPTER_ENABLED", False),
            real_default_timeout_sec=int(os.getenv("HATCHERY_REAL_DEFAULT_TIMEOUT_SEC", "30")),
            real_relay_map=_read_relay_map(),
            real_strict_mapping=_read_bool("HATCHERY_REAL_STRICT_MAPPING", False),
        )
