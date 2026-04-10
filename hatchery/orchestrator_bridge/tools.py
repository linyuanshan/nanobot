"""Whitelist business tools for the orchestrator bridge."""

from __future__ import annotations

import json
from typing import Any

from hatchery.orchestrator_bridge.client import HatcheryServiceClient


class BridgeTool:
    def __init__(self, name: str, description: str, parameters: dict[str, Any], handler):
        self._name = name
        self._description = description
        self._parameters = parameters
        self._handler = handler

    @property
    def name(self) -> str:
        return self._name

    @property
    def description(self) -> str:
        return self._description

    @property
    def parameters(self) -> dict[str, Any]:
        return self._parameters

    async def execute(self, **kwargs: Any) -> str:
        result = await self._handler(**kwargs)
        return json.dumps(result, ensure_ascii=True, sort_keys=True)


class BridgeToolRegistry:
    def __init__(self):
        self._tools: dict[str, BridgeTool] = {}

    def register(self, tool: BridgeTool) -> None:
        self._tools[tool.name] = tool

    def get(self, name: str) -> BridgeTool | None:
        return self._tools.get(name)

    @property
    def tool_names(self) -> list[str]:
        return list(self._tools.keys())


def build_tool_registry(client: HatcheryServiceClient) -> BridgeToolRegistry:
    registry = BridgeToolRegistry()
    registry.register(
        BridgeTool(
            name="dispatch_perception_task",
            description="Replay or submit a bio-perception event into the hatchery service.",
            parameters={
                "type": "object",
                "properties": {
                    "site_id": {"type": "string"},
                    "workshop_id": {"type": "string"},
                    "pool_id": {"type": "string"},
                    "mode": {"type": "string", "enum": ["sim", "shadow", "real"]},
                    "ts": {"type": "string"},
                    "payload": {"type": "object"},
                },
                "required": ["site_id", "workshop_id", "pool_id", "mode", "ts", "payload"],
            },
            handler=lambda **kwargs: client.post("/api/v1/perception/bio", kwargs),
        )
    )
    registry.register(
        BridgeTool(
            name="create_action_plan",
            description="Create a policy action plan from the latest pool state.",
            parameters={
                "type": "object",
                "properties": {
                    "pool_id": {"type": "string"},
                    "trace_id": {"type": "string"},
                    "model_version": {"type": "string"},
                },
                "required": ["pool_id"],
            },
            handler=lambda **kwargs: client.post("/api/v1/decisions/plan", kwargs),
        )
    )
    registry.register(
        BridgeTool(
            name="request_high_risk_approval",
            description="Query or request approval for a high-risk command already known by the safety kernel.",
            parameters={
                "type": "object",
                "properties": {
                    "command_id": {"type": "string"},
                    "timeout_sec": {"type": "integer"},
                    "remind_at_sec": {"type": "integer"},
                    "provider": {"type": "string"},
                },
                "required": ["command_id"],
            },
            handler=lambda **kwargs: client.post("/api/v1/approvals/requests", kwargs),
        )
    )
    registry.register(
        BridgeTool(
            name="submit_safe_command",
            description="Submit a controlled command into the hatchery safety kernel.",
            parameters={
                "type": "object",
                "properties": {
                    "command_id": {"type": "string"},
                    "idempotency_key": {"type": "string"},
                    "trace_id": {"type": "string"},
                    "mode": {"type": "string", "enum": ["sim", "shadow", "real"]},
                    "action_type": {"type": "string"},
                    "target": {"type": "object"},
                    "params": {"type": "object"},
                    "preconditions": {"type": "object"},
                    "deadline_sec": {"type": "integer"},
                    "degrade_policy": {"type": "string"},
                    "dry_run": {"type": "boolean"},
                },
                "required": ["command_id", "idempotency_key", "trace_id", "mode", "action_type", "target", "params"],
            },
            handler=lambda **kwargs: client.post("/api/v1/commands", kwargs),
        )
    )
    registry.register(
        BridgeTool(
            name="query_command_status",
            description="Query a previously submitted command status from the hatchery service.",
            parameters={
                "type": "object",
                "properties": {"command_id": {"type": "string"}},
                "required": ["command_id"],
            },
            handler=lambda command_id, **kwargs: client.get(f"/api/v1/commands/{command_id}"),
        )
    )
    registry.register(
        BridgeTool(
            name="query_pool_state",
            description="Query the current pool state from the hatchery service.",
            parameters={
                "type": "object",
                "properties": {"pool_id": {"type": "string"}},
                "required": ["pool_id"],
            },
            handler=lambda pool_id, **kwargs: client.get(f"/api/v1/pools/{pool_id}/state"),
        )
    )
    registry.register(
        BridgeTool(
            name="generate_shift_report",
            description="Read audit history for reporting and operator handoff.",
            parameters={
                "type": "object",
                "properties": {"trace_id": {"type": "string"}},
            },
            handler=lambda trace_id=None, **kwargs: client.get(
                f"/api/v1/audits{('?trace_id=' + trace_id) if trace_id else ''}"
            ),
        )
    )
    return registry
