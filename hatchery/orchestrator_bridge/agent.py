"""Custom AgentLoop that exposes only hatchery business tools."""

from __future__ import annotations

from nanobot.agent.loop import AgentLoop

from hatchery.orchestrator_bridge.client import HatcheryServiceClient
from hatchery.orchestrator_bridge.tools import build_tool_registry


class HatcheryAgentLoop(AgentLoop):
    def __init__(self, *args, service_url: str, **kwargs):
        self._bridge_client = HatcheryServiceClient(service_url)
        super().__init__(*args, **kwargs)

    def _register_default_tools(self) -> None:
        self.tools = build_tool_registry(self._bridge_client)
