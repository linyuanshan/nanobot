"""Feishu approval provider placeholder for future integration."""

from __future__ import annotations


class FeishuApprovalProvider:
    provider_name = "feishu"

    def build_callback_payload(self, approval_id: str) -> dict[str, str]:
        return {
            "approval_id": approval_id,
            "status": "pending",
            "note": "Feishu callback wiring is intentionally deferred to a later phase",
        }
