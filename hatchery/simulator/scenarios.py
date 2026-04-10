"""Frozen sim/shadow scenarios for phase 1."""

from __future__ import annotations


class ScenarioLibrary:
    scenarios = {
        "normal": {"rjy": 6.2, "ph": 7.9, "temp": 24.8, "relay": 0},
        "threshold_breach": {"rjy": 2.8, "ph": 7.2, "temp": 29.1, "relay": 1},
        "device_timeout": {"rjy": 5.2, "ph": 7.8, "temp": 25.2, "relay": 0, "device_timeout": True},
        "network_offline": {"rjy": 5.8, "ph": 7.7, "temp": 24.3, "relay": 0, "network_offline": True},
    }

    @classmethod
    def get(cls, name: str) -> dict:
        return dict(cls.scenarios[name])
