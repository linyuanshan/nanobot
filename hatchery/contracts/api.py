"""Public API models for the hatchery phase-1 service."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, Field

Mode = Literal["sim", "shadow", "real"]
AssessmentLevel = Literal["normal", "warn", "danger"]
RiskLevel = Literal["low", "medium", "high", "critical"]
OpsActionType = Literal["manual_override_on", "manual_override_off", "emergency_stop"]


class TelemetryWaterQualityIngestRequest(BaseModel):
    site_id: str
    workshop_id: str
    pool_id: str
    mode: Mode
    ts: datetime
    payload: dict[str, Any]


class BioPerceptionIngestRequest(BaseModel):
    site_id: str
    workshop_id: str
    pool_id: str
    mode: Mode
    ts: datetime
    payload: dict[str, Any]


class CommandTarget(BaseModel):
    site_id: str
    workshop_id: str
    pool_id: str


CommandTargetRef = CommandTarget


class CommandRequest(BaseModel):
    command_id: str
    idempotency_key: str
    trace_id: str
    mode: Mode
    action_type: str
    target: CommandTarget
    params: dict[str, Any]
    preconditions: dict[str, Any] = Field(default_factory=dict)
    deadline_sec: int = 180
    degrade_policy: str = ""
    dry_run: bool = False


class ApprovalRequest(BaseModel):
    command_id: str
    timeout_sec: int = 180
    remind_at_sec: int = 120
    provider: str = "local"


class ApprovalDecisionRequest(BaseModel):
    operator: str
    reason: str | None = None


class ActionPlanRequest(BaseModel):
    pool_id: str
    trace_id: str | None = None
    model_version: str = "policy-v1"


class ActionProposal(BaseModel):
    action_type: str
    params: dict[str, Any]
    risk_level: RiskLevel
    rationale: str


class ActionPlanResponse(BaseModel):
    plan_id: str
    trace_id: str
    pool_id: str
    risk_level: RiskLevel
    decision_explanation: str
    actions: list[ActionProposal]
    model_version: str
    created_at: datetime


class AssessmentView(BaseModel):
    level: AssessmentLevel
    reasons: list[str]


class PoolStateView(BaseModel):
    pool_id: str
    site_id: str
    workshop_id: str
    mode: Mode
    telemetry: dict[str, Any]
    bio: dict[str, Any]
    assessment: AssessmentView
    updated_at: datetime


class CommandView(BaseModel):
    command_id: str
    trace_id: str
    pool_id: str
    mode: Mode
    action_type: str
    effective_action_type: str
    params: dict[str, Any]
    effective_params: dict[str, Any]
    risk_level: RiskLevel
    status: str
    result_code: str
    approval_id: str | None = None
    receipt: dict[str, Any] | None = None
    transition_path: list[str] = Field(default_factory=list)
    updated_at: datetime


class TransitionRecord(BaseModel):
    from_status: str | None = None
    to_status: str
    reason: str
    created_at: datetime


class CommandTimelineView(BaseModel):
    command_id: str
    transitions: list[TransitionRecord]


class OpsControlCommandRequest(BaseModel):
    mode: Mode
    action_type: OpsActionType
    operator: str
    reason: str
    target: CommandTarget
    params: dict[str, Any] = Field(default_factory=dict)
    dry_run: bool = False


class DueApprovalResult(BaseModel):
    reminded: int = 0
    timed_out: int = 0


class AuditRecord(BaseModel):
    trace_id: str
    event_type: str
    reason: str
    operator: str
    model_version: str
    receipt: dict[str, Any] = Field(default_factory=dict)
    payload: dict[str, Any] = Field(default_factory=dict)
    mode: Mode | None = None
    site_id: str | None = None
    workshop_id: str | None = None
    pool_id: str | None = None
    created_at: datetime
