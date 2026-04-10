from __future__ import annotations

import argparse
import json
import queue
import sys
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from uuid import uuid4

import httpx
import paho.mqtt.client as mqtt


@dataclass(slots=True)
class SmokeConfig:
    service_url: str
    broker_host: str
    broker_port: int
    topic_prefix: str
    site_id: str
    workshop_id: str
    pool_id: str
    api_token: str
    actor: str
    timeout_sec: int

    def headers(self) -> dict[str, str]:
        headers: dict[str, str] = {}
        if self.api_token:
            headers["X-Hatchery-Token"] = self.api_token
        if self.actor:
            headers["X-Hatchery-Actor"] = self.actor
        return headers


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def wait_for_pool_state(client: httpx.Client, config: SmokeConfig, expected_do: float) -> dict:
    deadline = time.time() + config.timeout_sec
    while time.time() < deadline:
        response = client.get(
            f"{config.service_url}/api/v1/pools/{config.pool_id}/state",
            headers=config.headers(),
        )
        if response.status_code == 200:
            payload = response.json()
            if abs(float(payload["telemetry"].get("do_mg_l", -1)) - expected_do) < 0.0001:
                return payload
        time.sleep(1)
    raise TimeoutError("pool state did not reflect inbound MQTT telemetry")


def main() -> None:
    parser = argparse.ArgumentParser(description="Run a live MQTT smoke test against hatchery")
    parser.add_argument("--service-url", default="http://127.0.0.1:8090")
    parser.add_argument("--broker-host", default="127.0.0.1")
    parser.add_argument("--broker-port", type=int, default=1883)
    parser.add_argument("--topic-prefix", default="hatchery")
    parser.add_argument("--site-id", default="site-smoke")
    parser.add_argument("--workshop-id", default="ws-smoke")
    parser.add_argument("--pool-id", default="pool-smoke")
    parser.add_argument("--api-token", default="")
    parser.add_argument("--actor", default="mqtt-smoke")
    parser.add_argument("--timeout-sec", type=int, default=30)
    args = parser.parse_args()

    config = SmokeConfig(
        service_url=args.service_url.rstrip("/"),
        broker_host=args.broker_host,
        broker_port=args.broker_port,
        topic_prefix=args.topic_prefix,
        site_id=args.site_id,
        workshop_id=args.workshop_id,
        pool_id=args.pool_id,
        api_token=args.api_token,
        actor=args.actor,
        timeout_sec=args.timeout_sec,
    )

    inbound_topic = f"{config.topic_prefix}/{config.site_id}/{config.pool_id}/telemetry"
    request_topic = f"{config.topic_prefix}/{config.site_id}/{config.pool_id}/command/request"
    result_topic = f"{config.topic_prefix}/{config.site_id}/{config.pool_id}/command/result"
    events: queue.Queue[tuple[str, dict]] = queue.Queue()
    connected = queue.Queue()

    def on_connect(client: mqtt.Client, userdata, flags, rc, properties=None):  # pragma: no cover - callback
        if rc != 0:
            connected.put((False, rc))
            return
        client.subscribe(f"{config.topic_prefix}/{config.site_id}/{config.pool_id}/#")
        connected.put((True, rc))

    def on_message(client: mqtt.Client, userdata, message: mqtt.MQTTMessage):  # pragma: no cover - callback
        payload = json.loads(message.payload.decode("utf-8"))
        events.put((message.topic, payload))

    client_kwargs = {"client_id": f"hatchery-mqtt-smoke-{uuid4()}"}
    if hasattr(mqtt, "CallbackAPIVersion"):
        client_kwargs["callback_api_version"] = mqtt.CallbackAPIVersion.VERSION2
    subscriber = mqtt.Client(**client_kwargs)
    subscriber.on_connect = on_connect
    subscriber.on_message = on_message
    subscriber.connect(config.broker_host, config.broker_port, 30)
    subscriber.loop_start()

    ok, rc = connected.get(timeout=10)
    if not ok:
        raise RuntimeError(f"unable to connect to MQTT broker, rc={rc}")

    with httpx.Client(timeout=15.0, trust_env=False) as api_client:
        telemetry_payload = {
            "event_id": f"evt-smoke-{uuid4()}",
            "trace_id": f"trace-smoke-{uuid4()}",
            "event_type": "telemetry.water_quality.v1",
            "schema_version": "v1",
            "mode": "shadow",
            "ts": utc_now(),
            "site_id": config.site_id,
            "workshop_id": config.workshop_id,
            "pool_id": config.pool_id,
            "source": "mqtt-live-smoke",
            "payload": {
                "do_mg_l": 6.2,
                "ph": 7.8,
                "temp_c": 24.2,
                "relay_state": 0,
                "sensor_health": "online",
                "raw": {"rjy": 6.2, "temp": 24.2},
            },
        }
        publisher = mqtt.Client(client_id=f"hatchery-mqtt-pub-{uuid4()}")
        publisher.connect(config.broker_host, config.broker_port, 30)
        publisher.publish(inbound_topic, json.dumps(telemetry_payload, ensure_ascii=True), qos=1)
        publisher.disconnect()
        wait_for_pool_state(api_client, config, 6.2)
        print("[PASS] inbound MQTT telemetry reached hatchery state")

        command_id = f"cmd-smoke-{uuid4()}"
        command_payload = {
            "command_id": command_id,
            "idempotency_key": f"idem-smoke-{uuid4()}",
            "trace_id": f"trace-smoke-command-{uuid4()}",
            "mode": "sim",
            "action_type": "feed",
            "target": {
                "site_id": config.site_id,
                "workshop_id": config.workshop_id,
                "pool_id": config.pool_id,
            },
            "params": {"ratio": 0.6, "duration_sec": 120},
            "preconditions": {},
            "deadline_sec": 180,
            "degrade_policy": "",
            "dry_run": True,
        }
        response = api_client.post(f"{config.service_url}/api/v1/commands", json=command_payload, headers=config.headers())
        response.raise_for_status()
        print("[PASS] command submit reached hatchery API")

        seen_request = False
        seen_result = False
        deadline = time.time() + config.timeout_sec
        while time.time() < deadline and not (seen_request and seen_result):
            try:
                topic, payload = events.get(timeout=1)
            except queue.Empty:
                continue
            if topic == request_topic and payload["payload"].get("command_id") == command_id:
                seen_request = True
            if topic == result_topic and payload["payload"].get("command_id") == command_id:
                seen_result = True

        if not seen_request:
            raise TimeoutError("did not observe command/request topic on broker")
        if not seen_result:
            raise TimeoutError("did not observe command/result topic on broker")
        print("[PASS] outbound MQTT command events observed on broker")

    subscriber.loop_stop()
    subscriber.disconnect()
    print("HATCHERY MQTT LIVE SMOKE PASSED")


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:  # pragma: no cover - CLI flow
        print(f"HATCHERY MQTT LIVE SMOKE FAILED: {exc}", file=sys.stderr)
        raise