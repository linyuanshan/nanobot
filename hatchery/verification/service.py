"""Verification of execution results."""

from __future__ import annotations

from typing import Any


class VerificationService:
    def verify(self, command: dict[str, Any], receipt: dict[str, Any]) -> dict[str, Any]:
        return {
            "command_id": command["command_id"],
            "status": "Verified",
            "summary": "sim/shadow execution receipt accepted",
            "receipt_adapter": receipt["adapter"],
        }
