"""Safety kernel and command state machine."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import uuid4

from hatchery.audit import AuditService
from hatchery.contracts.api import (
    CommandRequest,
    CommandTimelineView,
    CommandView,
    DueApprovalResult,
    OpsControlCommandRequest,
    TransitionRecord,
)
from hatchery.db import HatcheryRepository
from hatchery.execution import ExecutionService
from hatchery.verification import VerificationService


class CommandService:
    def __init__(
        self,
        repository: HatcheryRepository,
        audit_service: AuditService,
        execution_service: ExecutionService,
        verification_service: VerificationService,
    ):
        self.repository = repository
        self.audit_service = audit_service
        self.execution_service = execution_service
        self.verification_service = verification_service
        self.mqtt_bridge = None

    def set_mqtt_bridge(self, mqtt_bridge: object) -> None:
        self.mqtt_bridge = mqtt_bridge

    def _transition(self, command_id: str, current_status: str | None, next_status: str, reason: str) -> None:
        self.repository.insert_transition(
            command_id=command_id,
            from_status=current_status,
            to_status=next_status,
            reason=reason,
        )
        self.repository.update_command(command_id, status=next_status, updated_at=datetime.now(UTC).isoformat())

    def _risk_level(self, request: CommandRequest) -> str:
        if request.action_type == "feed":
            return "high" if float(request.params.get("ratio", 0)) > 0.6 else "medium"
        return {
            "aerate_up": "medium",
            "aerate_down": "low",
            "sludge_clean": "medium",
            "water_change": "high",
            "manual_override_on": "high",
            "manual_override_off": "medium",
            "emergency_stop": "critical",
        }.get(request.action_type, "medium")

    def _requires_approval(self, risk_level: str, action_type: str) -> bool:
        return risk_level == "high" and action_type != "emergency_stop"

    def submit_command(self, request: CommandRequest, *, actor: str = "system") -> CommandView:
        return self._submit_command_internal(request, operator=actor, reason="command submitted")

    def submit_operational_control(self, request: OpsControlCommandRequest, *, actor: str = "system") -> CommandView:
        command_request = CommandRequest(
            command_id=f"ops-{request.action_type}-{uuid4()}",
            idempotency_key=f"ops-{request.action_type}-{request.target.pool_id}-{uuid4()}",
            trace_id=f"trace-ops-{uuid4()}",
            mode=request.mode,
            action_type=request.action_type,
            target=request.target,
            params=request.params,
            preconditions={},
            deadline_sec=60,
            degrade_policy="",
            dry_run=request.dry_run,
        )
        return self._submit_command_internal(
            command_request,
            bypass_approval=True,
            operator=actor,
            reason=request.reason,
        )

    def _submit_command_internal(
        self,
        request: CommandRequest,
        *,
        bypass_approval: bool = False,
        operator: str = "system",
        reason: str = "command submitted",
    ) -> CommandView:
        duplicate = self.repository.get_command_by_idempotency(request.idempotency_key)
        if duplicate:
            duplicate["result_code"] = "E_DUPLICATE_IDEMPOTENCY"
            return self._to_view(duplicate)

        risk_level = self._risk_level(request)
        command = {
            "command_id": request.command_id,
            "idempotency_key": request.idempotency_key,
            "trace_id": request.trace_id,
            "site_id": request.target.site_id,
            "workshop_id": request.target.workshop_id,
            "pool_id": request.target.pool_id,
            "mode": request.mode,
            "action_type": request.action_type,
            "effective_action_type": request.action_type,
            "params": request.params,
            "effective_params": dict(request.params),
            "preconditions": request.preconditions,
            "risk_level": risk_level,
            "status": "Requested",
            "result_code": "ACCEPTED_ASYNC" if self._requires_approval(risk_level, request.action_type) and not bypass_approval else "OK",
            "approval_id": None,
            "deadline_sec": request.deadline_sec,
            "degrade_policy": request.degrade_policy,
            "dry_run": request.dry_run,
            "receipt": None,
            "updated_at": datetime.now(UTC).isoformat(),
        }
        self.repository.insert_command(command)
        self.repository.insert_transition(
            command_id=request.command_id,
            from_status=None,
            to_status="Requested",
            reason=reason,
        )
        self.audit_service.record(
            trace_id=request.trace_id,
            event_type="command.request.v1",
            reason=reason,
            operator=operator,
            payload={
                "command_id": request.command_id,
                "action_type": request.action_type,
                "mode": request.mode,
                "risk_level": risk_level,
            },
            mode=request.mode,
            site_id=request.target.site_id,
            workshop_id=request.target.workshop_id,
            pool_id=request.target.pool_id,
        )
        self._transition(request.command_id, "Requested", "RiskChecked", "risk evaluated")

        if self._requires_approval(risk_level, request.action_type) and not bypass_approval:
            approval_id = self._create_approval(command)
            self.repository.update_command(request.command_id, approval_id=approval_id, result_code="E_RISK_NOT_APPROVED")
            self._transition(request.command_id, "RiskChecked", "PendingApproval", "high-risk approval required")
            current = self.repository.get_command_by_id(request.command_id)
            assert current is not None
            return self._to_view(current)

        if bypass_approval:
            self.audit_service.record(
                trace_id=request.trace_id,
                event_type="ops.control.v1",
                reason=reason,
                operator=operator,
                payload={"command_id": request.command_id, "action_type": request.action_type},
                mode=request.mode,
                site_id=request.target.site_id,
                workshop_id=request.target.workshop_id,
                pool_id=request.target.pool_id,
            )

        self._dispatch(request.command_id, reason=reason)
        current = self.repository.get_command_by_id(request.command_id)
        assert current is not None
        return self._to_view(current)

    def _create_approval(self, command: dict[str, Any]) -> str:
        now = datetime.now(UTC)
        approval_id = f"apr-{uuid4()}"
        self.repository.insert_approval(
            {
                "approval_id": approval_id,
                "command_id": command["command_id"],
                "trace_id": command["trace_id"],
                "pool_id": command["pool_id"],
                "provider": "local",
                "status": "PendingApproval",
                "decision": "pending",
                "requested_at": now.isoformat(),
                "remind_at": (now + timedelta(minutes=2)).isoformat(),
                "timeout_at": (now + timedelta(minutes=3)).isoformat(),
                "last_reminded_at": None,
                "operator": "system",
                "reason": "high-risk command requires confirmation",
            }
        )
        self.audit_service.record(
            trace_id=command["trace_id"],
            event_type="approval.request.v1",
            reason="approval requested",
            payload={"command_id": command["command_id"], "approval_id": approval_id},
            mode=command["mode"],
            site_id=command["site_id"],
            workshop_id=command["workshop_id"],
            pool_id=command["pool_id"],
        )
        return approval_id

    def confirm_approval(self, approval_id: str, operator: str, reason: str | None = None) -> CommandView:
        approval = self.repository.get_approval(approval_id)
        if not approval:
            raise KeyError(approval_id)
        self.repository.update_approval(
            approval_id,
            status="Approved",
            decision="approved",
            operator=operator,
            reason=reason or "approved",
        )
        self._transition(approval["command_id"], "PendingApproval", "Approved", "approval confirmed")
        command = self.repository.get_command_by_id(approval["command_id"])
        assert command is not None
        self.audit_service.record(
            trace_id=approval["trace_id"],
            event_type="approval.reply.v1",
            reason="approval confirmed",
            operator=operator,
            payload={"approval_id": approval_id},
            mode=command["mode"],
            site_id=command["site_id"],
            workshop_id=command["workshop_id"],
            pool_id=command["pool_id"],
        )
        self._dispatch(approval["command_id"], reason="approval confirmed")
        current = self.repository.get_command_by_id(approval["command_id"])
        assert current is not None
        return self._to_view(current)

    def reject_approval(self, approval_id: str, operator: str, reason: str | None = None) -> CommandView:
        approval = self.repository.get_approval(approval_id)
        if not approval:
            raise KeyError(approval_id)
        self.repository.update_approval(
            approval_id,
            status="Rejected",
            decision="rejected",
            operator=operator,
            reason=reason or "rejected",
        )
        self._transition(approval["command_id"], "PendingApproval", "Rejected", "approval rejected")
        self._transition(approval["command_id"], "Rejected", "Closed", "command closed after rejection")
        self.repository.update_command(approval["command_id"], result_code="E_RISK_NOT_APPROVED", updated_at=datetime.now(UTC).isoformat())
        command = self.repository.get_command_by_id(approval["command_id"])
        assert command is not None
        self.audit_service.record(
            trace_id=approval["trace_id"],
            event_type="approval.reply.v1",
            reason="approval rejected",
            operator=operator,
            payload={"approval_id": approval_id},
            mode=command["mode"],
            site_id=command["site_id"],
            workshop_id=command["workshop_id"],
            pool_id=command["pool_id"],
        )
        return self._to_view(command)

    def process_due_approvals(self, now: datetime | None = None) -> DueApprovalResult:
        current = now or datetime.now(UTC)
        result = DueApprovalResult()

        for approval in self.repository.list_pending_reminders(current.isoformat()):
            self.repository.update_approval(approval["approval_id"], last_reminded_at=current.isoformat())
            result.reminded += 1
            command = self.repository.get_command_by_id(approval["command_id"])
            if command is None:
                continue
            self.audit_service.record(
                trace_id=approval["trace_id"],
                event_type="alert.event.v1",
                reason="approval reminder emitted",
                payload={"approval_id": approval["approval_id"]},
                mode=command["mode"],
                site_id=command["site_id"],
                workshop_id=command["workshop_id"],
                pool_id=command["pool_id"],
            )
            self._publish_alert(command, "approval reminder emitted", {"approval_id": approval["approval_id"]})

        for approval in self.repository.list_due_pending_approvals(current.isoformat()):
            self.repository.update_approval(
                approval["approval_id"],
                status="TimedOut",
                decision="timed_out",
                operator="system",
                reason="approval timeout reached",
            )
            self._transition(approval["command_id"], "PendingApproval", "TimedOut", "approval timeout reached")
            self._transition(approval["command_id"], "TimedOut", "Degraded", "timeout degrade policy applied")
            self._apply_timeout_degrade(approval["command_id"])
            result.timed_out += 1
        return result

    def _apply_timeout_degrade(self, command_id: str) -> None:
        command = self.repository.get_command_by_id(command_id)
        assert command is not None

        if command["action_type"] == "water_change":
            command["effective_params"] = {"duration_sec": command["params"].get("duration_sec", 180)}
            self.repository.update_command(
                command_id,
                effective_action_type="aerate_up",
                effective_params=command["effective_params"],
                result_code="ACCEPTED_ASYNC",
            )
            self.audit_service.record(
                trace_id=command["trace_id"],
                event_type="alert.event.v1",
                reason="water change timed out; degraded to aerate_up",
                payload={"command_id": command_id},
                mode=command["mode"],
                site_id=command["site_id"],
                workshop_id=command["workshop_id"],
                pool_id=command["pool_id"],
            )
            self._publish_alert(command, "water change timed out; degraded to aerate_up", {"command_id": command_id})
            self._dispatch(command_id, reason="degraded water change dispatched as aerate_up")
            return

        if command["action_type"] == "feed" and float(command["params"].get("ratio", 0)) > 0.6:
            degraded_params = dict(command["params"])
            degraded_params["ratio"] = 0.60
            self.repository.update_command(command_id, effective_params=degraded_params, result_code="ACCEPTED_ASYNC")
            self.audit_service.record(
                trace_id=command["trace_id"],
                event_type="alert.event.v1",
                reason="feed timed out; degraded to 60 percent",
                payload={"command_id": command_id},
                mode=command["mode"],
                site_id=command["site_id"],
                workshop_id=command["workshop_id"],
                pool_id=command["pool_id"],
            )
            self._publish_alert(command, "feed timed out; degraded to 60 percent", {"command_id": command_id})
            self._dispatch(command_id, reason="degraded feed dispatched")
            return

        self.repository.update_command(command_id, result_code="E_RISK_NOT_APPROVED")
        self.audit_service.record(
            trace_id=command["trace_id"],
            event_type="alert.event.v1",
            reason="high-risk action timed out and was not executed",
            payload={"command_id": command_id},
            mode=command["mode"],
            site_id=command["site_id"],
            workshop_id=command["workshop_id"],
            pool_id=command["pool_id"],
        )
        self._publish_alert(command, "high-risk action timed out and was not executed", {"command_id": command_id})
        self._transition(command_id, "Degraded", "Closed", "timed out high-risk command was not executed")

    def _dispatch(self, command_id: str, reason: str) -> None:
        command = self.repository.get_command_by_id(command_id)
        assert command is not None
        current_status = command["status"]
        self._transition(command_id, current_status, "Dispatched", reason)

        command = self.repository.get_command_by_id(command_id)
        assert command is not None
        if self.mqtt_bridge:
            self.mqtt_bridge.publish_command_request(command, reason)

        self._transition(command_id, "Dispatched", "Executing", "execution adapter started")

        command = self.repository.get_command_by_id(command_id)
        assert command is not None
        receipt = self.execution_service.execute(command)
        result_code = receipt.get("result_code", "OK")
        self.repository.update_command(command_id, receipt=receipt, result_code=result_code, updated_at=datetime.now(UTC).isoformat())

        if result_code != "OK" or receipt.get("status") == "failed":
            self._transition(command_id, "Executing", "Failed", "execution adapter reported failure")
            self._transition(command_id, "Failed", "Closed", "command closed after execution failure")
            failed_command = self.repository.get_command_by_id(command_id)
            assert failed_command is not None
            if self.mqtt_bridge:
                self.mqtt_bridge.publish_command_result(failed_command, "command execution failed")
            self.audit_service.record(
                trace_id=failed_command["trace_id"],
                event_type="command.result.v1",
                reason="command execution failed",
                receipt=receipt,
                payload={"command_id": command_id},
                mode=failed_command["mode"],
                site_id=failed_command["site_id"],
                workshop_id=failed_command["workshop_id"],
                pool_id=failed_command["pool_id"],
            )
            self._publish_alert(failed_command, "command execution failed", {"command_id": command_id, "result_code": result_code})
            return

        self._transition(command_id, "Executing", "Executed", "execution adapter completed")
        verification = self.verification_service.verify(command, receipt)
        self.repository.insert_verification(command_id, "Verified", verification)
        self._transition(command_id, "Executed", "Verified", "verification recorded")
        self._transition(command_id, "Verified", "Closed", "command lifecycle complete")
        closed_command = self.repository.get_command_by_id(command_id)
        assert closed_command is not None
        if self.mqtt_bridge:
            self.mqtt_bridge.publish_command_result(closed_command, "command execution completed")
        self.audit_service.record(
            trace_id=closed_command["trace_id"],
            event_type="command.result.v1",
            reason="command execution completed",
            receipt=receipt,
            payload={"command_id": command_id},
            mode=closed_command["mode"],
            site_id=closed_command["site_id"],
            workshop_id=closed_command["workshop_id"],
            pool_id=closed_command["pool_id"],
        )

    def _publish_alert(self, command: dict[str, Any], reason: str, payload: dict[str, Any]) -> None:
        if not self.mqtt_bridge:
            return
        self.mqtt_bridge.publish_alert(
            mode=command["mode"],
            site_id=command["site_id"],
            workshop_id=command["workshop_id"],
            pool_id=command["pool_id"],
            reason=reason,
            payload=payload,
        )

    def get_command(self, command_id: str) -> CommandView:
        command = self.repository.get_command_by_id(command_id)
        if not command:
            raise KeyError(command_id)
        return self._to_view(command)

    def get_command_timeline(self, command_id: str) -> CommandTimelineView:
        command = self.repository.get_command_by_id(command_id)
        if not command:
            raise KeyError(command_id)
        return CommandTimelineView(
            command_id=command_id,
            transitions=[TransitionRecord(**record) for record in self.repository.list_transition_records(command_id)],
        )

    def _to_view(self, command: dict[str, Any]) -> CommandView:
        return CommandView(
            command_id=command["command_id"],
            trace_id=command["trace_id"],
            pool_id=command["pool_id"],
            mode=command["mode"],
            action_type=command["action_type"],
            effective_action_type=command["effective_action_type"],
            params=command["params"],
            effective_params=command["effective_params"],
            risk_level=command["risk_level"],
            status=command["status"],
            result_code=command["result_code"],
            approval_id=command.get("approval_id"),
            receipt=command.get("receipt"),
            transition_path=self.repository.list_transitions(command["command_id"]),
            updated_at=command["updated_at"],
        )
