from hatchery.orchestrator_bridge.bridge import HatcheryOrchestratorBridge


def test_orchestrator_bridge_only_exposes_whitelisted_tools() -> None:
    bridge = HatcheryOrchestratorBridge(service_url="http://example.test")

    tool_names = set(bridge.tool_registry.tool_names)
    assert tool_names == {
        "dispatch_perception_task",
        "create_action_plan",
        "request_high_risk_approval",
        "submit_safe_command",
        "query_command_status",
        "query_pool_state",
        "generate_shift_report",
    }
    assert "exec" not in tool_names
    assert "read_file" not in tool_names
