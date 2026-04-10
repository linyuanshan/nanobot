"""Real-device adapter preparation for future gray rollout."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any


@dataclass(slots=True)
class RealExecutionAdapterSettings:
    enabled: bool = False
    relay_map: dict[str, str] = field(default_factory=dict)
    default_timeout_sec: int = 30
    strict_mapping: bool = False


class RealExecutionAdapter:
    def __init__(self, settings: RealExecutionAdapterSettings | None = None):
        self.settings = settings or RealExecutionAdapterSettings()

    def status(self) -> dict[str, Any]:
        if not self.settings.enabled:
            return {
                "state": "disabled",
                "code": "REAL_DISABLED",
                "detail": "real adapter disabled by configuration",
                "mapped_actions": sorted(self.settings.relay_map.keys()),
            }
        if self.settings.strict_mapping and not self.settings.relay_map:
            return {
                "state": "error",
                "code": "E_REAL_RELAY_MAP_EMPTY",
                "detail": "strict mapping enabled but relay map is empty",
                "mapped_actions": [],
            }
        return {
            "state": "ok",
            "code": "OK",
            "detail": "real adapter ready for controlled rollout",
            "mapped_actions": sorted(self.settings.relay_map.keys()),
        }

    def execute(self, command: dict[str, Any]) -> dict[str, Any]:
        action = command["effective_action_type"]
        params = command.get("effective_params") or {}
        mapped_action, map_error = self._map_action(action, params)
        now = datetime.now(UTC).isoformat()

        if map_error is not None:
            return {
                "adapter": "real-relay-adapter-v1",
                "status": "failed",
                "result_code": map_error,
                "mapped_action": mapped_action,
                "started_at": now,
                "finished_at": now,
                "simulated_latency_ms": 0,
                "dry_run": command.get("dry_run", False),
                "error": "real adapter mapping is incomplete for the requested action",
            }

        if not self.settings.enabled and not command.get("dry_run", False):
            return {
                "adapter": "real-relay-adapter-v1",
                "status": "failed",
                "result_code": "E_REAL_ADAPTER_NOT_CONFIGURED",
                "mapped_action": mapped_action,
                "started_at": now,
                "finished_at": now,
                "simulated_latency_ms": 0,
                "dry_run": command.get("dry_run", False),
                "error": "real adapter is disabled; refusing live device control",
            }

        return {
            "adapter": "real-relay-adapter-v1",
            "status": "ok",
            "result_code": "OK",
            "mapped_action": mapped_action,
            "started_at": now,
            "finished_at": now,
            "simulated_latency_ms": 0,
            "dry_run": command.get("dry_run", False),
            "preview_only": True,
            "mapped_actions": sorted(self.settings.relay_map.keys()),
        }

    def _map_action(self, action: str, params: dict[str, Any]) -> tuple[str, str | None]:
        if self.settings.strict_mapping and action not in self.settings.relay_map:
            return (f"unmapped:{action}", "E_REAL_ACTION_NOT_MAPPED")

        relay = self.settings.relay_map.get(action, "relay")
        duration = int(params.get("duration_sec", self.settings.default_timeout_sec))
        if action in {"feed", "aerate_up", "sludge_clean", "water_change"}:
            return (f"{relay}=1 for {duration}s then relay=0", None)
        if action in {"aerate_down", "emergency_stop"}:
            return (f"{relay}=0", None)
        if action == "manual_override_on":
            return (f"{relay}=hold", None)
        if action == "manual_override_off":
            return (f"{relay}=auto", None)
        return (f"{relay}=noop", None)
