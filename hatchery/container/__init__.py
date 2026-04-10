"""Dependency wiring for the hatchery service."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from hatchery.adapters import MqttBridgeService, MqttRuntime
from hatchery.approval_gateway import ApprovalGateway
from hatchery.audit import AuditService
from hatchery.db import HatcheryRepository
from hatchery.execution import ExecutionService, RealExecutionAdapter, RealExecutionAdapterSettings
from hatchery.ingest import IngestService
from hatchery.policy import PolicyService
from hatchery.safety import CommandService
from hatchery.settings import HatcherySettings
from hatchery.verification import VerificationService


@dataclass
class ServiceContainer:
    repository: HatcheryRepository
    approval_gateway: ApprovalGateway
    audit_service: AuditService
    ingest_service: IngestService
    policy_service: PolicyService
    command_service: CommandService
    verification_service: VerificationService
    execution_service: ExecutionService
    mqtt_bridge: MqttBridgeService

    def start(self) -> None:
        self.mqtt_bridge.start()

    def stop(self) -> None:
        self.mqtt_bridge.stop()

    def readiness_checks(self) -> dict[str, str]:
        real_status = self.execution_service.real_adapter.status()["state"]
        return {
            "database": "ok" if self.repository.ping() else "error",
            "mqtt": self.mqtt_bridge.status(),
            "real_adapter": real_status,
        }


def build_container(settings: HatcherySettings, mqtt_runtime: Any | None = None) -> ServiceContainer:
    repository = HatcheryRepository(settings.database_path)
    approval_gateway = ApprovalGateway(provider_name=settings.approval_provider)
    audit_service = AuditService(repository)
    verification_service = VerificationService()
    ingest_service = IngestService(repository, service_name=settings.service_name)
    policy_service = PolicyService(repository)
    execution_service = ExecutionService(
        real_adapter=RealExecutionAdapter(
            RealExecutionAdapterSettings(
                enabled=settings.real_adapter_enabled,
                relay_map=settings.real_relay_map,
                default_timeout_sec=settings.real_default_timeout_sec,
                strict_mapping=settings.real_strict_mapping,
            )
        )
    )
    command_service = CommandService(
        repository=repository,
        audit_service=audit_service,
        execution_service=execution_service,
        verification_service=verification_service,
    )
    mqtt_bridge = MqttBridgeService(
        settings=settings,
        runtime=mqtt_runtime or MqttRuntime(
            host=settings.mqtt_host,
            port=settings.mqtt_port,
            client_id=settings.mqtt_client_id,
            keepalive_sec=settings.mqtt_keepalive_sec,
        ),
        ingest_service=ingest_service,
    )
    ingest_service.set_mqtt_bridge(mqtt_bridge)
    audit_service.set_mqtt_bridge(mqtt_bridge)
    command_service.set_mqtt_bridge(mqtt_bridge)
    return ServiceContainer(
        repository=repository,
        approval_gateway=approval_gateway,
        audit_service=audit_service,
        ingest_service=ingest_service,
        policy_service=policy_service,
        command_service=command_service,
        verification_service=verification_service,
        execution_service=execution_service,
        mqtt_bridge=mqtt_bridge,
    )
