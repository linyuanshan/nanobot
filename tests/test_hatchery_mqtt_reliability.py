from pathlib import Path

from hatchery.adapters.mqtt import InMemoryMqttRuntime
from hatchery.container import build_container
from hatchery.contracts.api import TelemetryWaterQualityIngestRequest
from hatchery.settings import HatcherySettings


class FlakyRuntime(InMemoryMqttRuntime):
    def __init__(self):
        super().__init__()
        self.publish_attempts = 0

    def publish(self, topic: str, payload: dict, qos: int = 1, retain: bool = False) -> None:
        self.publish_attempts += 1
        if self.publish_attempts == 1:
            self.connected = False
            raise RuntimeError("transient broker outage")
        self.connected = True
        super().publish(topic, payload, qos=qos, retain=retain)


def test_duplicate_inbound_mqtt_event_is_ignored(tmp_path: Path) -> None:
    runtime = InMemoryMqttRuntime()
    container = build_container(
        HatcherySettings(database_path=tmp_path / "hatchery.db", enable_scheduler=False, mqtt_enabled=True),
        mqtt_runtime=runtime,
    )
    container.start()
    try:
        envelope = {
            "event_id": "evt-dup-001",
            "trace_id": "trace-dup-001",
            "event_type": "telemetry.water_quality.v1",
            "schema_version": "v1",
            "mode": "shadow",
            "ts": "2026-02-07T10:05:00Z",
            "site_id": "site-edge",
            "workshop_id": "ws-edge",
            "pool_id": "pool-08",
            "source": "edge-sensor-gateway",
            "payload": {
                "do_mg_l": 5.8,
                "ph": 7.6,
                "temp_c": 23.9,
                "relay_state": 0,
                "sensor_health": "online",
                "raw": {"rjy": 5.8, "temp": 23.9},
            },
        }
        runtime.inject_message("hatchery/site-edge/pool-08/telemetry", envelope)
        runtime.inject_message("hatchery/site-edge/pool-08/telemetry", envelope)
    finally:
        container.stop()

    row_count = container.repository._conn.execute("SELECT COUNT(*) FROM telemetry_events").fetchone()[0]
    assert row_count == 1


def test_mqtt_publish_retries_once_after_transient_failure(tmp_path: Path) -> None:
    runtime = FlakyRuntime()
    container = build_container(
        HatcherySettings(database_path=tmp_path / "hatchery.db", enable_scheduler=False, mqtt_enabled=True),
        mqtt_runtime=runtime,
    )
    container.start()
    try:
        container.ingest_service.ingest_water_quality(
            TelemetryWaterQualityIngestRequest(
                site_id="site-001",
                workshop_id="ws-001",
                pool_id="pool-01",
                mode="sim",
                ts="2026-02-07T10:00:00Z",
                payload={
                    "relay": 0,
                    "ph": 7.4,
                    "hzd": 3,
                    "rjy": 5.9,
                    "temp": 24.5,
                },
            )
        )
    finally:
        container.stop()

    assert runtime.publish_attempts == 2
    assert runtime.published[0]["topic"] == "hatchery/site-001/pool-01/telemetry"
