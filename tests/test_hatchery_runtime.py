from pathlib import Path

from fastapi.testclient import TestClient

from hatchery.adapters.mqtt import InMemoryMqttRuntime
from hatchery.app import create_app
from hatchery.container import build_container
from hatchery.contracts.api import CommandRequest, TelemetryWaterQualityIngestRequest
from hatchery.settings import HatcherySettings


def test_settings_from_env_reads_runtime_configuration(monkeypatch, tmp_path: Path) -> None:
    database_path = tmp_path / "edge-hatchery.db"
    monkeypatch.setenv("HATCHERY_DATABASE_PATH", str(database_path))
    monkeypatch.setenv("HATCHERY_ENABLE_SCHEDULER", "false")
    monkeypatch.setenv("HATCHERY_MQTT_ENABLED", "true")
    monkeypatch.setenv("HATCHERY_MQTT_HOST", "broker.internal")
    monkeypatch.setenv("HATCHERY_MQTT_PORT", "2883")
    monkeypatch.setenv("HATCHERY_SERVICE_NAME", "edge-hatchery")

    settings = HatcherySettings.from_env()

    assert settings.database_path == database_path
    assert settings.enable_scheduler is False
    assert settings.mqtt_enabled is True
    assert settings.mqtt_host == "broker.internal"
    assert settings.mqtt_port == 2883
    assert settings.service_name == "edge-hatchery"


def test_healthz_and_readyz_report_database_and_mqtt_state(tmp_path: Path) -> None:
    app = create_app(HatcherySettings(database_path=tmp_path / "hatchery.db", enable_scheduler=False))
    client = TestClient(app)

    health = client.get("/healthz")
    assert health.status_code == 200
    assert health.json()["status"] == "ok"
    assert health.json()["checks"]["scheduler"] == "disabled"

    ready = client.get("/readyz")
    assert ready.status_code == 200
    assert ready.json()["status"] == "ready"
    assert ready.json()["checks"]["database"] == "ok"
    assert ready.json()["checks"]["mqtt"] == "disabled"


def test_mqtt_bridge_publishes_normalized_telemetry_and_command_events(tmp_path: Path) -> None:
    runtime = InMemoryMqttRuntime()
    settings = HatcherySettings(
        database_path=tmp_path / "hatchery.db",
        enable_scheduler=False,
        mqtt_enabled=True,
    )
    container = build_container(settings, mqtt_runtime=runtime)
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
        container.command_service.submit_command(
            CommandRequest(
                command_id="cmd-mqtt-001",
                idempotency_key="pool-01-feed-202602071400",
                trace_id="trace-mqtt-001",
                mode="sim",
                action_type="feed",
                target={
                    "site_id": "site-001",
                    "workshop_id": "ws-001",
                    "pool_id": "pool-01",
                },
                params={
                    "ratio": 0.60,
                    "duration_sec": 120,
                },
                preconditions={
                    "min_do_mg_l": 5.0,
                    "max_temp_c": 29.0,
                },
                deadline_sec=180,
                degrade_policy="feed_60_percent_on_timeout",
                dry_run=True,
            )
        )
    finally:
        container.stop()

    topics = [message["topic"] for message in runtime.published]
    assert "hatchery/site-001/pool-01/telemetry" in topics
    assert "hatchery/site-001/pool-01/command/request" in topics
    assert "hatchery/site-001/pool-01/command/result" in topics


def test_mqtt_bridge_consumes_inbound_telemetry_messages(tmp_path: Path) -> None:
    runtime = InMemoryMqttRuntime()
    settings = HatcherySettings(
        database_path=tmp_path / "hatchery.db",
        enable_scheduler=False,
        mqtt_enabled=True,
    )
    container = build_container(settings, mqtt_runtime=runtime)
    container.start()
    try:
        runtime.inject_message(
            "hatchery/site-edge/pool-08/telemetry",
            {
                "event_id": "evt-edge-001",
                "trace_id": "trace-edge-001",
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
                    "raw": {
                        "rjy": 5.8,
                        "temp": 23.9,
                    },
                },
            },
        )
    finally:
        container.stop()

    state = container.ingest_service.get_pool_state("pool-08")
    assert state is not None
    assert state.mode == "shadow"
    assert state.telemetry["do_mg_l"] == 5.8
    assert state.assessment.level == "normal"
