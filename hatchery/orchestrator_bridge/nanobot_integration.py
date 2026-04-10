"""Optional integration hooks to register hatchery bridge tools into nanobot."""

from __future__ import annotations

from nanobot.agent.tools.registry import ToolRegistry

from hatchery.orchestrator_bridge.nanobot_tools import build_hatchery_bridge_tools


def register_hatchery_tools(
    registry: ToolRegistry,
    *,
    bridge_url: str,
    bridge_token: str = "",
    actor: str = "nanobot-gateway",
) -> list[str]:
    """Register hatchery bridge tools into a nanobot ToolRegistry."""
    tools = build_hatchery_bridge_tools(
        bridge_url=bridge_url,
        bridge_token=bridge_token,
        actor=actor,
    )
    for tool in tools:
        registry.register(tool)
    return [tool.name for tool in tools]

