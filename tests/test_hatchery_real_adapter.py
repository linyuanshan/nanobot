from datetime import UTC, datetime
from pathlib import Path

from fastapi.testclient import TestClient

from hatchery.app import create_app
from hatchery.container import build_container
from hatchery.contracts.api import CommandRequest, CommandTarget
from hatchery.execution.real_adapter import RealExecutionAdapter, RealExecutionAdapterSettings
from hatchery.settings import HatcherySettings


def test_real_adapter_returns_clear_not_configured_receipt() -> None:
    adapter = RealExecutionAdapter(RealExecutionAdapterSettings(enabled=False))

    receipt = adapter.execute(
        {
            "command_id": "cmd-real-001",
            "mode": "real",
            "effective_action_type": "feed",
            "effective_params": {"duration_sec": 120},
            "dry_run": False,
        }
    )

    assert receipt["adapter"] == "real-relay-adapter-v1"
    assert receipt["result_code"] == "E_REAL_ADAPTER_NOT_CONFIGURED"
    assert receipt["mapped_action"] == "relay=1 for 120s then relay=0"


def test_real_adapter_can_preview_mapping_when_enabled_but_dry_run() -> None:
    adapter = RealExecutionAdapter(
        RealExecutionAdapterSettings(
            enabled=True,
            relay_map={"feed": "relay_feed", "emergency_stop": "relay_main"},
            default_timeout_sec=30,
        )
    )

    receipt = adapter.execute(
        {
            "command_id": "cmd-real-002",
            "mode": "real",
            "effective_action_type": "emergency_stop",
            "effective_params": {},
            "dry_run": True,
        }
    )

    assert receipt["adapter"] == "real-relay-adapter-v1"
    assert receipt["result_code"] == "OK"
    assert receipt["mapped_action"] == "relay_main=0"
    assert receipt["dry_run"] is True
    assert datetime.fromisoformat(receipt["started_at"]).tzinfo == UTC


def test_real_mode_command_does_not_fall_back_to_simulated_success(tmp_path) -> None:
    container = build_container(HatcherySettings(database_path=tmp_path / "hatchery.db", enable_scheduler=False))

    command = container.command_service.submit_command(
        CommandRequest(
            command_id="cmd-real-dispatch-001",
            idempotency_key="idem-real-dispatch-001",
            trace_id="trace-real-dispatch-001",
            mode="real",
            action_type="feed",
            target=CommandTarget(site_id="site-001", workshop_id="ws-001", pool_id="pool-01"),
            params={"ratio": 0.60, "duration_sec": 120},
            preconditions={},
            deadline_sec=180,
            degrade_policy="",
            dry_run=False,
        )
    )

    assert command.status == "Closed"
    assert command.result_code == "E_REAL_ADAPTER_NOT_CONFIGURED"
    assert "Failed" in command.transition_path


def test_real_adapter_fails_when_strict_mapping_has_no_action_entry() -> None:
    adapter = RealExecutionAdapter(
        RealExecutionAdapterSettings(
            enabled=True,
            strict_mapping=True,
            relay_map={"emergency_stop": "relay_main"},
        )
    )

    receipt = adapter.execute(
        {
            "command_id": "cmd-real-003",
            "mode": "real",
            "effective_action_type": "feed",
            "effective_params": {"duration_sec": 120},
            "dry_run": False,
        }
    )

    assert receipt["status"] == "failed"
    assert receipt["result_code"] == "E_REAL_ACTION_NOT_MAPPED"
    assert receipt["mapped_action"] == "unmapped:feed"


def test_readyz_reports_real_adapter_error_when_live_mapping_is_not_ready(tmp_path: Path) -> None:
    app = create_app(
        HatcherySettings(
            database_path=tmp_path / "hatchery.db",
            enable_scheduler=False,
            real_adapter_enabled=True,
            real_strict_mapping=True,
            real_relay_map={},
        )
    )
    client = TestClient(app)

    health = client.get("/healthz")
    ready = client.get("/readyz")

    assert health.status_code == 200
    assert health.json()["checks"]["real_adapter"] == "error"
    assert ready.status_code == 503
    assert ready.json()["checks"]["real_adapter"] == "error"
