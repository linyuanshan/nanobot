"""Sim/shadow/real relay execution."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from hatchery.execution.real_adapter import RealExecutionAdapter, RealExecutionAdapterSettings


class ExecutionService:
    def __init__(self, real_adapter: RealExecutionAdapter | None = None):
        self.real_adapter = real_adapter or RealExecutionAdapter(RealExecutionAdapterSettings())

    def execute(self, command: dict[str, Any]) -> dict[str, Any]:
        if command["mode"] == "real":
            return self.real_adapter.execute(command)

        adapter = "shadow-relay-adapter-v1" if command["mode"] == "shadow" else "sim-relay-adapter-v1"
        effective_action = command["effective_action_type"]
        params = command["effective_params"]

        if effective_action in {"feed", "aerate_up", "sludge_clean", "water_change"}:
            mapped_action = f"relay=1 for {params.get('duration_sec', 0)}s then relay=0"
        elif effective_action in {"aerate_down", "emergency_stop"}:
            mapped_action = "relay=0"
        elif effective_action == "manual_override_on":
            mapped_action = "relay=hold"
        elif effective_action == "manual_override_off":
            mapped_action = "relay=auto"
        else:
            mapped_action = "relay=0"

        now = datetime.now(UTC)
        return {
            "adapter": adapter,
            "status": "ok",
            "result_code": "OK",
            "mapped_action": mapped_action,
            "started_at": now.isoformat(),
            "finished_at": now.isoformat(),
            "simulated_latency_ms": 250 if command["mode"] == "sim" else 520,
            "dry_run": command["dry_run"],
        }
