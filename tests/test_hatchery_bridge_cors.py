from fastapi.testclient import TestClient

from hatchery.orchestrator_bridge.runner import create_bridge_app


def test_bridge_runner_allows_browser_cors_preflight() -> None:
    client = TestClient(create_bridge_app())

    response = client.options(
        "/tools/query_pool_state/invoke",
        headers={
            "origin": "http://127.0.0.1:8090",
            "access-control-request-method": "POST",
        },
    )

    assert response.status_code == 200
    assert response.headers["access-control-allow-origin"] == "*"
