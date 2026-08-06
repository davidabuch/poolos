from __future__ import annotations

from dataclasses import FrozenInstanceError
from typing import cast

import pytest

from poolos.home_assistant_transport_adapter import (
    HomeAssistantDeliveryDisposition,
    HomeAssistantDeliveryReason,
    HomeAssistantServiceCall,
    HomeAssistantTransportAdapter,
)
from poolos.integration import VendorCommand
from poolos.transport_delivery_gateway import (
    TransportDeliveryRequest,
    TransportRoute,
)


def _request(
    *,
    transport: str = "home_assistant",
    adapter: str = "home_assistant",
    endpoint: str = "switch.turn_on",
) -> TransportDeliveryRequest:
    return TransportDeliveryRequest(
        delivery_request_id="delivery-a",
        sequence=1,
        translation_id="translation-a",
        step_id="step-a",
        operation_id="operation-a",
        command_index=1,
        command=VendorCommand(
            vendor="pentair",
            operation="turn_on",
            target="switch.pool_pump",
            parameters={"speed": 1500},
        ),
        route=TransportRoute(
            transport=transport,
            endpoint=endpoint,
            adapter=adapter,
        ),
        correlation_id="correlation-a",
        provenance={"source_execution_plan_id": "plan-a"},
    )


def test_delivers_deterministic_home_assistant_service_call() -> None:
    captured: list[HomeAssistantServiceCall] = []

    def executor(call: HomeAssistantServiceCall):
        captured.append(call)
        return {"accepted": True, "context_id": "ha-context-a"}

    result = HomeAssistantTransportAdapter().deliver(_request(), executor)

    assert result.disposition is HomeAssistantDeliveryDisposition.DELIVERED
    assert result.reason is HomeAssistantDeliveryReason.SERVICE_CALL_DELIVERED
    assert len(captured) == 1
    call = captured[0]
    assert call.domain == "switch"
    assert call.service == "turn_on"
    assert call.target == {"entity_id": "switch.pool_pump"}
    assert call.data["speed"] == 1500
    assert call.data["poolos_vendor"] == "pentair"
    assert call.data["poolos_operation"] == "turn_on"
    assert result.acknowledgement["context_id"] == "ha-context-a"


def test_service_call_identity_is_deterministic() -> None:
    request = _request()
    adapter = HomeAssistantTransportAdapter()

    first = adapter.deliver(request, lambda call: None)
    second = adapter.deliver(request, lambda call: None)

    assert first.result_id == second.result_id
    assert first.service_call is not None
    assert second.service_call is not None
    assert first.service_call.service_call_id == second.service_call.service_call_id


def test_provenance_preserves_upstream_identities() -> None:
    result = HomeAssistantTransportAdapter().deliver(_request(), lambda call: None)

    assert result.provenance["source_transport_delivery_request_id"] == "delivery-a"
    assert result.provenance["source_vendor_step_translation_id"] == "translation-a"
    assert result.provenance["source_execution_step_id"] == "step-a"
    assert result.provenance["source_operation_id"] == "operation-a"
    assert result.provenance["source_correlation_id"] == "correlation-a"
    assert result.provenance["source_execution_plan_id"] == "plan-a"


def test_unsupported_transport_is_rejected_without_executor_call() -> None:
    called = False

    def executor(call: HomeAssistantServiceCall):
        nonlocal called
        called = True
        return None

    result = HomeAssistantTransportAdapter().deliver(
        _request(transport="mqtt"), executor
    )

    assert result.disposition is HomeAssistantDeliveryDisposition.REJECTED
    assert result.reason is HomeAssistantDeliveryReason.TRANSPORT_NOT_SUPPORTED
    assert result.service_call is None
    assert called is False


def test_unsupported_adapter_is_rejected() -> None:
    result = HomeAssistantTransportAdapter().deliver(
        _request(adapter="mqtt_adapter"), lambda call: None
    )

    assert result.disposition is HomeAssistantDeliveryDisposition.REJECTED
    assert result.reason is HomeAssistantDeliveryReason.ADAPTER_NOT_SUPPORTED


@pytest.mark.parametrize("endpoint", ["switch", ".turn_on", "switch.", "a.b.c"])
def test_invalid_endpoint_is_rejected(endpoint: str) -> None:
    result = HomeAssistantTransportAdapter().deliver(
        _request(endpoint=endpoint), lambda call: None
    )

    assert result.disposition is HomeAssistantDeliveryDisposition.REJECTED
    assert result.reason is HomeAssistantDeliveryReason.ENDPOINT_INVALID


def test_empty_endpoint_is_rejected_by_transport_route() -> None:
    with pytest.raises(ValueError, match="endpoint must not be empty"):
        _request(endpoint="")


def test_executor_failure_is_recorded() -> None:
    def executor(call: HomeAssistantServiceCall):
        raise RuntimeError("home assistant unavailable")

    result = HomeAssistantTransportAdapter().deliver(_request(), executor)

    assert result.disposition is HomeAssistantDeliveryDisposition.FAILED
    assert result.reason is HomeAssistantDeliveryReason.EXECUTOR_FAILED
    assert result.service_call is not None
    assert result.failure_detail == "RuntimeError:home assistant unavailable"


def test_invalid_executor_result_is_recorded() -> None:
    result = HomeAssistantTransportAdapter().deliver(
        _request(), cast(object, lambda call: "not-a-mapping")
    )

    assert result.disposition is HomeAssistantDeliveryDisposition.FAILED
    assert result.reason is HomeAssistantDeliveryReason.EXECUTOR_RESULT_INVALID


def test_result_and_nested_mappings_are_immutable() -> None:
    result = HomeAssistantTransportAdapter().deliver(_request(), lambda call: None)

    with pytest.raises(FrozenInstanceError):
        result.result_id = "changed"  # type: ignore[misc]
    with pytest.raises(TypeError):
        result.provenance["changed"] = "yes"  # type: ignore[index]
    assert result.service_call is not None
    with pytest.raises(TypeError):
        result.service_call.data["changed"] = True  # type: ignore[index]


def test_empty_adapter_configuration_is_rejected() -> None:
    with pytest.raises(ValueError, match="transport_name"):
        HomeAssistantTransportAdapter(transport_name="")
