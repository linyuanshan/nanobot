"""Audit recording service."""

from __future__ import annotations

from hatchery.contracts.api import AuditRecord
from hatchery.db import HatcheryRepository


class AuditService:
    def __init__(self, repository: HatcheryRepository):
        self.repository = repository
        self.mqtt_bridge = None

    def set_mqtt_bridge(self, mqtt_bridge: object) -> None:
        self.mqtt_bridge = mqtt_bridge

    def record(
        self,
        *,
        trace_id: str,
        event_type: str,
        reason: str,
        operator: str = "system",
        model_version: str = "phase1-v1",
        receipt: dict | None = None,
        payload: dict | None = None,
        mode: str | None = None,
        site_id: str | None = None,
        workshop_id: str | None = None,
        pool_id: str | None = None,
    ) -> AuditRecord:
        record = {
            "trace_id": trace_id,
            "event_type": event_type,
            "reason": reason,
            "operator": operator,
            "model_version": model_version,
            "receipt": receipt or {},
            "payload": payload or {},
            "mode": mode,
            "site_id": site_id,
            "workshop_id": workshop_id,
            "pool_id": pool_id,
        }
        created_at = self.repository.insert_audit(**record)
        audit_record = AuditRecord(**record, created_at=created_at)
        if self.mqtt_bridge and all(value is not None for value in (mode, site_id, workshop_id, pool_id)):
            self.mqtt_bridge.publish_audit(
                mode=mode,
                site_id=site_id,
                workshop_id=workshop_id,
                pool_id=pool_id,
                record=audit_record.model_dump(mode="json"),
            )
        return audit_record

    def list_records(
        self,
        trace_id: str | None = None,
        pool_id: str | None = None,
        event_type: str | None = None,
        from_ts: str | None = None,
        to_ts: str | None = None,
    ) -> list[AuditRecord]:
        return [
            AuditRecord(**record)
            for record in self.repository.list_audits(
                trace_id=trace_id,
                pool_id=pool_id,
                event_type=event_type,
                from_ts=from_ts,
                to_ts=to_ts,
            )
        ]
