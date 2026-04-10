"""Telemetry and perception ingestion."""

from __future__ import annotations

from hatchery.assessment import assess_pool_state
from hatchery.contracts.api import BioPerceptionIngestRequest, PoolStateView, TelemetryWaterQualityIngestRequest
from hatchery.contracts.events import Envelope, TopicBuilder
from hatchery.db import HatcheryRepository


class IngestService:
    def __init__(self, repository: HatcheryRepository, service_name: str = "hatchery-service"):
        self.repository = repository
        self.service_name = service_name
        self.mqtt_bridge = None

    def set_mqtt_bridge(self, mqtt_bridge: object) -> None:
        self.mqtt_bridge = mqtt_bridge

    def ingest_water_quality(self, request: TelemetryWaterQualityIngestRequest) -> Envelope:
        envelope = Envelope(
            event_type="telemetry.water_quality.v1",
            mode=request.mode,
            ts=request.ts,
            site_id=request.site_id,
            workshop_id=request.workshop_id,
            pool_id=request.pool_id,
            source=self.service_name,
            payload=self._normalize_water_quality_payload(request.payload),
        )
        inserted = self.ingest_water_quality_envelope(envelope)
        if inserted and self.mqtt_bridge:
            self.mqtt_bridge.publish_telemetry(envelope)
        return envelope

    def ingest_water_quality_envelope(self, envelope: Envelope) -> bool:
        inserted = self.repository.save_event(
            table="telemetry_events",
            event_id=envelope.event_id,
            trace_id=envelope.trace_id,
            pool_id=envelope.pool_id,
            event_type=envelope.event_type,
            payload=envelope.model_dump(mode="json"),
            ts=envelope.ts.isoformat(),
            topic=TopicBuilder.telemetry(envelope.site_id, envelope.pool_id),
        )
        if not inserted:
            return False
        payload = envelope.payload
        state = self.repository.get_pool_state(envelope.pool_id) or {
            "bio": {},
            "site_id": envelope.site_id,
            "workshop_id": envelope.workshop_id,
            "mode": envelope.mode,
        }
        level, reasons = assess_pool_state(payload)
        self.repository.upsert_pool_state(
            pool_id=envelope.pool_id,
            site_id=envelope.site_id,
            workshop_id=envelope.workshop_id,
            mode=envelope.mode,
            telemetry=payload,
            bio=state["bio"],
            assessment_level=level,
            assessment_reasons=reasons,
            updated_at=envelope.ts.isoformat(),
        )
        return True

    def ingest_bio_perception(self, request: BioPerceptionIngestRequest) -> Envelope:
        envelope = Envelope(
            event_type="perception.bio.v1",
            mode=request.mode,
            ts=request.ts,
            site_id=request.site_id,
            workshop_id=request.workshop_id,
            pool_id=request.pool_id,
            source=self.service_name,
            payload={
                "count": int(request.payload.get("count", 0)),
                "size_distribution": request.payload.get("size_distribution", []),
                "activity_score": float(request.payload.get("activity_score", 0.0)),
                "hunger_score": float(request.payload.get("hunger_score", 0.0)),
                "confidence": float(request.payload.get("confidence", 1.0)),
                "model_version": request.payload.get("model_version", "replay-v1"),
            },
        )
        inserted = self.ingest_bio_envelope(envelope)
        if inserted and self.mqtt_bridge:
            self.mqtt_bridge.publish_perception(envelope)
        return envelope

    def ingest_bio_envelope(self, envelope: Envelope) -> bool:
        inserted = self.repository.save_event(
            table="perception_events",
            event_id=envelope.event_id,
            trace_id=envelope.trace_id,
            pool_id=envelope.pool_id,
            event_type=envelope.event_type,
            payload=envelope.model_dump(mode="json"),
            ts=envelope.ts.isoformat(),
            topic=TopicBuilder.perception(envelope.site_id, envelope.pool_id),
        )
        if not inserted:
            return False
        state = self.repository.get_pool_state(envelope.pool_id) or {
            "telemetry": {},
            "site_id": envelope.site_id,
            "workshop_id": envelope.workshop_id,
            "mode": envelope.mode,
            "assessment_level": "normal",
            "assessment_reasons": ["bio event received before telemetry"],
        }
        self.repository.upsert_pool_state(
            pool_id=envelope.pool_id,
            site_id=envelope.site_id,
            workshop_id=envelope.workshop_id,
            mode=envelope.mode,
            telemetry=state["telemetry"],
            bio=envelope.payload,
            assessment_level=state["assessment_level"],
            assessment_reasons=state["assessment_reasons"],
            updated_at=envelope.ts.isoformat(),
        )
        return True

    def get_pool_state(self, pool_id: str) -> PoolStateView | None:
        state = self.repository.get_pool_state(pool_id)
        if not state:
            return None
        return PoolStateView(
            pool_id=state["pool_id"],
            site_id=state["site_id"],
            workshop_id=state["workshop_id"],
            mode=state["mode"],
            telemetry=state["telemetry"],
            bio=state["bio"],
            assessment={
                "level": state["assessment_level"],
                "reasons": state["assessment_reasons"],
            },
            updated_at=state["updated_at"],
        )

    def _normalize_water_quality_payload(self, payload: dict[str, object]) -> dict[str, object]:
        return {
            "do_mg_l": float(payload["rjy"]),
            "ph": float(payload["ph"]),
            "temp_c": float(payload["temp"]),
            "relay_state": int(payload.get("relay", 0)),
            "sensor_health": "online",
            "raw": {
                "rjy": payload["rjy"],
                "temp": payload["temp"],
            },
        }
