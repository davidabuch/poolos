"""Tests for the simulator-only execution gateway composition boundary."""

from __future__ import annotations

from dataclasses import dataclass
from typing import ClassVar

import pytest

from poolos.delivery import (
    DeliveryEndpointKind,
    EndpointVendorMismatchError,
    SimulatorVendorCommandEndpoint,
)
from poolos.environment import RuntimeMode, build_runtime_environment
from poolos.hal import CommandReceipt, CommandStatus, SimulatorTransport
from poolos.integration import VendorCommand
from poolos.simulator_execution_gateway import (
    SimulatorExecutionGateway,
    SimulatorExecutionGatewayError,
)


def command(vendor: str = "pentair") -> VendorCommand:
    return VendorCommand(
        vendor=vendor,
        operation="pump.set_speed",
        target="filter-pump",
        parameters={"rpm": 2100},
    )


def connected_endpoint(endpoint_id: str, vendor: str = "pentair") -> SimulatorVendorCommandEndpoint:
    transport = SimulatorTransport()
    transport.connect()
    return SimulatorVendorCommandEndpoint(endpoint_id, vendor, transport)


def simulation_environment(*endpoints: object):
    return build_runtime_environment(
        mode=RuntimeMode.SIMULATION,
        installation_id="buch-family-simulator",
        endpoints=endpoints,  # type: ignore[arg-type]
    )


@dataclass(slots=True)
class ShadowEndpoint:
    delivery_kind: ClassVar[DeliveryEndpointKind] = DeliveryEndpointKind.SHADOW
    endpoint_id: str = "shadow"
    vendor: str = "pentair"

    def deliver(
        self,
        command: VendorCommand,
        *,
        correlation_id: str,
        timeout: float | None = None,
    ) -> CommandReceipt:
        return CommandReceipt(CommandStatus.ACKNOWLEDGED)


def test_gateway_builds_from_simulation_environment_and_exposes_routes() -> None:
    endpoint = SimulatorVendorCommandEndpoint("sim-main", "Pentair")

    gateway = SimulatorExecutionGateway.from_environment(
        simulation_environment(endpoint)
    )

    assert gateway.environment.mode is RuntimeMode.SIMULATION
    assert gateway.endpoint_ids == ("sim-main",)
    assert gateway.routes[0].vendor == "pentair"


def test_gateway_requires_at_least_one_simulator_endpoint() -> None:
    environment = simulation_environment()

    with pytest.raises(SimulatorExecutionGatewayError, match="at least one"):
        SimulatorExecutionGateway.from_environment(environment)


def test_gateway_rejects_non_simulation_runtime() -> None:
    environment = build_runtime_environment(
        mode=RuntimeMode.SHADOW,
        installation_id="shadow-runtime",
        endpoints=(ShadowEndpoint(),),
    )

    with pytest.raises(SimulatorExecutionGatewayError, match="simulation runtime mode"):
        SimulatorExecutionGateway.from_environment(environment)


def test_gateway_delivers_through_existing_simulator_endpoint() -> None:
    transport = SimulatorTransport()
    transport.connect()
    endpoint = SimulatorVendorCommandEndpoint("sim-main", "pentair", transport)
    gateway = SimulatorExecutionGateway.from_environment(
        simulation_environment(endpoint)
    )

    result = gateway.deliver(command(), correlation_id="execution-step-1")

    assert result.endpoint_id == "sim-main"
    assert result.correlation_id == "execution-step-1"
    assert result.status is CommandStatus.ACKNOWLEDGED
    stored = transport.read("vendor-commands/pentair/filter-pump").payload
    assert stored["correlation_id"] == "execution-step-1"


def test_gateway_preserves_timeout_and_explicit_endpoint_selection() -> None:
    first = connected_endpoint("sim-one")
    second = connected_endpoint("sim-two")
    gateway = SimulatorExecutionGateway.from_environment(
        simulation_environment(first, second)
    )

    result = gateway.deliver(
        command(),
        correlation_id="execution-step-2",
        endpoint_id="sim-two",
        timeout=3.0,
    )

    assert result.endpoint_id == "sim-two"
    assert result.accepted


def test_automatic_vendor_routing_rejects_ambiguous_routes() -> None:
    gateway = SimulatorExecutionGateway.from_environment(
        simulation_environment(
            SimulatorVendorCommandEndpoint("sim-one", "pentair"),
            SimulatorVendorCommandEndpoint("sim-two", "pentair"),
        )
    )

    with pytest.raises(SimulatorExecutionGatewayError, match="multiple simulator"):
        gateway.deliver(command(), correlation_id="execution-step-1")


def test_automatic_vendor_routing_rejects_missing_vendor() -> None:
    gateway = SimulatorExecutionGateway.from_environment(
        simulation_environment(
            SimulatorVendorCommandEndpoint("sim-main", "pentair")
        )
    )

    with pytest.raises(SimulatorExecutionGatewayError, match="no simulator endpoint"):
        gateway.deliver(command("hayward"), correlation_id="execution-step-1")


def test_explicit_route_must_be_admitted_by_gateway() -> None:
    gateway = SimulatorExecutionGateway.from_environment(
        simulation_environment(
            SimulatorVendorCommandEndpoint("sim-main", "pentair")
        )
    )

    with pytest.raises(SimulatorExecutionGatewayError, match="not admitted"):
        gateway.deliver(
            command(),
            correlation_id="execution-step-1",
            endpoint_id="unknown",
        )


def test_explicit_route_still_enforces_vendor_compatibility() -> None:
    gateway = SimulatorExecutionGateway.from_environment(
        simulation_environment(
            SimulatorVendorCommandEndpoint("sim-main", "pentair")
        )
    )

    with pytest.raises(EndpointVendorMismatchError, match="vendor mismatch"):
        gateway.deliver(
            command("hayward"),
            correlation_id="execution-step-1",
            endpoint_id="sim-main",
        )


def test_gateway_does_not_expose_coordinator_or_operation_translation() -> None:
    public_names = set(dir(SimulatorExecutionGateway))

    assert "execute_plan" not in public_names
    assert "advance" not in public_names
    assert "translate" not in public_names
    assert "verify" not in public_names
    assert "gateway" not in public_names
