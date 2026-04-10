"""Bridge factory for hatchery business tools."""

from __future__ import annotations

from hatchery.orchestrator_bridge.client import HatcheryServiceClient
from hatchery.orchestrator_bridge.tools import build_tool_registry


class HatcheryOrchestratorBridge:
    def __init__(self, service_url: str):
        self.client = HatcheryServiceClient(service_url)
        self.tool_registry = build_tool_registry(self.client)
