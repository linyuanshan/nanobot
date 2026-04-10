from pathlib import Path

from fastapi.testclient import TestClient

from hatchery.app import HatcherySettings, create_app


def make_client(tmp_path: Path) -> TestClient:
    app = create_app(HatcherySettings(database_path=tmp_path / "hatchery.db", enable_scheduler=False))
    return TestClient(app)


def _submit_high_risk_command(client: TestClient, *, command_id: str, trace_id: str, pool_id: str) -> dict:
    response = client.post(
        "/api/v1/commands",
        json={
            "command_id": command_id,
            "idempotency_key": f"{pool_id}-water-change-{command_id}",
            "trace_id": trace_id,
            "mode": "shadow",
            "action_type": "water_change",
            "target": {
                "site_id": "site-001",
                "workshop_id": "ws-001",
                "pool_id": pool_id,
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
    return response.json()


def test_ops_endpoints_expose_command_timeline_summary_and_filtered_audits(tmp_path: Path) -> None:
    client = make_client(tmp_path)

    submitted = _submit_high_risk_command(
        client,
        command_id="cmd-ops-001",
        trace_id="trace-ops-001",
        pool_id="pool-01",
    )
    confirm = client.post(
        f"/api/v1/approvals/{submitted['approval_id']}/confirm",
        json={"operator": "owner-001", "reason": "ops acceptance"},
    )
    assert confirm.status_code == 200

    timeline = client.get("/api/v1/ops/commands/cmd-ops-001/timeline")
    assert timeline.status_code == 200
    timeline_payload = timeline.json()
    assert timeline_payload["command_id"] == "cmd-ops-001"
    assert timeline_payload["transitions"][0]["to_status"] == "Requested"
    assert any(item["to_status"] == "Approved" for item in timeline_payload["transitions"])

    summary = client.get("/api/v1/ops/summary")
    assert summary.status_code == 200
    summary_payload = summary.json()
    assert summary_payload["commands"]["total"] >= 1
    assert summary_payload["commands"]["by_status"]["Closed"] >= 1
    assert summary_payload["approvals"]["by_status"]["Approved"] >= 1

    filtered = client.get("/api/v1/audits", params={"trace_id": "trace-ops-001", "event_type": "command.result.v1"})
    assert filtered.status_code == 200
    filtered_payload = filtered.json()
    assert len(filtered_payload) == 1
    assert filtered_payload[0]["event_type"] == "command.result.v1"

    exported = client.get("/api/v1/audits/export", params={"trace_id": "trace-ops-001"})
    assert exported.status_code == 200
    assert "trace-ops-001" in exported.text


def test_ops_control_commands_execute_manual_override_and_emergency_stop(tmp_path: Path) -> None:
    client = make_client(tmp_path)

    manual = client.post(
        "/api/v1/ops/control-commands",
        json={
            "mode": "sim",
            "action_type": "manual_override_on",
            "operator": "ops-001",
            "reason": "maintenance window",
            "target": {
                "site_id": "site-001",
                "workshop_id": "ws-001",
                "pool_id": "pool-02",
            },
            "params": {},
        },
    )
    assert manual.status_code == 200
    manual_payload = manual.json()
    assert manual_payload["status"] == "Closed"
    assert manual_payload["effective_action_type"] == "manual_override_on"

    emergency = client.post(
        "/api/v1/ops/control-commands",
        json={
            "mode": "sim",
            "action_type": "emergency_stop",
            "operator": "ops-001",
            "reason": "safety stop",
            "target": {
                "site_id": "site-001",
                "workshop_id": "ws-001",
                "pool_id": "pool-02",
            },
            "params": {},
        },
    )
    assert emergency.status_code == 200
    emergency_payload = emergency.json()
    assert emergency_payload["status"] == "Closed"
    assert emergency_payload["receipt"]["mapped_action"] == "relay=0"
