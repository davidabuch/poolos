from __future__ import annotations

from dataclasses import FrozenInstanceError
from types import SimpleNamespace

import pytest

from poolos.integration import VendorCommand
from poolos.transport_delivery_gateway import (
    TransportDeliveryGateway,
    TransportDeliveryGatewayDisposition,
    TransportDeliveryGatewayReason,
    TransportRoute,
)
from poolos.vendor_translation_boundary import (
    VendorTranslatedStep,
    VendorTranslationBoundaryResult,
    VendorTranslationDisposition,
    VendorTranslationReason,
)


def _translation_result(
    *,
    disposition: VendorTranslationDisposition = VendorTranslationDisposition.TRANSLATED,
) -> VendorTranslationBoundaryResult:
    dispatch_result = SimpleNamespace(result_id="dispatch-result-a")
    translated_steps = ()
    reason = VendorTranslationReason.DISPATCH_NOT_READY
    if disposition is VendorTranslationDisposition.TRANSLATED:
        reason = VendorTranslationReason.DISPATCH_TRANSLATED
        translated_steps = (
            VendorTranslatedStep(
                translation_id="translation-step-1",
                step_id="plan-a:step:1",
                sequence=1,
                operation_id="operation-1",
                commands=(
                    VendorCommand(
                        vendor="pentair",
                        operation="set_pump_speed",
                        target="pump-main",
                        parameters={"rpm": 1800},
                    ),
                    VendorCommand(
                        vendor="pentair",
                        operation="start_pump",
                        target="pump-main",
                    ),
                ),
            ),
            VendorTranslatedStep(
                translation_id="translation-step-2",
                step_id="plan-a:step:2",
                sequence=2,
                operation_id="operation-2",
                commands=(
                    VendorCommand(
                        vendor="home_assistant",
                        operation="turn_on",
                        target="switch.pool_light",
                    ),
                ),
            ),
        )
    return VendorTranslationBoundaryResult(
        result_id="translation-result-a",
        disposition=disposition,
        reason=reason,
        dispatch_result=dispatch_result,  # type: ignore[arg-type]
        translated_steps=translated_steps,
        provenance={
            "source_execution_plan_id": "plan-a",
            "source_decision_id": "decision-a",
            "source_context_id": "context-a",
            "source_correlation_id": "correlation-a",
        },
    )


def _resolver(command: VendorCommand) -> TransportRoute:
    if command.vendor == "home_assistant":
        return TransportRoute(
            transport="home_assistant_service",
            endpoint="home-assistant-primary",
            adapter="home_assistant",
        )
    return TransportRoute(
        transport="rest",
        endpoint="pentair-local",
        adapter="pentair",
    )


def test_translated_commands_become_ordered_delivery_requests() -> None:
    result = TransportDeliveryGateway().prepare(_translation_result(), _resolver)

    assert result.disposition is TransportDeliveryGatewayDisposition.PREPARED
    assert result.reason is TransportDeliveryGatewayReason.DELIVERY_REQUESTS_PREPARED
    assert [request.sequence for request in result.delivery_requests] == [1, 2, 3]
    assert [request.command.operation for request in result.delivery_requests] == [
        "set_pump_speed",
        "start_pump",
        "turn_on",
    ]
    assert [request.route.adapter for request in result.delivery_requests] == [
        "pentair",
        "pentair",
        "home_assistant",
    ]


def test_delivery_identity_is_deterministic() -> None:
    translation = _translation_result()
    first = TransportDeliveryGateway().prepare(translation, _resolver)
    second = TransportDeliveryGateway().prepare(translation, _resolver)

    assert first.result_id == second.result_id
    assert [request.delivery_request_id for request in first.delivery_requests] == [
        request.delivery_request_id for request in second.delivery_requests
    ]


def test_provenance_preserves_upstream_identities() -> None:
    result = TransportDeliveryGateway().prepare(_translation_result(), _resolver)

    assert result.provenance["source_vendor_translation_result_id"] == "translation-result-a"
    assert result.provenance["source_execution_plan_id"] == "plan-a"
    assert result.provenance["source_decision_id"] == "decision-a"
    assert result.provenance["source_context_id"] == "context-a"
    assert result.delivery_requests[0].provenance["source_correlation_id"] == "correlation-a"


def test_non_translated_result_is_rejected() -> None:
    result = TransportDeliveryGateway().prepare(
        _translation_result(disposition=VendorTranslationDisposition.REJECTED),
        _resolver,
    )

    assert result.disposition is TransportDeliveryGatewayDisposition.REJECTED
    assert result.reason is TransportDeliveryGatewayReason.TRANSLATION_NOT_ACCEPTED
    assert not result.delivery_requests


def test_invalid_route_return_is_rejected_without_partial_requests() -> None:
    result = TransportDeliveryGateway().prepare(
        _translation_result(),
        lambda command: object(),  # type: ignore[return-value]
    )

    assert result.disposition is TransportDeliveryGatewayDisposition.REJECTED
    assert result.reason is TransportDeliveryGatewayReason.TRANSPORT_ROUTE_INVALID
    assert not result.delivery_requests
    assert result.failure_translation_id == "translation-step-1"


def test_resolver_exception_is_recorded_without_partial_requests() -> None:
    def resolver(command: VendorCommand) -> TransportRoute:
        if command.operation == "start_pump":
            raise LookupError("transport unavailable")
        return _resolver(command)

    result = TransportDeliveryGateway().prepare(_translation_result(), resolver)

    assert result.disposition is TransportDeliveryGatewayDisposition.REJECTED
    assert result.reason is TransportDeliveryGatewayReason.TRANSPORT_RESOLUTION_FAILED
    assert not result.delivery_requests
    assert result.failure_detail == "LookupError:transport unavailable"


def test_transport_route_rejects_empty_fields() -> None:
    with pytest.raises(ValueError, match="transport"):
        TransportRoute(transport="", endpoint="endpoint", adapter="adapter")


def test_result_and_provenance_are_immutable() -> None:
    result = TransportDeliveryGateway().prepare(_translation_result(), _resolver)

    with pytest.raises(FrozenInstanceError):
        result.result_id = "changed"  # type: ignore[misc]
    with pytest.raises(TypeError):
        result.provenance["changed"] = "yes"  # type: ignore[index]
    with pytest.raises(TypeError):
        result.delivery_requests[0].provenance["changed"] = "yes"  # type: ignore[index]


def test_empty_boundary_name_is_rejected() -> None:
    with pytest.raises(ValueError, match="boundary_name"):
        TransportDeliveryGateway(boundary_name="")
