"""FastAPI application for the hatchery phase-1 service."""

from __future__ import annotations

import json
import threading
from contextlib import asynccontextmanager
from datetime import UTC, datetime
from typing import Any

from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse, JSONResponse, PlainTextResponse, RedirectResponse

from hatchery.app.gui import render_acceptance_console
from hatchery.container import ServiceContainer, build_container
from hatchery.contracts.api import (
    ActionPlanRequest,
    ApprovalDecisionRequest,
    ApprovalRequest,
    BioPerceptionIngestRequest,
    CommandRequest,
    OpsControlCommandRequest,
    TelemetryWaterQualityIngestRequest,
)
from hatchery.security import authorize_request
from hatchery.settings import HatcherySettings


class ApprovalScheduler:
    def __init__(self, container: ServiceContainer, interval_sec: float):
        self.container = container
        self.interval_sec = interval_sec
        self.running = False
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

    def start(self) -> None:
        if self.running:
            return
        self._stop.clear()
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()
        self.running = True

    def stop(self) -> None:
        if not self.running:
            return
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout=5)
        self.running = False

    def _run(self) -> None:
        while not self._stop.is_set():
            self.container.command_service.process_due_approvals(datetime.now(UTC))
            self._stop.wait(self.interval_sec)


def create_app(settings: HatcherySettings | None = None) -> FastAPI:
    settings = settings or HatcherySettings.from_env()
    container = build_container(settings)
    scheduler = ApprovalScheduler(container, settings.scheduler_interval_sec)

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        container.start()
        if settings.enable_scheduler:
            scheduler.start()
        try:
            yield
        finally:
            if settings.enable_scheduler:
                scheduler.stop()
            container.stop()

    app = FastAPI(title="Hatchery Phase-1 Service", lifespan=lifespan)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_methods=["*"],
        allow_headers=["*"],
    )
    app.state.container = container
    app.state.settings = settings
    app.state.scheduler = scheduler

    def require(request: Request, minimum_role: str, *, require_actor: bool = False):
        return authorize_request(
            request,
            enabled=settings.auth_enabled,
            tokens=settings.auth_tokens,
            minimum_role=minimum_role,
            require_actor=require_actor,
        )

    @app.get("/", include_in_schema=False)
    def root() -> RedirectResponse:
        return RedirectResponse(url="/gui", status_code=307)

    @app.get("/gui", response_class=HTMLResponse, include_in_schema=False)
    def acceptance_gui() -> HTMLResponse:
        return HTMLResponse(content=render_acceptance_console())

    @app.get("/healthz")
    def healthz() -> dict[str, Any]:
        real_adapter = container.execution_service.real_adapter.status()
        return {
            "status": "ok",
            "service": settings.service_name,
            "checks": {
                "scheduler": "running" if scheduler.running else "disabled" if not settings.enable_scheduler else "stopped",
                "mqtt": container.mqtt_bridge.status(),
                "real_adapter": real_adapter["state"],
            },
            "mqtt": container.mqtt_bridge.metrics(),
            "real_adapter": real_adapter,
        }

    @app.get("/readyz")
    def readyz() -> JSONResponse:
        checks = container.readiness_checks()
        ready = all(value in {"ok", "disabled"} for value in checks.values())
        payload = {
            "status": "ready" if ready else "not_ready",
            "service": settings.service_name,
            "checks": checks,
        }
        return JSONResponse(status_code=200 if ready else 503, content=payload)

    @app.post("/api/v1/telemetry/water-quality")
    def ingest_water_quality(request: TelemetryWaterQualityIngestRequest, http_request: Request) -> JSONResponse:
        require(http_request, "operator")
        envelope = container.ingest_service.ingest_water_quality(request)
        return JSONResponse(status_code=202, content=envelope.model_dump(mode="json"))

    @app.post("/api/v1/perception/bio")
    def ingest_bio(request: BioPerceptionIngestRequest, http_request: Request) -> JSONResponse:
        require(http_request, "operator")
        envelope = container.ingest_service.ingest_bio_perception(request)
        return JSONResponse(status_code=202, content=envelope.model_dump(mode="json"))

    @app.get("/api/v1/pools/{pool_id}/state")
    def query_pool_state(pool_id: str, http_request: Request) -> dict[str, Any]:
        require(http_request, "viewer")
        state = container.ingest_service.get_pool_state(pool_id)
        if not state:
            raise HTTPException(status_code=404, detail="pool not found")
        return state.model_dump(mode="json")

    @app.post("/api/v1/decisions/plan")
    def create_action_plan(request: ActionPlanRequest, http_request: Request) -> dict[str, Any]:
        require(http_request, "viewer")
        return container.policy_service.create_action_plan(request).model_dump(mode="json")

    @app.post("/api/v1/approvals/requests")
    def create_approval(request: ApprovalRequest, http_request: Request) -> dict[str, Any]:
        require(http_request, "operator", require_actor=True)
        command = container.command_service.get_command(request.command_id)
        if command.approval_id:
            return {
                "approval_id": command.approval_id,
                "command_id": request.command_id,
                "status": "PendingApproval" if command.status == "PendingApproval" else command.status,
            }
        raise HTTPException(status_code=409, detail="command does not require approval")

    @app.post("/api/v1/approvals/{approval_id}/confirm")
    def confirm_approval(approval_id: str, request: ApprovalDecisionRequest, http_request: Request) -> dict[str, Any]:
        auth = require(http_request, "operator", require_actor=True)
        try:
            command = container.command_service.confirm_approval(approval_id, auth.actor, request.reason)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail="approval not found") from exc
        return command.model_dump(mode="json")

    @app.post("/api/v1/approvals/{approval_id}/reject")
    def reject_approval(approval_id: str, request: ApprovalDecisionRequest, http_request: Request) -> dict[str, Any]:
        auth = require(http_request, "operator", require_actor=True)
        try:
            command = container.command_service.reject_approval(approval_id, auth.actor, request.reason)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail="approval not found") from exc
        return command.model_dump(mode="json")

    @app.post("/api/v1/commands")
    def submit_command(request: CommandRequest, http_request: Request) -> JSONResponse:
        auth = require(http_request, "operator", require_actor=True)
        if request.mode == "real" and auth.role != "admin":
            raise HTTPException(status_code=403, detail="real mode requires admin role")
        command = container.command_service.submit_command(request)
        if command.result_code == "E_DUPLICATE_IDEMPOTENCY":
            return JSONResponse(status_code=409, content=command.model_dump(mode="json"))
        if command.status == "PendingApproval":
            return JSONResponse(status_code=202, content=command.model_dump(mode="json"))
        return JSONResponse(status_code=200, content=command.model_dump(mode="json"))

    @app.get("/api/v1/commands/{command_id}")
    def query_command(command_id: str, http_request: Request) -> dict[str, Any]:
        require(http_request, "viewer")
        try:
            command = container.command_service.get_command(command_id)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail="command not found") from exc
        return command.model_dump(mode="json")

    @app.get("/api/v1/audits")
    def query_audits(
        http_request: Request,
        trace_id: str | None = Query(default=None),
        pool_id: str | None = Query(default=None),
        event_type: str | None = Query(default=None),
        from_ts: str | None = Query(default=None),
        to_ts: str | None = Query(default=None),
    ) -> list[dict[str, Any]]:
        require(http_request, "viewer")
        return [
            record.model_dump(mode="json")
            for record in container.audit_service.list_records(
                trace_id=trace_id,
                pool_id=pool_id,
                event_type=event_type,
                from_ts=from_ts,
                to_ts=to_ts,
            )
        ]

    @app.get("/api/v1/audits/export")
    def export_audits(
        http_request: Request,
        trace_id: str | None = Query(default=None),
        pool_id: str | None = Query(default=None),
        event_type: str | None = Query(default=None),
        from_ts: str | None = Query(default=None),
        to_ts: str | None = Query(default=None),
    ) -> PlainTextResponse:
        require(http_request, "operator")
        records = [
            record.model_dump(mode="json")
            for record in container.audit_service.list_records(
                trace_id=trace_id,
                pool_id=pool_id,
                event_type=event_type,
                from_ts=from_ts,
                to_ts=to_ts,
            )
        ]
        payload = "\n".join(json.dumps(record, ensure_ascii=True, sort_keys=True) for record in records)
        return PlainTextResponse(content=payload, media_type="application/x-ndjson")

    @app.get("/api/v1/ops/commands/{command_id}/timeline")
    def query_command_timeline(command_id: str, http_request: Request) -> dict[str, Any]:
        require(http_request, "viewer")
        try:
            timeline = container.command_service.get_command_timeline(command_id)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail="command not found") from exc
        return timeline.model_dump(mode="json")

    @app.get("/api/v1/ops/summary")
    def query_ops_summary(http_request: Request) -> dict[str, Any]:
        require(http_request, "viewer")
        return {
            "commands": {
                "total": container.repository.count_commands_total(),
                "by_status": container.repository.count_commands_by_status(),
            },
            "approvals": {
                "by_status": container.repository.count_approvals_by_status(),
            },
            "mqtt": container.mqtt_bridge.metrics(),
        }

    @app.post("/api/v1/ops/control-commands")
    def submit_control_command(request: OpsControlCommandRequest, http_request: Request) -> JSONResponse:
        auth = require(http_request, "admin", require_actor=True)
        command = container.command_service.submit_operational_control(request, actor=auth.actor)
        return JSONResponse(status_code=200, content=command.model_dump(mode="json"))

    return app


__all__ = ["HatcherySettings", "create_app"]
