"""Local/mock approval gateway."""

from __future__ import annotations


class ApprovalGateway:
    def __init__(self, provider_name: str = "local"):
        self.provider_name = provider_name

    def create_request_metadata(self) -> dict[str, str]:
        return {"provider": self.provider_name, "channel": "mock"}
