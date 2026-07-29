from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone

import pytest

from poolos.delivery import (
    EndpointRegistry,
    PentairCommandClientError,
    PentairCommandRequest,
    PentairCommandResponse,
    PentairCommandTimeoutError,
    PentairVendorCommandEndpoint,
    VendorCommandGateway,
)
from poolos.hal import CommandStatus
from poolos.integration import VendorCommand


@dataclass
class RecordingPentairClient:
    response: PentairCommandResponse
    calls: list[tuple[PentairCommandRequest, float | None]] = field(
        default_factory=list
    )

    def execute(
        self,
        request: PentairCommandRequest,
        *,
        timeout: float | None = None,
    ) -> PentairCommandResponse:
        self.calls.append((request, timeout))
        return self.response


@dataclass
class ErrorPentairClient:
    error: Exception

    def execute(
        self,
        request: PentairCommandRequest,
        *,
        timeout: float | None = None,
    ) -> PentairCommandResponse:
        raise self.error


def command(
    operation: str = "pump.set_speed",
    vendor: str = "pentair",
) -> VendorCommand:
    return VendorCommand(
        vendor=vendor,
        operation=operation,
        target="filter-pump",
        parameters={"rpm": 2200},
        metadata={"operation_id": "operation-123"},
    )


def test_endpoint_adapts_vendor_command_to_client_request() -> None:
    received_at = datetime(2026, 7, 29, tzinfo=timezone.utc)
    client = RecordingPentairClient(
        PentairCommandResponse(
            accepted=True,
            acknowledged=True,
            message="queued by Home Assistant",
            command_id="ha-call-456",
            received_at=received_at,
            details={"service": "number.set_value"},
        )
    )
    endpoint = PentairVendorCommandEndpoint("intellicenter-main", client)

    receipt = endpoint.deliver(
        command(),
        correlation_id="correlation-123",
        timeout=3.5,
    )

    assert len(client.calls) == 1
    request, timeout = client.calls[0]
    assert request.operation == "pump.set_speed"
    assert request.target == "filter-pump"
    assert request.parameters == {"rpm": 2200}
    assert request.metadata == {"operation_id": "operation-123"}
    assert request.correlation_id == "correlation-123"
    assert timeout == 3.5
    assert receipt.status is CommandStatus.ACKNOWLEDGED
    assert receipt.command_id == "correlation-123"
    assert receipt.message == "queued by Home Assistant"
    assert receipt.acknowledged_at == received_at
    assert receipt.verification_required
    assert receipt.details["client_command_id"] == "ha-call-456"
    assert receipt.details["client_details"] == {
        "service": "number.set_value"
    }


@pytest.mark.parametrize(
    ("response", "expected_status"),
    [
        (
            PentairCommandResponse(accepted=True, acknowledged=False),
            CommandStatus.SENT,
        ),
        (
            PentairCommandResponse(accepted=False, message="controller denied"),
            CommandStatus.REJECTED,
        ),
    ],
)
def test_endpoint_maps_client_outcomes_to_receipts(
    response: PentairCommandResponse,
    expected_status: CommandStatus,
) -> None:
    endpoint = PentairVendorCommandEndpoint(
        "intellicenter-main",
        RecordingPentairClient(response),
    )

    receipt = endpoint.deliver(command(), correlation_id="correlation-123")

    assert receipt.status is expected_status
    assert receipt.verification_required


@pytest.mark.parametrize(
    ("error", "expected_status"),
    [
        (
            PentairCommandTimeoutError("Home Assistant request timed out"),
            CommandStatus.TIMED_OUT,
        ),
        (
            PentairCommandClientError("Home Assistant unavailable"),
            CommandStatus.FAILED,
        ),
    ],
)
def test_endpoint_maps_known_client_errors_to_receipts(
    error: Exception,
    expected_status: CommandStatus,
) -> None:
    endpoint = PentairVendorCommandEndpoint(
        "intellicenter-main",
        ErrorPentairClient(error),
    )

    receipt = endpoint.deliver(command(), correlation_id="correlation-123")

    assert receipt.status is expected_status
    assert receipt.message == str(error)
    assert receipt.details["error_type"] == type(error).__name__


def test_endpoint_rejects_vendor_mismatch_and_unknown_operation() -> None:
    client = RecordingPentairClient(PentairCommandResponse(accepted=True))
    endpoint = PentairVendorCommandEndpoint("intellicenter-main", client)

    with pytest.raises(ValueError, match="does not match"):
        endpoint.deliver(command(vendor="hayward"), correlation_id="one")

    with pytest.raises(ValueError, match="unsupported Pentair command operation"):
        endpoint.deliver(command(operation="heater.explode"), correlation_id="two")

    assert client.calls == []


def test_endpoint_validates_identity_and_correlation() -> None:
    client = RecordingPentairClient(PentairCommandResponse(accepted=True))

    with pytest.raises(ValueError, match="endpoint_id"):
        PentairVendorCommandEndpoint(" ", client)

    endpoint = PentairVendorCommandEndpoint("intellicenter-main", client)
    with pytest.raises(ValueError, match="correlation_id"):
        endpoint.deliver(command(), correlation_id=" ")


def test_request_and_response_are_validated_and_immutable() -> None:
    request = PentairCommandRequest(
        operation=" pump.start ",
        target=" filter-pump ",
        parameters={"enabled": True},
        metadata={"source": "test"},
        correlation_id=" correlation-123 ",
    )
    assert request.operation == "pump.start"
    assert request.target == "filter-pump"
    assert request.correlation_id == "correlation-123"

    with pytest.raises(TypeError):
        request.parameters["enabled"] = False  # type: ignore[index]
    with pytest.raises(ValueError, match="cannot be acknowledged"):
        PentairCommandResponse(accepted=False, acknowledged=True)
    with pytest.raises(ValueError, match="command_id"):
        PentairCommandResponse(accepted=True, command_id=" ")


def test_unexpected_client_error_remains_an_endpoint_exception() -> None:
    endpoint = PentairVendorCommandEndpoint(
        "intellicenter-main",
        ErrorPentairClient(RuntimeError("programming error")),
    )

    with pytest.raises(RuntimeError, match="programming error"):
        endpoint.deliver(command(), correlation_id="correlation-123")


def test_endpoint_composes_with_registry_and_gateway() -> None:
    endpoint = PentairVendorCommandEndpoint(
        "intellicenter-main",
        RecordingPentairClient(
            PentairCommandResponse(accepted=True, acknowledged=True)
        ),
    )
    registry = EndpointRegistry()
    registry.register(endpoint)
    gateway = VendorCommandGateway(registry)

    delivery = gateway.deliver(
        "intellicenter-main",
        command(),
        correlation_id="correlation-123",
    )

    assert delivery.endpoint_id == "intellicenter-main"
    assert delivery.correlation_id == "correlation-123"
    assert delivery.status is CommandStatus.ACKNOWLEDGED
    assert delivery.accepted
