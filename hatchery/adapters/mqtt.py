"""MQTT runtime and bridge for hatchery event flow."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from typing import Any, Callable

import paho.mqtt.client as mqtt

from hatchery.contracts.events import Envelope, TopicBuilder

MessageHandler = Callable[[str, dict[str, Any]], None]


class RecordingPublisher:
    def __init__(self):
        self.published: list[dict[str, Any]] = []

    def publish(self, topic: str, payload: dict[str, Any], qos: int = 1, retain: bool = False) -> None:
        self.published.append({"topic": topic, "payload": payload, "qos": qos, "retain": retain})


class InMemoryMqttRuntime(RecordingPublisher):
    def __init__(self):
        super().__init__()
        self.started = False
        self.connected = False
        self.last_error: str | None = None
        self.subscriptions: list[str] = []
        self._handler: MessageHandler | None = None

    def start(self, subscriptions: list[str], on_message: MessageHandler) -> None:
        self.subscriptions = list(subscriptions)
        self._handler = on_message
        self.started = True
        self.connected = True
        self.last_error = None

    def stop(self) -> None:
        self.started = False
        self.connected = False

    def inject_message(self, topic: str, payload: dict[str, Any]) -> None:
        if self._handler is None:
            return
        if any(mqtt.topic_matches_sub(subscription, topic) for subscription in self.subscriptions):
            self._handler(topic, payload)


class MqttRuntime:
    def __init__(self, host: str = "127.0.0.1", port: int = 1883, client_id: str = "hatchery-phase1", keepalive_sec: int = 30):
        self.host = host
        self.port = port
        self.keepalive_sec = keepalive_sec
        client_kwargs = {"client_id": client_id}
        if hasattr(mqtt, "CallbackAPIVersion"):
            client_kwargs["callback_api_version"] = mqtt.CallbackAPIVersion.VERSION2
        self.client = mqtt.Client(**client_kwargs)
        self.started = False
        self.connected = False
        self.last_error: str | None = None
        self.subscriptions: list[str] = []
        self.published: list[dict[str, Any]] = []
        self._handler: MessageHandler | None = None

    def start(self, subscriptions: list[str], on_message: MessageHandler) -> None:
        self.subscriptions = list(subscriptions)
        self._handler = on_message
        self.client.on_connect = self._on_connect
        self.client.on_disconnect = self._on_disconnect
        self.client.on_message = self._on_message
        try:
            self.client.connect(self.host, self.port, self.keepalive_sec)
            self.client.loop_start()
            self.started = True
            self.connected = True
            self.last_error = None
        except Exception as exc:  # pragma: no cover - depends on local broker
            self.started = True
            self.connected = False
            self.last_error = str(exc)

    def stop(self) -> None:
        if self.started:
            try:
                self.client.loop_stop()
                self.client.disconnect()
            except Exception:  # pragma: no cover - best effort shutdown
                pass
        self.started = False
        self.connected = False

    def publish(self, topic: str, payload: dict[str, Any], qos: int = 1, retain: bool = False) -> None:
        self.published.append({"topic": topic, "payload": payload, "qos": qos, "retain": retain})
        self.client.publish(topic, json.dumps(payload, ensure_ascii=True), qos=qos, retain=retain)

    def _on_connect(self, client: mqtt.Client, userdata: Any, flags: Any, rc: int, properties: Any = None) -> None:
        self.connected = rc == 0
        if rc != 0:
            self.last_error = f"mqtt connect failed: {rc}"
            return
        for subscription in self.subscriptions:
            client.subscribe(subscription)

    def _on_disconnect(self, client: mqtt.Client, userdata: Any, flags: Any, rc: int, properties: Any = None) -> None:
        self.connected = False
        if rc != 0:
            self.last_error = f"mqtt disconnected: {rc}"

    def _on_message(self, client: mqtt.Client, userdata: Any, message: mqtt.MQTTMessage) -> None:
        if self._handler is None:
            return
        try:
            payload = json.loads(message.payload.decode("utf-8"))
        except Exception as exc:  # pragma: no cover - invalid external payloads
            self.last_error = f"mqtt payload decode failed: {exc}"
            return
        self._handler(message.topic, payload)


class MqttBridgeService:
    def __init__(self, *, settings: "HatcherySettings", runtime: InMemoryMqttRuntime | MqttRuntime, ingest_service: "IngestService"):
        self.settings = settings
        self.runtime = runtime
        self.ingest_service = ingest_service
        self.received_messages = 0
        self.duplicate_messages = 0
        self.publish_failures = 0
        self.publish_retries = 0

    def start(self) -> None:
        if not self.settings.mqtt_enabled:
            return
        self.runtime.start(
            subscriptions=[
                f"{self.settings.mqtt_topic_prefix}/+/+/telemetry",
                f"{self.settings.mqtt_topic_prefix}/+/+/perception",
            ],
            on_message=self.handle_message,
        )

    def stop(self) -> None:
        if not self.settings.mqtt_enabled:
            return
        self.runtime.stop()

    def status(self) -> str:
        if not self.settings.mqtt_enabled:
            return "disabled"
        if self.runtime.connected:
            return "ok"
        if self.runtime.last_error:
            return "error"
        return "starting" if self.runtime.started else "stopped"

    def metrics(self) -> dict[str, Any]:
        return {
            "status": self.status(),
            "last_error": self.runtime.last_error,
            "received_messages": self.received_messages,
            "duplicate_messages": self.duplicate_messages,
            "publish_failures": self.publish_failures,
            "publish_retries": self.publish_retries,
        }

    def publish_telemetry(self, envelope: Envelope) -> None:
        self._publish(TopicBuilder.telemetry(envelope.site_id, envelope.pool_id, prefix=self.settings.mqtt_topic_prefix), envelope)

    def publish_perception(self, envelope: Envelope) -> None:
        self._publish(TopicBuilder.perception(envelope.site_id, envelope.pool_id, prefix=self.settings.mqtt_topic_prefix), envelope)

    def publish_command_request(self, command: dict[str, Any], reason: str) -> None:
        envelope = self._event_envelope(
            event_type="command.request.v1",
            mode=command["mode"],
            site_id=command["site_id"],
            workshop_id=command["workshop_id"],
            pool_id=command["pool_id"],
            payload={
                "command_id": command["command_id"],
                "trace_id": command["trace_id"],
                "action_type": command["action_type"],
                "effective_action_type": command["effective_action_type"],
                "params": command["effective_params"],
                "risk_level": command["risk_level"],
                "status": command["status"],
                "reason": reason,
            },
        )
        self._publish(TopicBuilder.command_request(command["site_id"], command["pool_id"], prefix=self.settings.mqtt_topic_prefix), envelope)

    def publish_command_result(self, command: dict[str, Any], reason: str) -> None:
        envelope = self._event_envelope(
            event_type="command.result.v1",
            mode=command["mode"],
            site_id=command["site_id"],
            workshop_id=command["workshop_id"],
            pool_id=command["pool_id"],
            payload={
                "command_id": command["command_id"],
                "trace_id": command["trace_id"],
                "action_type": command["action_type"],
                "effective_action_type": command["effective_action_type"],
                "result_code": command["result_code"],
                "status": command["status"],
                "receipt": command.get("receipt") or {},
                "reason": reason,
            },
        )
        self._publish(TopicBuilder.command_result(command["site_id"], command["pool_id"], prefix=self.settings.mqtt_topic_prefix), envelope)

    def publish_alert(self, *, mode: str, site_id: str, workshop_id: str, pool_id: str, reason: str, payload: dict[str, Any]) -> None:
        envelope = self._event_envelope(
            event_type="alert.event.v1",
            mode=mode,
            site_id=site_id,
            workshop_id=workshop_id,
            pool_id=pool_id,
            payload={**payload, "reason": reason},
        )
        self._publish(TopicBuilder.alert(site_id, pool_id, prefix=self.settings.mqtt_topic_prefix), envelope)

    def publish_audit(self, *, mode: str, site_id: str, workshop_id: str, pool_id: str, record: dict[str, Any]) -> None:
        envelope = self._event_envelope(
            event_type=record["event_type"],
            mode=mode,
            site_id=site_id,
            workshop_id=workshop_id,
            pool_id=pool_id,
            payload=record,
        )
        self._publish(TopicBuilder.audit(site_id, pool_id, prefix=self.settings.mqtt_topic_prefix), envelope)

    def handle_message(self, topic: str, payload: dict[str, Any]) -> None:
        self.received_messages += 1
        envelope = Envelope.model_validate(payload)
        if envelope.source == self.settings.service_name:
            return
        inserted = False
        if mqtt.topic_matches_sub(f"{self.settings.mqtt_topic_prefix}/+/+/telemetry", topic):
            inserted = self.ingest_service.ingest_water_quality_envelope(envelope)
        elif mqtt.topic_matches_sub(f"{self.settings.mqtt_topic_prefix}/+/+/perception", topic):
            inserted = self.ingest_service.ingest_bio_envelope(envelope)
        if not inserted:
            self.duplicate_messages += 1

    def _event_envelope(self, *, event_type: str, mode: str, site_id: str, workshop_id: str, pool_id: str, payload: dict[str, Any]) -> Envelope:
        return Envelope(
            event_type=event_type,
            mode=mode,
            ts=datetime.now(UTC),
            site_id=site_id,
            workshop_id=workshop_id,
            pool_id=pool_id,
            source=self.settings.service_name,
            payload=payload,
        )

    def _publish(self, topic: str, envelope: Envelope) -> None:
        if not self.settings.mqtt_enabled:
            return
        payload = envelope.model_dump(mode="json")
        for attempt in range(2):
            try:
                self.runtime.publish(topic, payload, qos=self.settings.mqtt_qos, retain=self.settings.mqtt_retain)
                self.runtime.connected = True
                return
            except Exception as exc:
                self.runtime.connected = False
                self.runtime.last_error = str(exc)
                if attempt == 0:
                    self.publish_retries += 1
                    try:
                        self.runtime.start(self.runtime.subscriptions, self.handle_message)
                    except Exception as reconnect_exc:  # pragma: no cover - depends on external broker
                        self.runtime.last_error = str(reconnect_exc)
                    continue
                self.publish_failures += 1
