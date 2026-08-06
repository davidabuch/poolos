"""Post-delivery Home Assistant observation verification boundary.

This boundary consumes a completed execution receipt plus explicit Home Assistant
state snapshots, translates those snapshots through the existing observation
bridge, and delegates comparison to the canonical execution verification engine.
It performs no polling, retry, reconciliation, command delivery, or actuation.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta
from enum import Enum
from hashlib import sha256
import json
from types import MappingProxyType
from typing import Mapping

from .execution_models import ExecutionStep, VerificationStatus
from .execution_receipt import ExecutionReceipt, ExecutionReceiptDisposition
from .execution_verification import (
    ExecutionVerificationEngine,
    ExecutionVerificationResult,
    VerificationEvidenceDisposition,
)
from .homeassistant.observations import (
    HomeAssistantObservationBridge,
    HomeAssistantObservationProfile,
    HomeAssistantState,
)
from .observations import FreshnessPolicy, ObservationSourceKind, ObservationStore
from .execution_verification import ExecutionVerificationRequest


class PostDeliveryVerificationDisposition(str, Enum):
    """Operational classification of post-delivery verification evidence."""

    VERIFIED = "verified"
    PENDING = "pending"
    MISMATCHED = "mismatched"
    UNAVAILABLE = "unavailable"
    STALE = "stale"
    TIMED_OUT = "timed_out"
    REJECTED = "rejected"


@dataclass(frozen=True, slots=True, kw_only=True)
class PostDeliveryVerificationRequest:
    """Explicit inputs for one post-delivery verification evaluation."""

    receipt: ExecutionReceipt
    plan_id: str
    step: ExecutionStep
    observation_profile: HomeAssistantObservationProfile
    states: tuple[HomeAssistantState, ...]
    evaluated_at: datetime
    timeout: timedelta
    freshness_policy: FreshnessPolicy
    metadata: Mapping[str, str] = field(default_factory=dict)

    def __post_init__(self) -> None:
        plan_id = self.plan_id.strip()
        if not plan_id:
            raise ValueError("plan_id must not be empty")
        object.__setattr__(self, "plan_id", plan_id)
        if self.evaluated_at.tzinfo is None:
            raise ValueError("evaluated_at must be timezone-aware")
        if self.timeout < timedelta(0):
            raise ValueError("timeout must not be negative")
        states = tuple(self.states)
        entity_ids = [state.entity_id for state in states]
        if len(entity_ids) != len(set(entity_ids)):
            raise ValueError("states must contain unique entity IDs")
        object.__setattr__(self, "states", states)
        object.__setattr__(self, "metadata", MappingProxyType(dict(self.metadata)))


@dataclass(frozen=True, slots=True, kw_only=True)
class PostDeliveryVerificationResult:
    """Immutable post-delivery verification boundary result."""

    result_id: str
    disposition: PostDeliveryVerificationDisposition
    evaluated_at: datetime
    receipt_id: str
    plan_id: str
    step_id: str
    reason: str
    verification: ExecutionVerificationResult | None
    provenance: Mapping[str, str] = field(default_factory=dict)
    schema_version: int = 1

    def __post_init__(self) -> None:
        for name in ("result_id", "receipt_id", "plan_id", "step_id", "reason"):
            value = getattr(self, name).strip()
            if not value:
                raise ValueError(f"{name} must not be empty")
            object.__setattr__(self, name, value)
        if self.evaluated_at.tzinfo is None:
            raise ValueError("evaluated_at must be timezone-aware")
        if self.schema_version < 1:
            raise ValueError("schema_version must be at least 1")
        if self.disposition is PostDeliveryVerificationDisposition.REJECTED:
            if self.verification is not None:
                raise ValueError("rejected result cannot contain verification evidence")
        elif self.verification is None:
            raise ValueError("non-rejected result requires verification evidence")
        object.__setattr__(self, "provenance", MappingProxyType(dict(self.provenance)))

    @property
    def terminal(self) -> bool:
        return self.disposition in {
            PostDeliveryVerificationDisposition.VERIFIED,
            PostDeliveryVerificationDisposition.MISMATCHED,
            PostDeliveryVerificationDisposition.TIMED_OUT,
            PostDeliveryVerificationDisposition.REJECTED,
        }


@dataclass(frozen=True, slots=True)
class PostDeliveryObservationVerifier:
    """Gate canonical verification on successful delivery evidence."""

    boundary_name: str = "poolos.post_delivery_observation_verification"
    verification_engine: ExecutionVerificationEngine = field(
        default_factory=ExecutionVerificationEngine
    )

    def __post_init__(self) -> None:
        if not self.boundary_name.strip():
            raise ValueError("boundary_name must not be empty")

    def evaluate(
        self, request: PostDeliveryVerificationRequest
    ) -> PostDeliveryVerificationResult:
        if request.receipt.disposition is not ExecutionReceiptDisposition.COMPLETED:
            return self._result(
                request,
                disposition=PostDeliveryVerificationDisposition.REJECTED,
                reason="delivery_receipt_not_completed",
                verification=None,
            )

        receipt_step_id = request.receipt.provenance.get("source_execution_step_id")
        if receipt_step_id and receipt_step_id != request.step.step_id:
            return self._result(
                request,
                disposition=PostDeliveryVerificationDisposition.REJECTED,
                reason="receipt_step_identity_mismatch",
                verification=None,
            )
        receipt_plan_id = request.receipt.provenance.get("source_execution_plan_id")
        if receipt_plan_id and receipt_plan_id != request.plan_id:
            return self._result(
                request,
                disposition=PostDeliveryVerificationDisposition.REJECTED,
                reason="receipt_plan_identity_mismatch",
                verification=None,
            )

        store = ObservationStore()
        bridge = HomeAssistantObservationBridge(request.observation_profile, store)
        bridge.ingest_many(request.states)
        verification = self.verification_engine.verify(
            ExecutionVerificationRequest(
                plan_id=request.plan_id,
                step=request.step,
                observations=store,
                verification_started_at=request.receipt.recorded_at,
                evaluated_at=request.evaluated_at,
                timeout=request.timeout,
                freshness_policy=request.freshness_policy,
                source_kind=ObservationSourceKind.LIVE,
                metadata={
                    **dict(request.metadata),
                    "source_execution_receipt_id": request.receipt.receipt_id,
                },
            )
        )
        disposition, reason = _classify(verification)
        return self._result(
            request,
            disposition=disposition,
            reason=reason,
            verification=verification,
        )

    def _result(
        self,
        request: PostDeliveryVerificationRequest,
        *,
        disposition: PostDeliveryVerificationDisposition,
        reason: str,
        verification: ExecutionVerificationResult | None,
    ) -> PostDeliveryVerificationResult:
        payload = {
            "boundary_name": self.boundary_name,
            "receipt_id": request.receipt.receipt_id,
            "plan_id": request.plan_id,
            "step_id": request.step.step_id,
            "evaluated_at": request.evaluated_at.isoformat(),
            "disposition": disposition.value,
            "reason": reason,
            "verification_id": verification.verification_id if verification else "",
        }
        canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"))
        result_id = "post-delivery-verification-" + sha256(
            canonical.encode("utf-8")
        ).hexdigest()[:24]
        return PostDeliveryVerificationResult(
            result_id=result_id,
            disposition=disposition,
            evaluated_at=request.evaluated_at,
            receipt_id=request.receipt.receipt_id,
            plan_id=request.plan_id,
            step_id=request.step.step_id,
            reason=reason,
            verification=verification,
            provenance={
                **dict(request.receipt.provenance),
                "post_delivery_verification_boundary": self.boundary_name,
                "post_delivery_verification_result_id": result_id,
                "source_execution_receipt_id": request.receipt.receipt_id,
                "source_execution_verification_id": (
                    verification.verification_id if verification else ""
                ),
                "source_correlation_id": request.receipt.correlation_id or "",
            },
        )


def _classify(
    verification: ExecutionVerificationResult,
) -> tuple[PostDeliveryVerificationDisposition, str]:
    if verification.status is VerificationStatus.VERIFIED:
        return PostDeliveryVerificationDisposition.VERIFIED, "expected_state_observed"
    if verification.status is VerificationStatus.TIMED_OUT:
        return (
            PostDeliveryVerificationDisposition.TIMED_OUT,
            "verification_deadline_reached",
        )
    dispositions = {item.disposition for item in verification.evidence}
    if VerificationEvidenceDisposition.MISMATCHED in dispositions:
        return PostDeliveryVerificationDisposition.MISMATCHED, "observed_state_mismatch"
    if VerificationEvidenceDisposition.UNUSABLE in dispositions:
        return (
            PostDeliveryVerificationDisposition.UNAVAILABLE,
            "entity_unavailable_or_unusable",
        )
    if VerificationEvidenceDisposition.STALE in dispositions:
        return PostDeliveryVerificationDisposition.STALE, "observation_stale"
    return PostDeliveryVerificationDisposition.PENDING, "observation_evidence_pending"


__all__ = [
    "PostDeliveryObservationVerifier",
    "PostDeliveryVerificationDisposition",
    "PostDeliveryVerificationRequest",
    "PostDeliveryVerificationResult",
]
