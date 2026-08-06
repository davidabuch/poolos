"""Build and optionally record deterministic execution receipts."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from hashlib import sha256
import json
from typing import Mapping

from .execution_receipt import (
    ExecutionReceipt,
    ExecutionReceiptDisposition,
    ExecutionReceiptRecorder,
)
from .home_assistant_delivery_acknowledgement import (
    HomeAssistantAcknowledgementDisposition,
    HomeAssistantAcknowledgementResult,
)


def _derived_id(prefix: str, payload: Mapping[str, object]) -> str:
    canonical = json.dumps(dict(sorted(payload.items())), sort_keys=True, separators=(",", ":"), ensure_ascii=True)
    return prefix + sha256(canonical.encode("utf-8")).hexdigest()[:24]


@dataclass(frozen=True, slots=True)
class ExecutionReceiptBuilder:
    boundary_name: str = "poolos.execution_receipt_builder"

    def __post_init__(self) -> None:
        if not self.boundary_name.strip():
            raise ValueError("boundary_name must not be empty")

    def build(
        self,
        acknowledgement: HomeAssistantAcknowledgementResult,
        *,
        recorded_at: datetime,
        recorder: ExecutionReceiptRecorder | None = None,
    ) -> ExecutionReceipt:
        if recorded_at.tzinfo is None or recorded_at.utcoffset() is None:
            raise ValueError("recorded_at must be timezone-aware")
        if not isinstance(acknowledgement, HomeAssistantAcknowledgementResult):
            raise TypeError("acknowledgement must be HomeAssistantAcknowledgementResult")

        delivery = acknowledgement.delivery_result
        request = delivery.delivery_request
        service_call = delivery.service_call
        disposition = {
            HomeAssistantAcknowledgementDisposition.ACKNOWLEDGED: ExecutionReceiptDisposition.COMPLETED,
            HomeAssistantAcknowledgementDisposition.FAILED: ExecutionReceiptDisposition.FAILED,
            HomeAssistantAcknowledgementDisposition.TIMED_OUT: ExecutionReceiptDisposition.TIMED_OUT,
            HomeAssistantAcknowledgementDisposition.UNAVAILABLE: ExecutionReceiptDisposition.UNAVAILABLE,
            HomeAssistantAcknowledgementDisposition.REJECTED: ExecutionReceiptDisposition.REJECTED,
        }[acknowledgement.disposition]
        receipt_id = _derived_id(
            "execution-receipt-",
            {
                "acknowledgement_id": acknowledgement.acknowledgement_id,
                "boundary_name": self.boundary_name,
                "delivery_request_id": request.delivery_request_id,
                "disposition": disposition.value,
                "recorded_at": recorded_at.isoformat(),
            },
        )
        receipt = ExecutionReceipt(
            receipt_id=receipt_id,
            disposition=disposition,
            recorded_at=recorded_at,
            acknowledgement_id=acknowledgement.acknowledgement_id,
            delivery_result_id=delivery.result_id,
            delivery_request_id=request.delivery_request_id,
            service_call_id=service_call.service_call_id if service_call is not None else None,
            correlation_id=request.correlation_id,
            detail=acknowledgement.detail,
            raw_acknowledgement=acknowledgement.raw_acknowledgement,
            provenance={
                **dict(acknowledgement.provenance),
                "execution_receipt_builder": self.boundary_name,
                "execution_receipt_id": receipt_id,
                "execution_receipt_disposition": disposition.value,
                "source_home_assistant_acknowledgement_id": acknowledgement.acknowledgement_id,
                "source_home_assistant_delivery_result_id": delivery.result_id,
                "source_transport_delivery_request_id": request.delivery_request_id,
                "source_home_assistant_service_call_id": service_call.service_call_id if service_call is not None else "",
                "source_correlation_id": request.correlation_id or "",
            },
        )
        return recorder.record(receipt) if recorder is not None else receipt
