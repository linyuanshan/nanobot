"""Executable bridge runner for hatchery business tools."""

from __future__ import annotations

import argparse
import json
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import httpx
import uvicorn
from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from hatchery.logging_utils import configure_runtime_logging
from hatchery.orchestrator_bridge.bridge import HatcheryOrchestratorBridge
from hatchery.orchestrator_bridge.client import HatcheryServiceClient
from hatchery.runtime_env import load_env_file
from hatchery.security import authorize_request


def _read_json_dict(name: str) -> dict[str, str]:
    raw = os.getenv(name)
    if not raw:
        return {}
    try:
        payload = json.loads(raw)
    except json.JSONDecodeError:
        return {}
    return {str(key): str(value) for key, value in payload.items()} if isinstance(payload, dict) else {}


def _read_bool(name: str, default: bool) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


@dataclass(slots=True)
class BridgeRunnerSettings:
    service_url: str = "http://127.0.0.1:8090"
    host: str = "127.0.0.1"
    port: int = 8190
    name: str = "hatchery-bridge"
    auth_enabled: bool = False
    auth_tokens: dict[str, str] = field(default_factory=dict)
    service_token: str = ""
    service_actor: str = "bridge-service"
    log_dir: str = "workspace/hatchery/logs"
    log_level: str = "INFO"
    log_max_bytes: int = 2_000_000
    log_backup_count: int = 5

    @classmethod
    def from_env(cls) -> "BridgeRunnerSettings":
        load_env_file()
        return cls(
            service_url=os.getenv("HATCHERY_BRIDGE_SERVICE_URL", "http://127.0.0.1:8090"),
            host=os.getenv("HATCHERY_BRIDGE_HOST", "127.0.0.1"),
            port=int(os.getenv("HATCHERY_BRIDGE_PORT", "8190")),
            name=os.getenv("HATCHERY_BRIDGE_NAME", "hatchery-bridge"),
            auth_enabled=_read_bool("HATCHERY_BRIDGE_AUTH_ENABLED", False),
            auth_tokens=_read_json_dict("HATCHERY_BRIDGE_AUTH_TOKENS_JSON"),
            service_token=os.getenv("HATCHERY_BRIDGE_SERVICE_TOKEN", ""),
            service_actor=os.getenv("HATCHERY_BRIDGE_SERVICE_ACTOR", "bridge-service"),
            log_dir=os.getenv("HATCHERY_LOG_DIR", "workspace/hatchery/logs"),
            log_level=os.getenv("HATCHERY_LOG_LEVEL", "INFO"),
            log_max_bytes=int(os.getenv("HATCHERY_LOG_MAX_BYTES", "2000000")),
            log_backup_count=int(os.getenv("HATCHERY_LOG_BACKUP_COUNT", "5")),
        )


def _service_headers(settings: BridgeRunnerSettings) -> dict[str, str]:
    headers: dict[str, str] = {}
    if settings.service_token:
        headers["X-Hatchery-Token"] = settings.service_token
    if settings.service_actor:
        headers["X-Hatchery-Actor"] = settings.service_actor
    return headers


def create_bridge_app(
    settings: BridgeRunnerSettings | None = None,
    *,
    bridge: HatcheryOrchestratorBridge | Any | None = None,
    ready_client: HatcheryServiceClient | Any | None = None,
) -> FastAPI:
    settings = settings or BridgeRunnerSettings.from_env()
    service_headers = _service_headers(settings)
    bridge = bridge or HatcheryOrchestratorBridge(settings.service_url)
    if hasattr(bridge, "client") and isinstance(bridge.client, HatcheryServiceClient):
        bridge.client.default_headers = service_headers
    ready_client = ready_client or HatcheryServiceClient(settings.service_url, default_headers=service_headers)

    app = FastAPI(title="Hatchery Orchestrator Bridge")
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_methods=["*"],
        allow_headers=["*"],
    )
    app.state.settings = settings
    app.state.bridge = bridge
    app.state.ready_client = ready_client

    def require(request: Request, minimum_role: str, *, require_actor: bool = False):
        return authorize_request(
            request,
            enabled=settings.auth_enabled,
            tokens=settings.auth_tokens,
            minimum_role=minimum_role,
            require_actor=require_actor,
        )

    @app.get("/healthz")
    def healthz() -> dict[str, Any]:
        return {
            "status": "ok",
            "name": settings.name,
            "service_url": settings.service_url,
            "tool_count": len(bridge.tool_registry.tool_names),
            "auth_enabled": settings.auth_enabled,
        }

    @app.get("/readyz")
    async def readyz() -> JSONResponse:
        try:
            payload = await ready_client.get("/readyz")
        except Exception as exc:
            return JSONResponse(status_code=503, content={"status": "not_ready", "detail": str(exc)})
        status = payload.get("status", "not_ready")
        return JSONResponse(status_code=200 if status == "ready" else 503, content=payload)

    @app.get("/tools")
    def list_tools(request: Request) -> dict[str, Any]:
        require(request, "operator")
        tools = []
        for name in bridge.tool_registry.tool_names:
            tool = bridge.tool_registry.get(name)
            if tool is None:
                continue
            tools.append(
                {
                    "name": tool.name,
                    "description": tool.description,
                    "parameters": tool.parameters,
                }
            )
        return {"tools": tools}

    @app.post("/tools/{tool_name}/invoke")
    async def invoke_tool(tool_name: str, request: Request) -> dict[str, Any]:
        require(request, "operator", require_actor=True)
        tool = bridge.tool_registry.get(tool_name)
        if tool is None:
            raise HTTPException(status_code=404, detail="tool not found")
        payload = await request.json()
        try:
            raw_result = await tool.execute(**payload)
        except httpx.HTTPStatusError as exc:
            raise HTTPException(status_code=exc.response.status_code, detail="upstream hatchery service error") from exc
        except httpx.HTTPError as exc:
            raise HTTPException(status_code=502, detail="unable to reach hatchery service") from exc
        try:
            result = json.loads(raw_result)
        except json.JSONDecodeError:
            result = raw_result
        return {"tool": tool_name, "result": result}

    return app


def main() -> None:
    settings = BridgeRunnerSettings.from_env()
    configure_runtime_logging(
        service_name=settings.name,
        log_dir=Path(settings.log_dir),
        level=settings.log_level,
        max_bytes=settings.log_max_bytes,
        backup_count=settings.log_backup_count,
    )
    parser = argparse.ArgumentParser(description="Run the hatchery bridge service")
    parser.add_argument("--service-url", default=settings.service_url)
    parser.add_argument("--host", default=settings.host)
    parser.add_argument("--port", type=int, default=settings.port)
    args = parser.parse_args()

    app = create_bridge_app(
        BridgeRunnerSettings(
            service_url=args.service_url,
            host=args.host,
            port=args.port,
            name=settings.name,
            auth_enabled=settings.auth_enabled,
            auth_tokens=settings.auth_tokens,
            service_token=settings.service_token,
            service_actor=settings.service_actor,
            log_dir=settings.log_dir,
            log_level=settings.log_level,
            log_max_bytes=settings.log_max_bytes,
            log_backup_count=settings.log_backup_count,
        )
    )
    uvicorn.run(app, host=args.host, port=args.port)


if __name__ == "__main__":
    main()

