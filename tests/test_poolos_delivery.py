"""Tests for vendor-command delivery contracts and gateway routing."""

from __future__ import annotations

from dataclasses import dataclass, field

import pytest

from poolos.delivery import (
    DuplicateEndpointError,
    EndpointDeliveryError,
    EndpointNotFoundError,
    EndpointRegistry,
    EndpointVendorMismatchError,
    VendorCommandGateway,
)
from poolos.hal import CommandReceipt, CommandStatus
from poolos.integration import VendorCommand


@dataclass(slots=True)
class RecordingEndpoint:
    endpoint_id: str
    vendor: str
    receipt: CommandReceipt = field(
        default_factory=lambda: CommandReceipt(CommandStatus.ACKNOWLEDGED)
    )
    calls: list[tuple[VendorCommand, str, float | None]] = field(default_factory=list)

    def deliver(
        self,
        command: VendorCommand,
        *,
        correlation_id: str,
        timeout: float | None = None,
    ) -> CommandReceipt:
        self.calls.append((command, correlation_id, timeout))
        return self.receipt


@dataclass(slots=True)
class FailingEndpoint:
    endpoint_id: str
    vendor: str

    def deliver(
        self,
        command: VendorCommand,
        *,
        correlation_id: str,
        timeout: float | None = None,
    ) -> CommandReceipt:
        raise TimeoutError("controller unavailable")


@dataclass(slots=True)
class InvalidReceiptEndpoint:
    endpoint_id: str
    vendor: str

    def deliver(
        self,
        command: VendorCommand,
        *,
        correlation_id: str,
        timeout: float | None = None,
    ) -> CommandReceipt:
        return object()  # type: ignore[return-value]


def command(vendor: str = "pentair") -> VendorCommand:
    return VendorCommand(
        vendor=vendor,
        operation="pump.start",
        target="filter_pump",
    )


def test_registry_registers_and_resolves_endpoint_by_stable_id() -> None:
    registry = EndpointRegistry()
    endpoint = RecordingEndpoint("main-controller", "pentair")

    registry.register(endpoint)

    assert registry.get("main-controller") is endpoint
    assert registry.all() == (endpoint,)


def test_registry_rejects_duplicate_endpoint_id() -> None:
    registry = EndpointRegistry()
    registry.register(RecordingEndpoint("main-controller", "pentair"))

    with pytest.raises(DuplicateEndpointError, match="main-controller"):
        registry.register(RecordingEndpoint("main-controller", "pentair"))


def test_registry_can_replace_endpoint_without_creating_second_route() -> None:
    registry = EndpointRegistry()
    original = RecordingEndpoint("main-controller", "pentair")
    replacement = RecordingEndpoint("main-controller", "pentair")
    registry.register(original)

    registry.replace(replacement)

    assert registry.get("main-controller") is replacement
    assert registry.all() == (replacement,)


def test_registry_unregisters_endpoint() -> None:
    registry = EndpointRegistry()
    endpoint = RecordingEndpoint("main-controller", "pentair")
    registry.register(endpoint)

    removed = registry.unregister("main-controller")

    assert removed is endpoint
    with pytest.raises(EndpointNotFoundError, match="main-controller"):
        registry.get("main-controller")


def test_registry_rejects_blank_endpoint_identity_and_vendor() -> None:
    registry = EndpointRegistry()

    with pytest.raises(ValueError, match="endpoint_id"):
        registry.register(RecordingEndpoint("  ", "pentair"))
    with pytest.raises(ValueError, match="vendor"):
        registry.register(RecordingEndpoint("main-controller", "  "))


def test_gateway_routes_command_and_propagates_delivery_context() -> None:
    endpoint = RecordingEndpoint("main-controller", "pentair")
    registry = EndpointRegistry()
    registry.register(endpoint)
    gateway = VendorCommandGateway(registry)
    vendor_command = command()

    result = gateway.deliver(
        "main-controller",
        vendor_command,
        correlation_id="operation-123",
        timeout=2.5,
    )

    assert endpoint.calls == [(vendor_command, "operation-123", 2.5)]
    assert result.endpoint_id == "main-controller"
    assert result.correlation_id == "operation-123"
    assert result.command is vendor_command
    assert result.receipt is endpoint.receipt
    assert result.status is CommandStatus.ACKNOWLEDGED
    assert result.accepted


def test_gateway_vendor_comparison_is_case_and_whitespace_insensitive() -> None:
    endpoint = RecordingEndpoint("main-controller", " Pentair ")
    registry = EndpointRegistry()
    registry.register(endpoint)
    gateway = VendorCommandGateway(registry)

    result = gateway.deliver(
        "main-controller",
        command("PENTAIR"),
        correlation_id="operation-123",
    )

    assert result.accepted


def test_gateway_rejects_endpoint_vendor_mismatch_before_delivery() -> None:
    endpoint = RecordingEndpoint("main-controller", "pentair")
    registry = EndpointRegistry()
    registry.register(endpoint)
    gateway = VendorCommandGateway(registry)

    with pytest.raises(EndpointVendorMismatchError) as error:
        gateway.deliver(
            "main-controller",
            command("hayward"),
            correlation_id="operation-123",
        )

    assert error.value.endpoint_id == "main-controller"
    assert error.value.expected == "pentair"
    assert error.value.actual == "hayward"
    assert endpoint.calls == []


def test_gateway_propagates_missing_endpoint_as_routing_failure() -> None:
    gateway = VendorCommandGateway(EndpointRegistry())

    with pytest.raises(EndpointNotFoundError, match="missing-controller"):
        gateway.deliver(
            "missing-controller",
            command(),
            correlation_id="operation-123",
        )


def test_gateway_wraps_endpoint_exception_with_delivery_context() -> None:
    registry = EndpointRegistry()
    registry.register(FailingEndpoint("main-controller", "pentair"))
    gateway = VendorCommandGateway(registry)

    with pytest.raises(EndpointDeliveryError) as error:
        gateway.deliver(
            "main-controller",
            command(),
            correlation_id="operation-123",
        )

    assert error.value.endpoint_id == "main-controller"
    assert error.value.correlation_id == "operation-123"
    assert isinstance(error.value.cause, TimeoutError)
    assert isinstance(error.value.__cause__, TimeoutError)


def test_gateway_rejects_invalid_endpoint_return_type() -> None:
    registry = EndpointRegistry()
    registry.register(InvalidReceiptEndpoint("main-controller", "pentair"))
    gateway = VendorCommandGateway(registry)

    with pytest.raises(EndpointDeliveryError) as error:
        gateway.deliver(
            "main-controller",
            command(),
            correlation_id="operation-123",
        )

    assert isinstance(error.value.cause, TypeError)


def test_gateway_requires_explicit_nonblank_routing_and_correlation() -> None:
    endpoint = RecordingEndpoint("main-controller", "pentair")
    registry = EndpointRegistry()
    registry.register(endpoint)
    gateway = VendorCommandGateway(registry)

    with pytest.raises(ValueError, match="endpoint_id"):
        gateway.deliver(" ", command(), correlation_id="operation-123")
    with pytest.raises(ValueError, match="correlation_id"):
        gateway.deliver("main-controller", command(), correlation_id=" ")

    assert endpoint.calls == []


def test_rejected_receipt_remains_distinct_from_delivery_exception() -> None:
    endpoint = RecordingEndpoint(
        "main-controller",
        "pentair",
        receipt=CommandReceipt(CommandStatus.REJECTED, message="controller denied command"),
    )
    registry = EndpointRegistry()
    registry.register(endpoint)
    gateway = VendorCommandGateway(registry)

    result = gateway.deliver(
        "main-controller",
        command(),
        correlation_id="operation-123",
    )

    assert result.status is CommandStatus.REJECTED
    assert not result.accepted
    assert result.receipt.message == "controller denied command"
