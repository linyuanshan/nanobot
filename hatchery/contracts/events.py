"""Event envelopes and MQTT topic helpers."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any
from uuid import uuid4

from pydantic import BaseModel, Field

from hatchery.contracts.api import Mode


def utc_now() -> datetime:
    return datetime.now(UTC)


class Envelope(BaseModel):
    event_id: str = Field(default_factory=lambda: str(uuid4()))
    trace_id: str = Field(default_factory=lambda: str(uuid4()))
    event_type: str
    schema_version: str = "v1"
    mode: Mode
    ts: datetime = Field(default_factory=utc_now)
    site_id: str
    workshop_id: str
    pool_id: str
    source: str = "hatchery-service"
    payload: dict[str, Any]


class TopicBuilder:
    @staticmethod
    def telemetry(site_id: str, pool_id: str, *, prefix: str = "hatchery") -> str:
        return f"{prefix}/{site_id}/{pool_id}/telemetry"

    @staticmethod
    def perception(site_id: str, pool_id: str, *, prefix: str = "hatchery") -> str:
        return f"{prefix}/{site_id}/{pool_id}/perception"

    @staticmethod
    def command_request(site_id: str, pool_id: str, *, prefix: str = "hatchery") -> str:
        return f"{prefix}/{site_id}/{pool_id}/command/request"

    @staticmethod
    def command_result(site_id: str, pool_id: str, *, prefix: str = "hatchery") -> str:
        return f"{prefix}/{site_id}/{pool_id}/command/result"

    @staticmethod
    def alert(site_id: str, pool_id: str, *, prefix: str = "hatchery") -> str:
        return f"{prefix}/{site_id}/{pool_id}/alert"

    @staticmethod
    def audit(site_id: str, pool_id: str, *, prefix: str = "hatchery") -> str:
        return f"{prefix}/{site_id}/{pool_id}/audit"
