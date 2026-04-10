from datetime import UTC, datetime, timedelta
from pathlib import Path

from hatchery.app import HatcherySettings
from hatchery.container import build_container
from hatchery.contracts.api import CommandRequest, CommandTarget, CommandTargetRef


def build_request(command_id: str, idempotency_key: str) -> CommandRequest:
    return CommandRequest(
        command_id=command_id,
        idempotency_key=idempotency_key,
        trace_id=f"trace-{command_id}",
        mode="sim",
        action_type="water_change",
        target=CommandTarget(site_id="site-001", workshop_id="ws-001", pool_id="pool-01"),
        params={"ratio": 0.30, "duration_sec": 180},
        preconditions={"min_do_mg_l": 5.0, "max_temp_c": 29.0},
        deadline_sec=180,
        degrade_policy="aerate_up_on_timeout",
        dry_run=True,
    )


def test_timeout_degrades_water_change_to_aerate_up(tmp_path: Path) -> None:
    container = build_container(HatcherySettings(database_path=tmp_path / "hatchery.db"))
    service = container.command_service

    submitted = service.submit_command(build_request("cmd-timeout-001", "idem-timeout-001"))
    assert submitted.status == "PendingApproval"
    assert submitted.approval_id

    due_now = datetime.now(UTC) + timedelta(minutes=4)
    processed = service.process_due_approvals(now=due_now)
    assert processed.timed_out == 1

    command = service.get_command("cmd-timeout-001")
    assert command.status == "Closed"
    assert command.effective_action_type == "aerate_up"
    assert command.result_code == "OK"
    assert "TimedOut" in command.transition_path
    assert "Degraded" in command.transition_path
    assert command.receipt["adapter"] == "sim-relay-adapter-v1"
