"""Assessment rules for water-quality states."""

from __future__ import annotations

from typing import Any


def assess_pool_state(telemetry: dict[str, Any]) -> tuple[str, list[str]]:
    reasons: list[str] = []
    level = "normal"

    do_value = telemetry.get("do_mg_l")
    if do_value is not None:
        if do_value <= 3:
            level = "danger"
            reasons.append(f"DO below danger threshold: {do_value} mg/L")
        elif do_value <= 5 and level != "danger":
            level = "warn"
            reasons.append(f"DO below warning threshold: {do_value} mg/L")

    ph_value = telemetry.get("ph")
    if ph_value is not None:
        if ph_value < 6.5:
            level = "danger"
            reasons.append(f"pH below danger threshold: {ph_value}")
        elif ph_value < 7.5 and level != "danger":
            level = "warn"
            reasons.append(f"pH below warning threshold: {ph_value}")

    temp_value = telemetry.get("temp_c")
    if temp_value is not None:
        if temp_value > 31:
            level = "danger"
            reasons.append(f"temperature above danger threshold: {temp_value} C")
        elif temp_value > 28 and level != "danger":
            level = "warn"
            reasons.append(f"temperature above warning threshold: {temp_value} C")

    if not reasons:
        reasons.append("all monitored metrics within target range")
    return level, reasons
