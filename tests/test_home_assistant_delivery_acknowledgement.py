from __future__ import annotations

from dataclasses import FrozenInstanceError
from datetime import datetime, timezone
from typing import Any, Mapping

import pytest

from poolos.home_assistant_delivery_acknowledgement import (
    HomeAssistantAcknowledgementDisposition,
    HomeAssistantAcknowledgementReason,
    HomeAssistantAcknowledgementRequest,
    HomeAssistantDeliveryAcknowledgement,
)
from poolos.home_assistant_transport_adapter import HomeAssistantTransportAdapter
from poolos.integration import VendorCommand
from poolos.transport_delivery_gateway import (
    TransportDeliveryRequest,
    TransportRoute,
)

NOW = datetime(2026, 8, 6, 2, 30, tzinfo=timezone.utc)


def _delivery_request() -> TransportDeliveryRequest:
    return TransportDeliveryRequest(
        delivery_request_id="delivery-a",
        sequence=1,
        translation_id="translation-a",
        step_id="step-a",
        operation_id="operation-a",
        command_index=1,
        command=VendorCommand(
            vendor="home_assistant",
            operation="turn_on",
            target="switch.pool_pump",
        ),
        route=TransportRoute(
            transport="home_assistant",
            endpoint="switch.turn_on",
            adapter="home_assistant",
        ),
        correlation_id="correlation-a",
        provenance={"source_execution_plan_id": "plan-a"},
    )


def _delivered(acknowledgement: Mapping[str, Any] | None = None):
    return HomeAssistantTransportAdapter().deliver(
        _delivery_request(),
        lambda call: acknowledgement,
    )


def test_none_acknowledgement_defaults_to_success() -> None:
    result = HomeAssistantDeliveryAcknowledgement().normalize(
        HomeAssistantAcknowledgementRequest(
            delivery_result=_delivered(),
            observed_at=NOW,
        )
    )

    assert result.disposition is HomeAssistantAcknowledgementDisposition.ACKNOWLEDGED
    assert result.reason is HomeAssistantAcknowledgementReason.DELIVERY_ACKNOWLEDGED
    assert result.detail is None


def test_success_status_is_acknowledged() -> None:
    result = HomeAssistantDeliveryAcknowledgement().normalize(
        HomeAssistantAcknowledgementRequest(
            delivery_result=_delivered({"status": "success"}),
            observed_at=NOW,
        )
    )

    assert result.disposition is HomeAssistantAcknowledgementDisposition.ACKNOWLEDGED


@pytest.mark.parametrize(
    ("outcome", "disposition", "reason"),
    [
        (
            "failed",
            HomeAssistantAcknowledgementDisposition.FAILED,
            HomeAssistantAcknowledgementReason.DELIVERY_FAILED,
        ),
        (
            "timeout",
            HomeAssistantAcknowledgementDisposition.TIMED_OUT,
            HomeAssistantAcknowledgementReason.DELIVERY_TIMED_OUT,
        ),
        (
            "unavailable",
            HomeAssistantAcknowledgementDisposition.UNAVAILABLE,
            HomeAssistantAcknowledgementReason.HOME_ASSISTANT_UNAVAILABLE,
        ),
    ],
)
def test_explicit_outcomes_are_normalized(outcome, disposition, reason) -> None:
    result = HomeAssistantDeliveryAcknowledgement().normalize(
        HomeAssistantAcknowledgementRequest(
            delivery_result=_delivered(),
            observed_at=NOW,
            outcome=outcome,
        )
    )

    assert result.disposition is disposition
    assert result.reason is reason
    assert result.detail is not None


def test_acknowledgement_mapping_outcome_is_used() -> None:
    result = HomeAssistantDeliveryAcknowledgement().normalize(
        HomeAssistantAcknowledgementRequest(
            delivery_result=_delivered({"outcome": "timeout"}),
            observed_at=NOW,
        )
    )

    assert result.disposition is HomeAssistantAcknowledgementDisposition.TIMED_OUT


def test_adapter_failure_is_normalized_without_override() -> None:
    def executor(call):
        raise RuntimeError("offline")

    delivery = HomeAssistantTransportAdapter().deliver(_delivery_request(), executor)
    result = HomeAssistantDeliveryAcknowledgement().normalize(
        HomeAssistantAcknowledgementRequest(
            delivery_result=delivery,
            observed_at=NOW,
        )
    )

    assert result.disposition is HomeAssistantAcknowledgementDisposition.FAILED
    assert result.reason is HomeAssistantAcknowledgementReason.DELIVERY_FAILED
    assert "RuntimeError:offline" in (result.detail or "")


def test_unknown_outcome_is_rejected() -> None:
    result = HomeAssistantDeliveryAcknowledgement().normalize(
        HomeAssistantAcknowledgementRequest(
            delivery_result=_delivered(),
            observed_at=NOW,
            outcome="mystery",
        )
    )

    assert result.disposition is HomeAssistantAcknowledgementDisposition.REJECTED
    assert result.reason is HomeAssistantAcknowledgementReason.ACKNOWLEDGEMENT_INVALID


def test_identity_is_deterministic() -> None:
    request = HomeAssistantAcknowledgementRequest(
        delivery_result=_delivered({"status": "success"}),
        observed_at=NOW,
    )

    first = HomeAssistantDeliveryAcknowledgement().normalize(request)
    second = HomeAssistantDeliveryAcknowledgement().normalize(request)

    assert first.acknowledgement_id == second.acknowledgement_id


def test_provenance_preserves_upstream_identities() -> None:
    result = HomeAssistantDeliveryAcknowledgement().normalize(
        HomeAssistantAcknowledgementRequest(
            delivery_result=_delivered(),
            observed_at=NOW,
        )
    )

    assert result.provenance["source_transport_delivery_request_id"] == "delivery-a"
    assert result.provenance["source_correlation_id"] == "correlation-a"
    assert result.provenance["source_execution_plan_id"] == "plan-a"


def test_request_rejects_naive_observed_at() -> None:
    with pytest.raises(ValueError, match="timezone-aware"):
        HomeAssistantAcknowledgementRequest(
            delivery_result=_delivered(),
            observed_at=datetime(2026, 8, 6, 2, 30),
        )


def test_result_and_provenance_are_immutable() -> None:
    result = HomeAssistantDeliveryAcknowledgement().normalize(
        HomeAssistantAcknowledgementRequest(
            delivery_result=_delivered(),
            observed_at=NOW,
        )
    )

    with pytest.raises(FrozenInstanceError):
        result.detail = "changed"  # type: ignore[misc]
    with pytest.raises(TypeError):
        result.provenance["changed"] = "yes"  # type: ignore[index]


def test_empty_boundary_name_is_rejected() -> None:
    with pytest.raises(ValueError, match="boundary_name"):
        HomeAssistantDeliveryAcknowledgement(boundary_name="")
