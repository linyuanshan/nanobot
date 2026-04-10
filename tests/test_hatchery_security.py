from pathlib import Path

from fastapi.testclient import TestClient

from hatchery.app import HatcherySettings, create_app
from hatchery.orchestrator_bridge.runner import BridgeRunnerSettings, create_bridge_app


def make_secured_client(tmp_path: Path) -> TestClient:
    app = create_app(
        HatcherySettings(
            database_path=tmp_path / "hatchery.db",
            enable_scheduler=False,
            auth_enabled=True,
            auth_tokens={
                "viewer-token": "viewer",
                "operator-token": "operator",
                "admin-token": "admin",
            },
        )
    )
    return TestClient(app)


def _headers(token: str, actor: str = "tester") -> dict[str, str]:
    return {
        "X-Hatchery-Token": token,
        "X-Hatchery-Actor": actor,
    }


def test_submit_command_requires_token_when_auth_enabled(tmp_path: Path) -> None:
    client = make_secured_client(tmp_path)

    response = client.post(
        "/api/v1/commands",
        json={
            "command_id": "cmd-auth-001",
            "idempotency_key": "idem-auth-001",
            "trace_id": "trace-auth-001",
            "mode": "sim",
            "action_type": "feed",
            "target": {
                "site_id": "site-001",
                "workshop_id": "ws-001",
                "pool_id": "pool-01",
            },
            "params": {
                "ratio": 0.6,
                "duration_sec": 120,
            },
            "preconditions": {},
            "deadline_sec": 180,
            "degrade_policy": "",
            "dry_run": True,
        },
    )

    assert response.status_code == 401


def test_real_mode_command_requires_admin_role(tmp_path: Path) -> None:
    client = make_secured_client(tmp_path)

    response = client.post(
        "/api/v1/commands",
        headers=_headers("operator-token"),
        json={
            "command_id": "cmd-auth-real-001",
            "idempotency_key": "idem-auth-real-001",
            "trace_id": "trace-auth-real-001",
            "mode": "real",
            "action_type": "feed",
            "target": {
                "site_id": "site-001",
                "workshop_id": "ws-001",
                "pool_id": "pool-01",
            },
            "params": {
                "ratio": 0.6,
                "duration_sec": 120,
            },
            "preconditions": {},
            "deadline_sec": 180,
            "degrade_policy": "",
            "dry_run": False,
        },
    )

    assert response.status_code == 403


def test_ops_control_requires_admin_but_admin_can_execute(tmp_path: Path) -> None:
    client = make_secured_client(tmp_path)

    forbidden = client.post(
        "/api/v1/ops/control-commands",
        headers=_headers("operator-token", actor="ops-operator"),
        json={
            "mode": "sim",
            "action_type": "manual_override_on",
            "operator": "ops-operator",
            "reason": "maintenance",
            "target": {
                "site_id": "site-001",
                "workshop_id": "ws-001",
                "pool_id": "pool-01",
            },
            "params": {},
            "dry_run": True,
        },
    )
    allowed = client.post(
        "/api/v1/ops/control-commands",
        headers=_headers("admin-token", actor="ops-admin"),
        json={
            "mode": "sim",
            "action_type": "manual_override_on",
            "operator": "ops-admin",
            "reason": "maintenance",
            "target": {
                "site_id": "site-001",
                "workshop_id": "ws-001",
                "pool_id": "pool-01",
            },
            "params": {},
            "dry_run": True,
        },
    )

    assert forbidden.status_code == 403
    assert allowed.status_code == 200
    assert allowed.json()["status"] == "Closed"


def test_bridge_tools_require_token_when_bridge_auth_enabled() -> None:
    app = create_bridge_app(
        settings=BridgeRunnerSettings(
            service_url="http://127.0.0.1:8090",
            auth_enabled=True,
            auth_tokens={"bridge-token": "operator"},
        ),
        bridge=type(
            "DummyBridge",
            (),
            {
                "tool_registry": type(
                    "Registry",
                    (),
                    {
                        "tool_names": [],
                        "get": staticmethod(lambda name: None),
                    },
                )()
            },
        )(),
        ready_client=type("ReadyClient", (), {"get": staticmethod(lambda path: {"status": "ready"})})(),
    )
    client = TestClient(app)

    health = client.get("/healthz")
    unauthorized = client.get("/tools")
    authorized = client.get("/tools", headers=_headers("bridge-token"))

    assert health.status_code == 200
    assert unauthorized.status_code == 401
    assert authorized.status_code == 200
