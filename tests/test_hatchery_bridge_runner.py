import asyncio

from fastapi.testclient import TestClient

from hatchery.orchestrator_bridge.runner import BridgeRunnerSettings, create_bridge_app


class DummyBridge:
    def __init__(self):
        self.tool_registry = type(
            "Registry",
            (),
            {
                "tool_names": ["query_pool_state"],
                "get": lambda self, name: type(
                    "Tool",
                    (),
                    {
                        "name": "query_pool_state",
                        "description": "Query the current pool state.",
                        "parameters": {"type": "object"},
                        "execute": staticmethod(lambda **kwargs: asyncio.sleep(0, result='{"pool_id":"pool-01"}')),
                    },
                )()
                if name == "query_pool_state"
                else None,
            },
        )()


class ReadyClient:
    async def get(self, path: str) -> dict:
        if path == "/readyz":
            return {"status": "ready"}
        raise AssertionError(path)


def test_bridge_runner_exposes_health_tools_and_invocation() -> None:
    app = create_bridge_app(
        settings=BridgeRunnerSettings(service_url="http://hatchery.test"),
        bridge=DummyBridge(),
        ready_client=ReadyClient(),
    )
    client = TestClient(app)

    health = client.get("/healthz")
    assert health.status_code == 200
    assert health.json()["status"] == "ok"
    assert health.json()["tool_count"] == 1

    ready = client.get("/readyz")
    assert ready.status_code == 200
    assert ready.json()["status"] == "ready"

    tools = client.get("/tools")
    assert tools.status_code == 200
    assert tools.json()["tools"][0]["name"] == "query_pool_state"

    invoke = client.post("/tools/query_pool_state/invoke", json={"pool_id": "pool-01"})
    assert invoke.status_code == 200
    assert invoke.json()["result"]["pool_id"] == "pool-01"
