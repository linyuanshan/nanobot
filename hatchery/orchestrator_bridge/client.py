"""HTTP client for the hatchery business service."""

from __future__ import annotations

import httpx


class HatcheryServiceClient:
    def __init__(self, service_url: str, default_headers: dict[str, str] | None = None):
        self.service_url = service_url.rstrip("/")
        self.default_headers = dict(default_headers or {})

    async def post(self, path: str, payload: dict, headers: dict[str, str] | None = None) -> dict:
        merged_headers = {**self.default_headers, **(headers or {})}
        async with httpx.AsyncClient(base_url=self.service_url, timeout=10.0, trust_env=False) as client:
            response = await client.post(path, json=payload, headers=merged_headers)
            response.raise_for_status()
            return response.json()

    async def get(self, path: str, headers: dict[str, str] | None = None) -> dict:
        merged_headers = {**self.default_headers, **(headers or {})}
        async with httpx.AsyncClient(base_url=self.service_url, timeout=10.0, trust_env=False) as client:
            response = await client.get(path, headers=merged_headers)
            response.raise_for_status()
            return response.json()
