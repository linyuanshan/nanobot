from __future__ import annotations

import argparse
import json
import sys
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

import httpx


@dataclass(slots=True)
class Harness:
    service_url: str
    bridge_url: str | None
    api_token: str
    bridge_token: str
    actor: str
    timeout_sec: int

    def api_headers(self) -> dict[str, str]:
        headers: dict[str, str] = {}
        if self.api_token:
            headers["X-Hatchery-Token"] = self.api_token
        if self.actor:
            headers["X-Hatchery-Actor"] = self.actor
        return headers

    def bridge_headers(self) -> dict[str, str]:
        headers: dict[str, str] = {}
        if self.bridge_token:
            headers["X-Hatchery-Token"] = self.bridge_token
        if self.actor:
            headers["X-Hatchery-Actor"] = self.actor
        return headers


def stamp() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%d%H%M%S")


def print_step(message: str) -> None:
    print(f"\n==> {message}")


def assert_true(condition: bool, message: str) -> None:
    if not condition:
        raise AssertionError(message)
    print(f"[PASS] {message}")


def request_json(client: httpx.Client, method: str, url: str, *, headers: dict[str, str], payload: dict[str, Any] | None = None) -> tuple[int, Any]:
    response = client.request(method, url, json=payload, headers=headers)
    try:
        body = response.json()
    except ValueError:
        body = response.text
    return response.status_code, body


def wait_for_command(client: httpx.Client, harness: Harness, command_id: str, expected_status: str) -> dict[str, Any]:
    deadline = time.time() + harness.timeout_sec
    while time.time() < deadline:
        status_code, payload = request_json(
            client,
            "GET",
            f"{harness.service_url}/api/v1/commands/{command_id}",
            headers=harness.api_headers(),
        )
        if status_code == 200 and payload["status"] == expected_status:
            return payload
        time.sleep(2)
    raise TimeoutError(f"command {command_id} did not reach {expected_status}")


def main() -> None:
    parser = argparse.ArgumentParser(description="Run hatchery API and bridge end-to-end checks")
    parser.add_argument("--service-url", default="http://127.0.0.1:8090")
    parser.add_argument("--bridge-url", default="http://127.0.0.1:8190")
    parser.add_argument("--api-token", default="")
    parser.add_argument("--bridge-token", default="")
    parser.add_argument("--actor", default="e2e-harness")
    parser.add_argument("--timeout-sec", type=int, default=60)
    parser.add_argument("--skip-bridge", action="store_true")
    args = parser.parse_args()

    harness = Harness(
        service_url=args.service_url.rstrip("/"),
        bridge_url=None if args.skip_bridge else args.bridge_url.rstrip("/"),
        api_token=args.api_token,
        bridge_token=args.bridge_token or args.api_token,
        actor=args.actor,
        timeout_sec=args.timeout_sec,
    )

    with httpx.Client(timeout=15.0, trust_env=False) as client:
        print_step("Health checks")
        status_code, health = request_json(client, "GET", f"{harness.service_url}/healthz", headers=harness.api_headers())
        assert_true(status_code == 200 and health["status"] == "ok", "API health returns ok")
        status_code, ready = request_json(client, "GET", f"{harness.service_url}/readyz", headers=harness.api_headers())
        assert_true(status_code in {200, 503}, "API ready endpoint is reachable")

        unique = stamp()

        print_step("Telemetry ingest")
        telemetry = {
            "site_id": "site-001",
            "workshop_id": "ws-001",
            "pool_id": "pool-01",
            "mode": "sim",
            "ts": "2026-02-07T10:00:00Z",
            "payload": {
                "relay": 0,
                "ph": 7.4,
                "hzd": 3,
                "rjy": 5.9,
                "temp": 24.5,
            },
        }
        status_code, telemetry_response = request_json(
            client,
            "POST",
            f"{harness.service_url}/api/v1/telemetry/water-quality",
            headers=harness.api_headers(),
            payload=telemetry,
        )
        assert_true(status_code == 202, "Telemetry ingest returns 202")
        assert_true(telemetry_response["payload"]["do_mg_l"] == 5.9, "Telemetry normalized do_mg_l field")

        print_step("Bio ingest and pool query")
        bio = {
            "site_id": "site-001",
            "workshop_id": "ws-001",
            "pool_id": "pool-01",
            "mode": "sim",
            "ts": "2026-02-07T10:05:00Z",
            "payload": {
                "count": 120,
                "activity_score": 0.65,
                "hunger_score": 0.85,
                "confidence": 0.98,
                "model_version": "replay-v1",
            },
        }
        status_code, _ = request_json(
            client,
            "POST",
            f"{harness.service_url}/api/v1/perception/bio",
            headers=harness.api_headers(),
            payload=bio,
        )
        assert_true(status_code == 202, "Bio ingest returns 202")
        status_code, pool_state = request_json(
            client,
            "GET",
            f"{harness.service_url}/api/v1/pools/pool-01/state",
            headers=harness.api_headers(),
        )
        assert_true(status_code == 200 and pool_state["pool_id"] == "pool-01", "Pool state query returns pool-01")

        print_step("Low-risk command")
        low_risk_command_id = f"cmd-e2e-feed-{unique}"
        low_risk = {
            "command_id": low_risk_command_id,
            "idempotency_key": f"idem-e2e-feed-{unique}",
            "trace_id": f"trace-e2e-feed-{unique}",
            "mode": "sim",
            "action_type": "feed",
            "target": {
                "site_id": "site-001",
                "workshop_id": "ws-001",
                "pool_id": "pool-01",
            },
            "params": {"ratio": 0.6, "duration_sec": 120},
            "preconditions": {},
            "deadline_sec": 180,
            "degrade_policy": "",
            "dry_run": True,
        }
        status_code, low_risk_result = request_json(
            client,
            "POST",
            f"{harness.service_url}/api/v1/commands",
            headers=harness.api_headers(),
            payload=low_risk,
        )
        assert_true(status_code == 200, "Low-risk command returns 200")
        assert_true(low_risk_result["status"] == "Closed", "Low-risk command closes immediately")

        print_step("High-risk command and approval")
        high_risk_command_id = f"cmd-e2e-water-{unique}"
        high_risk = {
            "command_id": high_risk_command_id,
            "idempotency_key": f"idem-e2e-water-{unique}",
            "trace_id": f"trace-e2e-water-{unique}",
            "mode": "shadow",
            "action_type": "water_change",
            "target": {
                "site_id": "site-001",
                "workshop_id": "ws-001",
                "pool_id": "pool-01",
            },
            "params": {"ratio": 0.3, "duration_sec": 180},
            "preconditions": {},
            "deadline_sec": 180,
            "degrade_policy": "aerate_up_on_timeout",
            "dry_run": True,
        }
        status_code, high_risk_result = request_json(
            client,
            "POST",
            f"{harness.service_url}/api/v1/commands",
            headers=harness.api_headers(),
            payload=high_risk,
        )
        assert_true(status_code == 202, "High-risk command returns 202")
        approval_id = high_risk_result["approval_id"]
        status_code, confirm_result = request_json(
            client,
            "POST",
            f"{harness.service_url}/api/v1/approvals/{approval_id}/confirm",
            headers=harness.api_headers(),
            payload={"operator": harness.actor, "reason": "approved by e2e"},
        )
        assert_true(status_code == 200 and confirm_result["status"] == "Closed", "High-risk approval completes command")

        print_step("Ops summary and audits")
        status_code, summary = request_json(
            client,
            "GET",
            f"{harness.service_url}/api/v1/ops/summary",
            headers=harness.api_headers(),
        )
        assert_true(status_code == 200 and summary["commands"]["total"] >= 2, "Ops summary reports commands")
        status_code, audits = request_json(
            client,
            "GET",
            f"{harness.service_url}/api/v1/audits?trace_id=trace-e2e-water-{unique}",
            headers=harness.api_headers(),
        )
        assert_true(status_code == 200 and len(audits) >= 2, "Audit query returns records for high-risk trace")

        if harness.bridge_url:
            print_step("Bridge query and submit")
            status_code, tools = request_json(client, "GET", f"{harness.bridge_url}/tools", headers=harness.bridge_headers())
            assert_true(status_code == 200 and len(tools["tools"]) >= 1, "Bridge tool listing works")
            status_code, bridge_pool = request_json(
                client,
                "POST",
                f"{harness.bridge_url}/tools/query_pool_state/invoke",
                headers=harness.bridge_headers(),
                payload={"pool_id": "pool-01"},
            )
            assert_true(status_code == 200 and bridge_pool["result"]["pool_id"] == "pool-01", "Bridge query_pool_state works")
            bridge_command_id = f"cmd-bridge-e2e-{unique}"
            status_code, bridge_command = request_json(
                client,
                "POST",
                f"{harness.bridge_url}/tools/submit_safe_command/invoke",
                headers=harness.bridge_headers(),
                payload={
                    "command_id": bridge_command_id,
                    "idempotency_key": f"idem-bridge-e2e-{unique}",
                    "trace_id": f"trace-bridge-e2e-{unique}",
                    "mode": "sim",
                    "action_type": "feed",
                    "target": {
                        "site_id": "site-001",
                        "workshop_id": "ws-001",
                        "pool_id": "pool-01",
                    },
                    "params": {"ratio": 0.6, "duration_sec": 120},
                    "preconditions": {},
                    "deadline_sec": 180,
                    "degrade_policy": "",
                    "dry_run": True,
                },
            )
            assert_true(status_code == 200 and bridge_command["result"]["status"] == "Closed", "Bridge submit_safe_command works")

    print("\nHATCHERY E2E PASSED")


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:  # pragma: no cover - CLI flow
        print(f"HATCHERY E2E FAILED: {exc}", file=sys.stderr)
        raise