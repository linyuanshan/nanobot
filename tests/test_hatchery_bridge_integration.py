import asyncio
import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import httpx
import pytest
from fastapi.testclient import TestClient

from hatchery.orchestrator_bridge.client import HatcheryServiceClient
from hatchery.orchestrator_bridge.runner import BridgeRunnerSettings, create_bridge_app


class _CommandHandler(BaseHTTPRequestHandler):
    def do_POST(self) -> None:  # noqa: N802
        if self.path != "/api/v1/commands":
            self.send_response(404)
            self.end_headers()
            return
        payload = json.dumps(
            {
                "command_id": "cmd-proxy-001",
                "trace_id": "trace-proxy-001",
                "pool_id": "pool-01",
                "mode": "sim",
                "action_type": "feed",
                "effective_action_type": "feed",
                "params": {"ratio": 0.6, "duration_sec": 120},
                "effective_params": {"ratio": 0.6, "duration_sec": 120},
                "risk_level": "medium",
                "status": "Closed",
                "result_code": "OK",
                "approval_id": None,
                "receipt": None,
                "transition_path": ["Requested", "Closed"],
                "updated_at": "2026-03-21T00:00:00Z",
            }
        ).encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)
        self.wfile.flush()

    def log_message(self, format: str, *args) -> None:  # noqa: A003
        return


@pytest.mark.asyncio
async def test_service_client_ignores_proxy_env_for_local_bridge_calls(monkeypatch) -> None:
    server = ThreadingHTTPServer(("127.0.0.1", 0), _CommandHandler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        monkeypatch.setenv("HTTP_PROXY", "http://127.0.0.1:9")
        monkeypatch.setenv("HTTPS_PROXY", "http://127.0.0.1:9")
        monkeypatch.setenv("NO_PROXY", "")
        client = HatcheryServiceClient(f"http://127.0.0.1:{server.server_address[1]}")

        result = await client.post("/api/v1/commands", {"command_id": "cmd-proxy-001"})
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)

    assert result["status"] == "Closed"
    assert result["result_code"] == "OK"


def test_bridge_runner_returns_bad_gateway_payload_for_upstream_errors() -> None:
    request = httpx.Request("POST", "http://127.0.0.1:8090/api/v1/commands")
    response = httpx.Response(status_code=502, request=request)

    class FailingBridge:
        def __init__(self):
            self.tool_registry = type(
                "Registry",
                (),
                {
                    "tool_names": ["submit_safe_command"],
                    "get": lambda self, name: type(
                        "Tool",
                        (),
                        {
                            "name": "submit_safe_command",
                            "description": "Submit a controlled command.",
                            "parameters": {"type": "object"},
                            "execute": staticmethod(
                                lambda **kwargs: asyncio.sleep(
                                    0,
                                    result=(_ for _ in ()).throw(
                                        httpx.HTTPStatusError("bad gateway", request=request, response=response)
                                    ),
                                )
                            ),
                        },
                    )()
                    if name == "submit_safe_command"
                    else None,
                },
            )()

    app = create_bridge_app(
        settings=BridgeRunnerSettings(service_url="http://127.0.0.1:8090"),
        bridge=FailingBridge(),
        ready_client=type("ReadyClient", (), {"get": staticmethod(lambda path: asyncio.sleep(0, result={"status": "ready"}))})(),
    )
    client = TestClient(app, raise_server_exceptions=False)

    response = client.post("/tools/submit_safe_command/invoke", json={"command_id": "cmd-bad-gateway"})

    assert response.status_code == 502
    assert response.json()["detail"] == "upstream hatchery service error"
