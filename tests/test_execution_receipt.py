from __future__ import annotations

from dataclasses import FrozenInstanceError
from datetime import datetime, timezone
from typing import cast

import pytest

from poolos.execution_receipt import InMemoryExecutionReceiptRecorder
from poolos.execution_receipt_builder import ExecutionReceiptBuilder
from poolos.home_assistant_delivery_acknowledgement import (
    HomeAssistantAcknowledgementDisposition,
    HomeAssistantAcknowledgementReason,
    HomeAssistantAcknowledgementResult,
)
from poolos.home_assistant_transport_adapter import HomeAssistantDeliveryResult
from poolos.transport_delivery_gateway import TransportDeliveryRequest

NOW = datetime(2026, 8, 5, 20, 0, tzinfo=timezone.utc)


def _ack(disposition: HomeAssistantAcknowledgementDisposition = HomeAssistantAcknowledgementDisposition.ACKNOWLEDGED):
    request = cast(TransportDeliveryRequest, object.__new__(TransportDeliveryRequest))
    object.__setattr__(request, "delivery_request_id", "delivery-a")
    object.__setattr__(request, "correlation_id", "correlation-a")
    delivery = cast(HomeAssistantDeliveryResult, object.__new__(HomeAssistantDeliveryResult))
    object.__setattr__(delivery, "result_id", "delivery-result-a")
    object.__setattr__(delivery, "delivery_request", request)
    object.__setattr__(delivery, "service_call", None)
    detail = None if disposition is HomeAssistantAcknowledgementDisposition.ACKNOWLEDGED else "failure"
    reason = {
        HomeAssistantAcknowledgementDisposition.ACKNOWLEDGED: HomeAssistantAcknowledgementReason.DELIVERY_ACKNOWLEDGED,
        HomeAssistantAcknowledgementDisposition.FAILED: HomeAssistantAcknowledgementReason.DELIVERY_FAILED,
        HomeAssistantAcknowledgementDisposition.TIMED_OUT: HomeAssistantAcknowledgementReason.DELIVERY_TIMED_OUT,
        HomeAssistantAcknowledgementDisposition.UNAVAILABLE: HomeAssistantAcknowledgementReason.HOME_ASSISTANT_UNAVAILABLE,
        HomeAssistantAcknowledgementDisposition.REJECTED: HomeAssistantAcknowledgementReason.ACKNOWLEDGEMENT_INVALID,
    }[disposition]
    return HomeAssistantAcknowledgementResult(
        acknowledgement_id="ack-a",
        disposition=disposition,
        reason=reason,
        observed_at=NOW,
        delivery_result=delivery,
        detail=detail,
        raw_acknowledgement={"outcome": disposition.value},
        provenance={"source_execution_plan_id": "plan-a"},
    )


def test_builds_completed_receipt() -> None:
    receipt = ExecutionReceiptBuilder().build(_ack(), recorded_at=NOW)
    assert receipt.disposition.value == "completed"
    assert receipt.delivery_request_id == "delivery-a"
    assert receipt.provenance["source_execution_plan_id"] == "plan-a"


@pytest.mark.parametrize("value", [
    HomeAssistantAcknowledgementDisposition.FAILED,
    HomeAssistantAcknowledgementDisposition.TIMED_OUT,
    HomeAssistantAcknowledgementDisposition.UNAVAILABLE,
    HomeAssistantAcknowledgementDisposition.REJECTED,
])
def test_maps_non_success_outcomes(value) -> None:
    receipt = ExecutionReceiptBuilder().build(_ack(value), recorded_at=NOW)
    assert receipt.disposition.value == value.value
    assert receipt.detail == "failure"


def test_identity_is_deterministic() -> None:
    builder = ExecutionReceiptBuilder()
    assert builder.build(_ack(), recorded_at=NOW).receipt_id == builder.build(_ack(), recorded_at=NOW).receipt_id


def test_records_append_only() -> None:
    recorder = InMemoryExecutionReceiptRecorder()
    receipt = ExecutionReceiptBuilder().build(_ack(), recorded_at=NOW, recorder=recorder)
    assert recorder.latest is receipt
    assert recorder.receipts == (receipt,)
    with pytest.raises(ValueError, match="duplicate receipt_id"):
        recorder.record(receipt)


def test_receipt_is_immutable() -> None:
    receipt = ExecutionReceiptBuilder().build(_ack(), recorded_at=NOW)
    with pytest.raises(FrozenInstanceError):
        receipt.detail = "changed"  # type: ignore[misc]
    with pytest.raises(TypeError):
        receipt.provenance["changed"] = "yes"  # type: ignore[index]


def test_rejects_naive_time() -> None:
    with pytest.raises(ValueError, match="timezone-aware"):
        ExecutionReceiptBuilder().build(_ack(), recorded_at=datetime(2026, 8, 5, 20, 0))
