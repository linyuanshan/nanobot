"""nanobot tool adapters for hatchery orchestrator bridge."""

from __future__ import annotations

import json
from uuid import uuid4
from typing import Any

import httpx

from nanobot.agent.tools.base import Tool

from hatchery.orchestrator_bridge.client import HatcheryServiceClient
from hatchery.orchestrator_bridge.tools import build_tool_registry


class HatcheryBridgeInvokeTool(Tool):
    """Adapter that invokes a hatchery bridge tool through HTTP."""

    def __init__(
        self,
        *,
        bridge_url: str,
        bridge_tool_name: str,
        description: str,
        parameters: dict[str, Any],
        bridge_token: str = "",
        actor: str = "nanobot-gateway",
    ):
        self._bridge_url = bridge_url.rstrip("/")
        self._bridge_tool_name = bridge_tool_name
        self._description = description
        self._parameters = parameters
        self._bridge_token = bridge_token
        self._actor = actor

    @property
    def name(self) -> str:
        return self._bridge_tool_name

    @property
    def description(self) -> str:
        return f"[hatchery bridge] {self._description}"

    @property
    def parameters(self) -> dict[str, Any]:
        return self._parameters

    async def execute(self, **kwargs: Any) -> str:
        headers: dict[str, str] = {}
        if self._bridge_token:
            headers["X-Hatchery-Token"] = self._bridge_token
        if self._actor:
            headers["X-Hatchery-Actor"] = self._actor

        payload = dict(kwargs)
        if self._bridge_tool_name == "submit_safe_command":
            payload = await self._normalize_submit_payload(payload, headers)
            target = payload.get("target")
            missing_target = [
                key
                for key in ("site_id", "workshop_id", "pool_id")
                if not isinstance(target, dict) or not target.get(key)
            ]
            if missing_target:
                return json.dumps(
                    {
                        "ok": False,
                        "error": "invalid_submit_payload",
                        "detail": (
                            "target.site_id/workshop_id/pool_id are required; "
                            "provide target or include pool_id for auto-fill"
                        ),
                        "missing": missing_target,
                        "tool": self._bridge_tool_name,
                    },
                    ensure_ascii=False,
                    sort_keys=True,
                )

        try:
            response = await self._invoke_tool(self._bridge_tool_name, payload, headers)
            response.raise_for_status()
        except httpx.HTTPStatusError as exc:
            detail = _extract_error_detail(exc.response)
            return json.dumps(
                {
                    "ok": False,
                    "error": f"bridge_http_{exc.response.status_code}",
                    "detail": detail,
                    "tool": self._bridge_tool_name,
                },
                ensure_ascii=False,
                sort_keys=True,
            )
        except httpx.HTTPError as exc:
            return json.dumps(
                {
                    "ok": False,
                    "error": "bridge_unreachable",
                    "detail": str(exc),
                    "tool": self._bridge_tool_name,
                },
                ensure_ascii=False,
                sort_keys=True,
            )

        try:
            payload = response.json()
        except ValueError:
            return response.text
        return json.dumps(payload, ensure_ascii=False, sort_keys=True)

    async def _invoke_tool(
        self,
        tool_name: str,
        payload: dict[str, Any],
        headers: dict[str, str],
    ) -> httpx.Response:
        endpoint = f"{self._bridge_url}/tools/{tool_name}/invoke"
        async with httpx.AsyncClient(timeout=10.0, trust_env=False) as client:
            return await client.post(endpoint, json=payload, headers=headers)

    async def _normalize_submit_payload(
        self,
        payload: dict[str, Any],
        headers: dict[str, str],
    ) -> dict[str, Any]:
        normalized = dict(payload)
        if not normalized.get("command_id"):
            normalized["command_id"] = f"cmd-auto-{uuid4().hex[:12]}"
        if not normalized.get("idempotency_key"):
            normalized["idempotency_key"] = str(normalized["command_id"])
        if not normalized.get("trace_id"):
            normalized["trace_id"] = f"trace-auto-{uuid4().hex[:12]}"

        target = normalized.get("target")
        if not isinstance(target, dict):
            target = {}
        pool_id = _first_non_empty(
            target.get("pool_id"),
            normalized.get("pool_id"),
        )

        if pool_id and (
            not target.get("site_id")
            or not target.get("workshop_id")
            or not target.get("pool_id")
        ):
            pool_state = await self._query_pool_state(pool_id, headers)
            if pool_state:
                target.setdefault("site_id", pool_state.get("site_id"))
                target.setdefault("workshop_id", pool_state.get("workshop_id"))
                target.setdefault("pool_id", pool_state.get("pool_id"))

        if pool_id and not target.get("pool_id"):
            target["pool_id"] = pool_id
        normalized["target"] = target
        return normalized

    async def _query_pool_state(
        self,
        pool_id: str,
        headers: dict[str, str],
    ) -> dict[str, Any] | None:
        try:
            response = await self._invoke_tool(
                "query_pool_state",
                {"pool_id": pool_id},
                headers,
            )
            response.raise_for_status()
            payload = response.json()
        except Exception:
            return None
        if not isinstance(payload, dict):
            return None
        result = payload.get("result")
        return result if isinstance(result, dict) else None


def build_hatchery_bridge_tools(
    *,
    bridge_url: str,
    bridge_token: str = "",
    actor: str = "nanobot-gateway",
) -> list[Tool]:
    """Build nanobot tool adapters from hatchery bridge whitelist metadata."""
    metadata_registry = build_tool_registry(HatcheryServiceClient("http://127.0.0.1:8090"))
    tools: list[Tool] = []
    for bridge_tool_name in metadata_registry.tool_names:
        bridge_tool = metadata_registry.get(bridge_tool_name)
        if bridge_tool is None:
            continue
        tools.append(
            HatcheryBridgeInvokeTool(
                bridge_url=bridge_url,
                bridge_tool_name=bridge_tool.name,
                description=bridge_tool.description,
                parameters=bridge_tool.parameters,
                bridge_token=bridge_token,
                actor=actor,
            )
        )
    return tools


def _extract_error_detail(response: httpx.Response) -> Any:
    try:
        payload = response.json()
    except ValueError:
        return response.text
    if isinstance(payload, dict):
        return payload.get("detail", payload)
    return payload


def _first_non_empty(*values: Any) -> str | None:
    for value in values:
        if isinstance(value, str) and value.strip():
            return value.strip()
    return None
