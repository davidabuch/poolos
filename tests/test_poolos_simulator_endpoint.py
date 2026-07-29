"""Tests for the simulator-backed vendor command endpoint."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone

import pytest

from poolos.delivery import (
    EndpointRegistry,
    SimulatorVendorCommandEndpoint,
    VendorCommandGateway,
)
from poolos.hal import (
    CommandStatus,
    CommandTimeoutError,
    SimulatorTransport,
    Transport,
    TransportError,
    TransportMetadata,
    TransportResponse,
    TransportState,
)
from poolos.integration import VendorCommand


def command(vendor: str = "pentair") -> VendorCommand:
    return VendorCommand(
        vendor=vendor,
        operation="pump.set_speed",
        target="filter-pump",
        parameters={"rpm": 2200},
        metadata={"operation_id": "operation-123"},
    )


@dataclass(slots=True)
class RecordingTransport(Transport):
    response: TransportResponse
    calls: list[tuple[str, object, float | None]] = field(default_factory=list)

    def connect(self) -> None:
        pass

    def disconnect(self) -> None:
        pass

    def send(
        self,
        destination: str,
        payload: object,
        *,
        timeout: float | None = None,
    ) -> TransportResponse:
        self.calls.append((destination, payload, timeout))
        return self.response

    def read(
        self,
        source: str,
        *,
        timeout: float | None = None,
    ) -> TransportResponse:
        raise NotImplementedError

    def metadata(self) -> TransportMetadata:
        return TransportMetadata("recording", state=TransportState.CONNECTED)


@dataclass(slots=True)
class ErrorTransport(Transport):
    error: Exception

    def connect(self) -> None:
        pass

    def disconnect(self) -> None:
        pass

    def send(
        self,
        destination: str,
        payload: object,
        *,
        timeout: float | None = None,
    ) -> TransportResponse:
        raise self.error

    def read(
        self,
        source: str,
        *,
        timeout: float | None = None,
    ) -> TransportResponse:
        raise NotImplementedError

    def metadata(self) -> TransportMetadata:
        return TransportMetadata("error", state=TransportState.ERROR)


def test_endpoint_delivers_deterministic_payload_to_simulator_transport() -> None:
    transport = SimulatorTransport()
    transport.connect()
    endpoint = SimulatorVendorCommandEndpoint(
        "main-controller",
        "pentair",
        transport,
    )
    vendor_command = command()

    receipt = endpoint.deliver(
        vendor_command,
        correlation_id="correlation-123",
        timeout=2.5,
    )

    destination = "vendor-commands/pentair/filter-pump"
    stored = transport.read(destination).payload
    assert stored == {
        "vendor": "pentair",
        "operation": "pump.set_speed",
        "target": "filter-pump",
        "parameters": {"rpm": 2200},
        "metadata": {"operation_id": "operation-123"},
        "correlation_id": "correlation-123",
        "endpoint_id": "main-controller",
    }
    assert receipt.status is CommandStatus.ACKNOWLEDGED
    assert receipt.command_id == "correlation-123"
    assert receipt.acknowledged_at is not None
    assert receipt.verification_required
    assert receipt.details["destination"] == destination


def test_endpoint_propagates_timeout_and_preserves_context() -> None:
    received_at = datetime(2026, 7, 28, tzinfo=timezone.utc)
    transport = RecordingTransport(
        TransportResponse(
            accepted=True,
            acknowledged=False,
            payload={"queued": True},
            received_at=received_at,
            correlation_id="transport-456",
        )
    )
    endpoint = SimulatorVendorCommandEndpoint(
        "main-controller",
        "pentair",
        transport,
        destination_prefix="simulation/commands/",
    )

    receipt = endpoint.deliver(
        command(),
        correlation_id="correlation-123",
        timeout=4.0,
    )

    assert len(transport.calls) == 1
    destination, payload, timeout = transport.calls[0]
    assert destination == "simulation/commands/pentair/filter-pump"
    assert isinstance(payload, dict)
    assert payload["correlation_id"] == "correlation-123"
    assert timeout == 4.0
    assert receipt.status is CommandStatus.SENT
    assert receipt.acknowledged_at is None
    assert receipt.details["transport_correlation_id"] == "transport-456"


def test_endpoint_maps_transport_rejection_without_synthesizing_failure() -> None:
    endpoint = SimulatorVendorCommandEndpoint(
        "main-controller",
        "pentair",
        RecordingTransport(
            TransportResponse(
                accepted=False,
                acknowledged=False,
                payload={"reason": "denied"},
            )
        ),
    )

    receipt = endpoint.deliver(command(), correlation_id="correlation-123")

    assert receipt.status is CommandStatus.REJECTED
    assert not receipt.accepted
    assert receipt.details["transport_payload"] == {"reason": "denied"}


@pytest.mark.parametrize(
    ("error", "expected_status"),
    [
        (CommandTimeoutError("simulator timeout"), CommandStatus.TIMED_OUT),
        (TransportError("simulator unavailable"), CommandStatus.FAILED),
    ],
)
def test_endpoint_maps_known_transport_errors_to_receipts(
    error: Exception,
    expected_status: CommandStatus,
) -> None:
    endpoint = SimulatorVendorCommandEndpoint(
        "main-controller",
        "pentair",
        ErrorTransport(error),
    )

    receipt = endpoint.deliver(command(), correlation_id="correlation-123")

    assert receipt.status is expected_status
    assert receipt.command_id == "correlation-123"
    assert receipt.message == str(error)
    assert receipt.details["error_type"] == type(error).__name__


def test_endpoint_rejects_vendor_mismatch_when_called_directly() -> None:
    endpoint = SimulatorVendorCommandEndpoint("main-controller", "pentair")

    with pytest.raises(ValueError, match="does not match"):
        endpoint.deliver(command("hayward"), correlation_id="correlation-123")


def test_endpoint_validates_identity_vendor_prefix_and_correlation() -> None:
    with pytest.raises(ValueError, match="endpoint_id"):
        SimulatorVendorCommandEndpoint(" ", "pentair")
    with pytest.raises(ValueError, match="vendor"):
        SimulatorVendorCommandEndpoint("main-controller", " ")
    with pytest.raises(ValueError, match="destination_prefix"):
        SimulatorVendorCommandEndpoint(
            "main-controller",
            "pentair",
            destination_prefix=" / ",
        )

    endpoint = SimulatorVendorCommandEndpoint("main-controller", "pentair")
    with pytest.raises(ValueError, match="correlation_id"):
        endpoint.deliver(command(), correlation_id=" ")


def test_endpoint_composes_with_registry_and_gateway() -> None:
    transport = SimulatorTransport()
    transport.connect()
    endpoint = SimulatorVendorCommandEndpoint(
        "main-controller",
        "pentair",
        transport,
    )
    registry = EndpointRegistry()
    registry.register(endpoint)
    gateway = VendorCommandGateway(registry)

    delivery = gateway.deliver(
        "main-controller",
        command(),
        correlation_id="correlation-123",
    )

    assert delivery.endpoint_id == "main-controller"
    assert delivery.correlation_id == "correlation-123"
    assert delivery.status is CommandStatus.ACKNOWLEDGED
    assert delivery.accepted
