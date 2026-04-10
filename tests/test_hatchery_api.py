from pathlib import Path

from fastapi.testclient import TestClient

from hatchery.app import HatcherySettings, create_app


def make_client(tmp_path: Path) -> TestClient:
    app = create_app(HatcherySettings(database_path=tmp_path / "hatchery.db"))
    return TestClient(app)


def test_water_quality_ingest_normalizes_payload_and_updates_state(tmp_path: Path) -> None:
    client = make_client(tmp_path)

    response = client.post(
        "/api/v1/telemetry/water-quality",
        json={
            "site_id": "site-001",
            "workshop_id": "ws-001",
            "pool_id": "pool-01",
            "mode": "sim",
            "ts": "2026-02-07T10:00:00Z",
            "payload": {
                "relay": 0,
                "ph": 7.42,
                "hzd": 3,
                "rjy": 2.95,
                "temp": 24.7,
            },
        },
    )

    assert response.status_code == 202
    body = response.json()
    assert body["event_type"] == "telemetry.water_quality.v1"
    assert body["payload"]["do_mg_l"] == 2.95
    assert body["payload"]["temp_c"] == 24.7
    assert body["payload"]["relay_state"] == 0

    state_response = client.get("/api/v1/pools/pool-01/state")
    assert state_response.status_code == 200
    state = state_response.json()
    assert state["pool_id"] == "pool-01"
    assert state["assessment"]["level"] == "danger"
    assert any("DO" in reason for reason in state["assessment"]["reasons"])


def test_high_risk_command_requires_approval_then_executes_after_confirm(tmp_path: Path) -> None:
    client = make_client(tmp_path)

    response = client.post(
        "/api/v1/commands",
        json={
            "command_id": "cmd-20260207-0001",
            "idempotency_key": "pool-01-water-change-202602071000",
            "trace_id": "trace-001",
            "mode": "shadow",
            "action_type": "water_change",
            "target": {
                "site_id": "site-001",
                "workshop_id": "ws-001",
                "pool_id": "pool-01",
            },
            "params": {
                "ratio": 0.30,
                "duration_sec": 180,
            },
            "preconditions": {
                "min_do_mg_l": 5.0,
                "max_temp_c": 29.0,
            },
            "deadline_sec": 180,
            "degrade_policy": "aerate_up_on_timeout",
            "dry_run": True,
        },
    )

    assert response.status_code == 202
    body = response.json()
    assert body["status"] == "PendingApproval"
    assert body["approval_id"]

    confirm = client.post(
        f"/api/v1/approvals/{body['approval_id']}/confirm",
        json={"operator": "owner-001", "reason": "approved in test"},
    )
    assert confirm.status_code == 200

    command = client.get("/api/v1/commands/cmd-20260207-0001")
    assert command.status_code == 200
    payload = command.json()
    assert payload["status"] == "Closed"
    assert payload["result_code"] == "OK"
    assert payload["effective_action_type"] == "water_change"
    assert payload["receipt"]["adapter"] == "shadow-relay-adapter-v1"


def test_duplicate_idempotency_key_returns_conflict(tmp_path: Path) -> None:
    client = make_client(tmp_path)

    command_payload = {
        "command_id": "cmd-20260207-0002",
        "idempotency_key": "pool-01-feed-202602071100",
        "trace_id": "trace-002",
        "mode": "sim",
        "action_type": "feed",
        "target": {
            "site_id": "site-001",
            "workshop_id": "ws-001",
            "pool_id": "pool-01",
        },
        "params": {
            "ratio": 0.60,
            "duration_sec": 120,
        },
        "preconditions": {
            "min_do_mg_l": 5.0,
            "max_temp_c": 29.0,
        },
        "deadline_sec": 180,
        "degrade_policy": "feed_60_percent_on_timeout",
        "dry_run": True,
    }

    first = client.post("/api/v1/commands", json=command_payload)
    assert first.status_code == 200

    duplicate = client.post(
        "/api/v1/commands",
        json={**command_payload, "command_id": "cmd-20260207-0003", "trace_id": "trace-003"},
    )
    assert duplicate.status_code == 409
    assert duplicate.json()["result_code"] == "E_DUPLICATE_IDEMPOTENCY"
