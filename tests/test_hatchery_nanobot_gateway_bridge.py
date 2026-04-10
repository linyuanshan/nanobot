import json
import threading
from contextlib import contextmanager
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any

import pytest

from hatchery.orchestrator_bridge.nanobot_integration import register_hatchery_tools
from hatchery.orchestrator_bridge.nanobot_tools import build_hatchery_bridge_tools
from nanobot.agent.loop import AgentLoop
from nanobot.bus.queue import MessageBus
from nanobot.providers.base import LLMProvider, LLMResponse, ToolCallRequest


class _BridgeHandler(BaseHTTPRequestHandler):
    records: list[dict[str, Any]] = []

    def do_POST(self) -> None:  # noqa: N802
        segments = self.path.strip("/").split("/")
        if len(segments) != 3 or segments[0] != "tools" or segments[2] != "invoke":
            self.send_response(404)
            self.end_headers()
            return

        tool_name = segments[1]
        body = self.rfile.read(int(self.headers.get("Content-Length", "0") or "0"))
        payload = json.loads(body.decode("utf-8")) if body else {}

        self.__class__.records.append(
            {
                "tool_name": tool_name,
                "payload": payload,
                "token": self.headers.get("X-Hatchery-Token"),
                "actor": self.headers.get("X-Hatchery-Actor"),
            }
        )

        if tool_name == "query_pool_state":
            result = {
                "tool": tool_name,
                "result": {
                    "site_id": "site-001",
                    "workshop_id": "ws-01",
                    "pool_id": payload.get("pool_id"),
                    "mode": "shadow",
                    "assessment": {"level": "normal"},
                    "water_quality": {"do_mg_l": 6.8},
                },
            }
        elif tool_name == "create_action_plan":
            result = {
                "tool": tool_name,
                "result": {
                    "pool_id": payload.get("pool_id"),
                    "risk_level": "low",
                    "action_type": "feed",
                    "params": {"ratio": 0.6, "duration_sec": 120},
                },
            }
        elif tool_name == "submit_safe_command":
            result = {
                "tool": tool_name,
                "result": {
                    "command_id": payload.get("command_id"),
                    "status": "Closed",
                    "result_code": "OK",
                    "transition_path": ["Requested", "RiskChecked", "Executed", "Closed"],
                },
            }
        else:
            result = {"tool": tool_name, "result": {"ok": True}}

        response = json.dumps(result, ensure_ascii=True).encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(response)))
        self.end_headers()
        self.wfile.write(response)

    def log_message(self, format: str, *args) -> None:  # noqa: A003
        return


@contextmanager
def _running_bridge_server():
    _BridgeHandler.records = []
    server = ThreadingHTTPServer(("127.0.0.1", 0), _BridgeHandler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield server
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)


class _ScriptedProvider(LLMProvider):
    def __init__(self):
        super().__init__(api_key="mock")
        self.step = 0
        self.exposed_tools: list[str] = []

    async def chat(  # type: ignore[override]
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None = None,
        model: str | None = None,
        max_tokens: int = 4096,
        temperature: float = 0.7,
    ) -> LLMResponse:
        self.step += 1
        if self.step == 1:
            self.exposed_tools = [item["function"]["name"] for item in tools or []]
            return LLMResponse(
                content=None,
                tool_calls=[ToolCallRequest(id="tc-1", name="query_pool_state", arguments={"pool_id": "pool-01"})],
            )
        if self.step == 2:
            return LLMResponse(
                content=None,
                tool_calls=[
                    ToolCallRequest(
                        id="tc-2",
                        name="create_action_plan",
                        arguments={"pool_id": "pool-01", "trace_id": "trace-feishu-001"},
                    )
                ],
            )
        if self.step == 3:
            return LLMResponse(
                content=None,
                tool_calls=[
                    ToolCallRequest(
                        id="tc-3",
                        name="submit_safe_command",
                        arguments={
                            "command_id": "cmd-feishu-001",
                            "idempotency_key": "idem-feishu-001",
                            "trace_id": "trace-feishu-001",
                            "mode": "sim",
                            "action_type": "feed",
                            "target": {"site_id": "site-001", "workshop_id": "ws-01", "pool_id": "pool-01"},
                            "params": {"ratio": 0.6, "duration_sec": 120},
                        },
                    )
                ],
            )
        return LLMResponse(content="pool-01 当前低风险，已执行投喂并完成闭环。")

    def get_default_model(self) -> str:
        return "mock-model"


def test_build_hatchery_bridge_tools_keeps_whitelist_shape() -> None:
    tools = build_hatchery_bridge_tools(bridge_url="http://127.0.0.1:8190")
    tool_names = {tool.name for tool in tools}
    assert tool_names == {
        "dispatch_perception_task",
        "create_action_plan",
        "request_high_risk_approval",
        "submit_safe_command",
        "query_command_status",
        "query_pool_state",
        "generate_shift_report",
    }


@pytest.mark.asyncio
async def test_register_tools_invokes_bridge_with_auth_headers(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("USERPROFILE", str(tmp_path))
    with _running_bridge_server() as server:
        bridge_url = f"http://127.0.0.1:{server.server_address[1]}"
        bus = MessageBus()
        provider = _ScriptedProvider()
        agent = AgentLoop(bus=bus, provider=provider, workspace=tmp_path)
        registered = register_hatchery_tools(
            agent.tools,
            bridge_url=bridge_url,
            bridge_token="bridge-token",
            actor="feishu-bot",
        )

        assert "query_pool_state" in registered
        result = await agent.tools.execute("query_pool_state", {"pool_id": "pool-01"})

    payload = json.loads(result)
    assert payload["result"]["pool_id"] == "pool-01"
    assert _BridgeHandler.records[0]["tool_name"] == "query_pool_state"
    assert _BridgeHandler.records[0]["token"] == "bridge-token"
    assert _BridgeHandler.records[0]["actor"] == "feishu-bot"


@pytest.mark.asyncio
async def test_agent_can_complete_pool_check_plan_and_safe_feed_flow(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("USERPROFILE", str(tmp_path))
    with _running_bridge_server() as server:
        bridge_url = f"http://127.0.0.1:{server.server_address[1]}"
        bus = MessageBus()
        provider = _ScriptedProvider()
        agent = AgentLoop(bus=bus, provider=provider, workspace=tmp_path)
        register_hatchery_tools(
            agent.tools,
            bridge_url=bridge_url,
            bridge_token="bridge-token",
            actor="feishu-bot",
        )

        reply = await agent.process_direct("请检查 pool-01 状态，给出动作建议，并在低风险时执行投喂。")

    assert "已执行投喂" in reply
    assert {"query_pool_state", "create_action_plan", "submit_safe_command"}.issubset(provider.exposed_tools)
    assert [item["tool_name"] for item in _BridgeHandler.records] == [
        "query_pool_state",
        "create_action_plan",
        "submit_safe_command",
    ]


@pytest.mark.asyncio
async def test_submit_safe_command_auto_fills_target_from_pool_state(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("USERPROFILE", str(tmp_path))
    with _running_bridge_server() as server:
        bridge_url = f"http://127.0.0.1:{server.server_address[1]}"
        bus = MessageBus()
        provider = _ScriptedProvider()
        agent = AgentLoop(bus=bus, provider=provider, workspace=tmp_path)
        register_hatchery_tools(
            agent.tools,
            bridge_url=bridge_url,
            bridge_token="bridge-token",
            actor="feishu-bot",
        )

        result = await agent.tools.execute(
            "submit_safe_command",
            {
                "command_id": "cmd-auto-fill-001",
                "idempotency_key": "idem-auto-fill-001",
                "trace_id": "trace-auto-fill-001",
                "mode": "shadow",
                "action_type": "feed",
                "target": {"pool_id": "pool-01"},
                "params": {"ratio": 0.6, "duration_sec": 120},
            },
        )

    payload = json.loads(result)
    assert payload["result"]["status"] == "Closed"
    submit = [item for item in _BridgeHandler.records if item["tool_name"] == "submit_safe_command"][0]
    assert submit["payload"]["target"] == {
        "site_id": "site-001",
        "workshop_id": "ws-01",
        "pool_id": "pool-01",
    }
