"""Deterministic normalization of Home Assistant delivery acknowledgements.

Epic 10.17B converts one Home Assistant transport-adapter result into immutable
canonical acknowledgement evidence. It performs no retry, backoff, state
reconciliation, network operation, Home Assistant call, or physical actuation.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from hashlib import sha256
import json
from types import MappingProxyType
from typing import Any, Mapping

from .home_assistant_transport_adapter import (
    HomeAssistantDeliveryDisposition,
    HomeAssistantDeliveryResult,
)


def _require_aware(value: datetime, field_name: str) -> None:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{field_name} must be timezone-aware")


def _canonical_json(value: object) -> str:
    return json.dumps(
        value,
        ensure_ascii=True,
        separators=(",", ":"),
        sort_keys=True,
    )


def _derived_id(prefix: str, payload: Mapping[str, object]) -> str:
    canonical = _canonical_json(dict(sorted(payload.items())))
    return prefix + sha256(canonical.encode("utf-8")).hexdigest()[:24]


class HomeAssistantAcknowledgementDisposition(str, Enum):
    """Canonical outcome of one Home Assistant delivery acknowledgement."""

    ACKNOWLEDGED = "acknowledged"
    FAILED = "failed"
    TIMED_OUT = "timed_out"
    UNAVAILABLE = "unavailable"
    REJECTED = "rejected"


class HomeAssistantAcknowledgementReason(str, Enum):
    """Stable machine-readable acknowledgement outcome reasons."""

    DELIVERY_ACKNOWLEDGED = "delivery_acknowledged"
    DELIVERY_FAILED = "delivery_failed"
    DELIVERY_TIMED_OUT = "delivery_timed_out"
    HOME_ASSISTANT_UNAVAILABLE = "home_assistant_unavailable"
    DELIVERY_NOT_ACCEPTED = "delivery_not_accepted"
    DELIVERY_EVIDENCE_INVALID = "delivery_evidence_invalid"
    ACKNOWLEDGEMENT_INVALID = "acknowledgement_invalid"


@dataclass(frozen=True, slots=True)
class HomeAssistantAcknowledgementRequest:
    """Explicit acknowledgement evidence for one adapter delivery result."""

    delivery_result: HomeAssistantDeliveryResult
    observed_at: datetime
    outcome: str | None = None
    detail: str | None = None
    metadata: Mapping[str, str] = field(default_factory=dict)

    def __post_init__(self) -> None:
        _require_aware(self.observed_at, "observed_at")
        if self.outcome is not None and not self.outcome.strip():
            raise ValueError("outcome must not be empty when provided")
        if self.detail is not None and not self.detail.strip():
            raise ValueError("detail must not be empty when provided")
        object.__setattr__(self, "metadata", MappingProxyType(dict(self.metadata)))


@dataclass(frozen=True, slots=True)
class HomeAssistantAcknowledgementResult:
    """Immutable canonical acknowledgement evidence."""

    acknowledgement_id: str
    disposition: HomeAssistantAcknowledgementDisposition
    reason: HomeAssistantAcknowledgementReason
    observed_at: datetime
    delivery_result: HomeAssistantDeliveryResult
    detail: str | None = None
    raw_acknowledgement: Mapping[str, Any] = field(default_factory=dict)
    provenance: Mapping[str, str] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not self.acknowledgement_id.strip():
            raise ValueError("acknowledgement_id must not be empty")
        _require_aware(self.observed_at, "observed_at")
        if self.disposition is HomeAssistantAcknowledgementDisposition.ACKNOWLEDGED:
            if self.reason is not HomeAssistantAcknowledgementReason.DELIVERY_ACKNOWLEDGED:
                raise ValueError("acknowledged result requires delivery-acknowledged reason")
            if self.detail is not None:
                raise ValueError("acknowledged result cannot contain failure detail")
        elif self.detail is None:
            raise ValueError("non-acknowledged result requires detail")
        if self.detail is not None and not self.detail.strip():
            raise ValueError("detail must not be empty when provided")
        object.__setattr__(
            self,
            "raw_acknowledgement",
            MappingProxyType(dict(self.raw_acknowledgement)),
        )
        object.__setattr__(self, "provenance", MappingProxyType(dict(self.provenance)))


@dataclass(frozen=True, slots=True)
class HomeAssistantDeliveryAcknowledgement:
    """Normalize one adapter result without retrying or reconciling state."""

    boundary_name: str = "poolos.home_assistant_delivery_acknowledgement"

    def __post_init__(self) -> None:
        if not self.boundary_name.strip():
            raise ValueError("boundary_name must not be empty")

    def normalize(
        self,
        request: HomeAssistantAcknowledgementRequest,
    ) -> HomeAssistantAcknowledgementResult:
        """Return canonical acknowledgement evidence for one delivery result."""

        delivery = request.delivery_result
        if not isinstance(delivery, HomeAssistantDeliveryResult):
            return self._result(
                request,
                disposition=HomeAssistantAcknowledgementDisposition.REJECTED,
                reason=HomeAssistantAcknowledgementReason.DELIVERY_EVIDENCE_INVALID,
                detail="delivery_result_must_be_home_assistant_delivery_result",
            )

        if delivery.disposition is HomeAssistantDeliveryDisposition.REJECTED:
            return self._result(
                request,
                disposition=HomeAssistantAcknowledgementDisposition.REJECTED,
                reason=HomeAssistantAcknowledgementReason.DELIVERY_NOT_ACCEPTED,
                detail=delivery.failure_detail or "delivery_rejected",
            )

        if delivery.disposition is HomeAssistantDeliveryDisposition.FAILED:
            return self._result(
                request,
                disposition=HomeAssistantAcknowledgementDisposition.FAILED,
                reason=HomeAssistantAcknowledgementReason.DELIVERY_FAILED,
                detail=delivery.failure_detail or "delivery_failed",
            )

        if delivery.service_call is None:
            return self._result(
                request,
                disposition=HomeAssistantAcknowledgementDisposition.REJECTED,
                reason=HomeAssistantAcknowledgementReason.DELIVERY_EVIDENCE_INVALID,
                detail="delivered_result_missing_service_call",
            )

        outcome = self._resolve_outcome(request, delivery.acknowledgement)
        mapping = {
            "success": (
                HomeAssistantAcknowledgementDisposition.ACKNOWLEDGED,
                HomeAssistantAcknowledgementReason.DELIVERY_ACKNOWLEDGED,
                None,
            ),
            "failed": (
                HomeAssistantAcknowledgementDisposition.FAILED,
                HomeAssistantAcknowledgementReason.DELIVERY_FAILED,
                request.detail or "home_assistant_reported_failure",
            ),
            "timeout": (
                HomeAssistantAcknowledgementDisposition.TIMED_OUT,
                HomeAssistantAcknowledgementReason.DELIVERY_TIMED_OUT,
                request.detail or "home_assistant_delivery_timed_out",
            ),
            "unavailable": (
                HomeAssistantAcknowledgementDisposition.UNAVAILABLE,
                HomeAssistantAcknowledgementReason.HOME_ASSISTANT_UNAVAILABLE,
                request.detail or "home_assistant_unavailable",
            ),
        }
        resolved = mapping.get(outcome)
        if resolved is None:
            return self._result(
                request,
                disposition=HomeAssistantAcknowledgementDisposition.REJECTED,
                reason=HomeAssistantAcknowledgementReason.ACKNOWLEDGEMENT_INVALID,
                detail=f"unsupported_acknowledgement_outcome:{outcome}",
            )

        disposition, reason, detail = resolved
        return self._result(
            request,
            disposition=disposition,
            reason=reason,
            detail=detail,
        )

    @staticmethod
    def _resolve_outcome(
        request: HomeAssistantAcknowledgementRequest,
        acknowledgement: Mapping[str, Any],
    ) -> str:
        if request.outcome is not None:
            return request.outcome.strip().lower()
        raw = acknowledgement.get("outcome", acknowledgement.get("status", "success"))
        return str(raw).strip().lower()

    def _result(
        self,
        request: HomeAssistantAcknowledgementRequest,
        *,
        disposition: HomeAssistantAcknowledgementDisposition,
        reason: HomeAssistantAcknowledgementReason,
        detail: str | None = None,
    ) -> HomeAssistantAcknowledgementResult:
        delivery = request.delivery_result
        raw_acknowledgement = (
            dict(delivery.acknowledgement)
            if isinstance(delivery, HomeAssistantDeliveryResult)
            else {}
        )
        acknowledgement_id = _derived_id(
            "home-assistant-acknowledgement-",
            {
                "boundary_name": self.boundary_name,
                "delivery_result_id": getattr(delivery, "result_id", "invalid"),
                "detail": detail or "",
                "disposition": disposition.value,
                "observed_at": request.observed_at.isoformat(),
                "raw_acknowledgement": raw_acknowledgement,
                "reason": reason.value,
            },
        )
        provenance = {
            **(
                dict(delivery.provenance)
                if isinstance(delivery, HomeAssistantDeliveryResult)
                else {}
            ),
            **dict(request.metadata),
            "home_assistant_delivery_acknowledgement": self.boundary_name,
            "home_assistant_acknowledgement_id": acknowledgement_id,
            "home_assistant_acknowledgement_disposition": disposition.value,
            "home_assistant_acknowledgement_reason": reason.value,
            "home_assistant_acknowledgement_observed_at": request.observed_at.isoformat(),
            "source_home_assistant_delivery_result_id": getattr(
                delivery, "result_id", ""
            ),
            "source_home_assistant_service_call_id": (
                delivery.service_call.service_call_id
                if isinstance(delivery, HomeAssistantDeliveryResult)
                and delivery.service_call is not None
                else ""
            ),
            "source_transport_delivery_request_id": (
                delivery.delivery_request.delivery_request_id
                if isinstance(delivery, HomeAssistantDeliveryResult)
                else ""
            ),
            "source_correlation_id": (
                delivery.delivery_request.correlation_id or ""
                if isinstance(delivery, HomeAssistantDeliveryResult)
                else ""
            ),
            "detail": detail or "",
        }
        return HomeAssistantAcknowledgementResult(
            acknowledgement_id=acknowledgement_id,
            disposition=disposition,
            reason=reason,
            observed_at=request.observed_at,
            delivery_result=delivery,
            detail=detail,
            raw_acknowledgement=raw_acknowledgement,
            provenance=provenance,
        )
