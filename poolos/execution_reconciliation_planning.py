"""Deterministic execution reconciliation and recovery planning.

This boundary consumes completed post-delivery verification evidence plus
explicit current policy facts and recommends the next supervisory action. It
never retries commands, generates commands, mutates execution state, contacts
Home Assistant, or actuates equipment.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from hashlib import sha256
import json
from types import MappingProxyType
from typing import Mapping

from .post_delivery_observation_verification import (
    PostDeliveryVerificationDisposition,
    PostDeliveryVerificationResult,
)


class ExecutionReconciliationDisposition(str, Enum):
    """Recommended supervisory response to execution evidence."""

    SATISFIED = "satisfied"
    REEVALUATE = "reevaluate"
    RETRY_RECOMMENDED = "retry_recommended"
    OPERATOR_INTERVENTION_REQUIRED = "operator_intervention_required"
    ABORT = "abort"


@dataclass(frozen=True, slots=True, kw_only=True)
class ExecutionReconciliationRequest:
    """Explicit evidence and policy facts for one reconciliation decision."""

    verification_result: PostDeliveryVerificationResult
    evaluated_at: datetime
    assumptions_current: bool
    retry_allowed: bool
    mismatch_persistent: bool = False
    metadata: Mapping[str, str] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if self.evaluated_at.tzinfo is None or self.evaluated_at.utcoffset() is None:
            raise ValueError("evaluated_at must be timezone-aware")
        if self.evaluated_at < self.verification_result.evaluated_at:
            raise ValueError(
                "evaluated_at cannot precede verification_result.evaluated_at"
            )
        object.__setattr__(self, "metadata", MappingProxyType(dict(self.metadata)))


@dataclass(frozen=True, slots=True, kw_only=True)
class ExecutionReconciliationResult:
    """Immutable recommendation produced without executing recovery."""

    reconciliation_id: str
    disposition: ExecutionReconciliationDisposition
    evaluated_at: datetime
    receipt_id: str
    verification_result_id: str
    plan_id: str
    step_id: str
    reason: str
    provenance: Mapping[str, str] = field(default_factory=dict)
    schema_version: int = 1

    def __post_init__(self) -> None:
        for name in (
            "reconciliation_id",
            "receipt_id",
            "verification_result_id",
            "plan_id",
            "step_id",
            "reason",
        ):
            value = getattr(self, name).strip()
            if not value:
                raise ValueError(f"{name} must not be empty")
            object.__setattr__(self, name, value)
        if self.evaluated_at.tzinfo is None or self.evaluated_at.utcoffset() is None:
            raise ValueError("evaluated_at must be timezone-aware")
        if self.schema_version < 1:
            raise ValueError("schema_version must be at least 1")
        object.__setattr__(self, "provenance", MappingProxyType(dict(self.provenance)))

    @property
    def requires_follow_up(self) -> bool:
        """Return whether a later subsystem or operator must act."""

        return self.disposition is not ExecutionReconciliationDisposition.SATISFIED


@dataclass(frozen=True, slots=True)
class ExecutionReconciliationPlanner:
    """Recommend a next action from immutable verification evidence."""

    boundary_name: str = "poolos.execution_reconciliation_planning"

    def __post_init__(self) -> None:
        if not self.boundary_name.strip():
            raise ValueError("boundary_name must not be empty")

    def evaluate(
        self, request: ExecutionReconciliationRequest
    ) -> ExecutionReconciliationResult:
        verification = request.verification_result
        disposition, reason = self._classify(request)
        payload = {
            "boundary_name": self.boundary_name,
            "verification_result_id": verification.result_id,
            "receipt_id": verification.receipt_id,
            "plan_id": verification.plan_id,
            "step_id": verification.step_id,
            "evaluated_at": request.evaluated_at.isoformat(),
            "assumptions_current": request.assumptions_current,
            "retry_allowed": request.retry_allowed,
            "mismatch_persistent": request.mismatch_persistent,
            "disposition": disposition.value,
            "reason": reason,
        }
        canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"))
        reconciliation_id = "execution-reconciliation-" + sha256(
            canonical.encode("utf-8")
        ).hexdigest()[:24]
        return ExecutionReconciliationResult(
            reconciliation_id=reconciliation_id,
            disposition=disposition,
            evaluated_at=request.evaluated_at,
            receipt_id=verification.receipt_id,
            verification_result_id=verification.result_id,
            plan_id=verification.plan_id,
            step_id=verification.step_id,
            reason=reason,
            provenance={
                **dict(verification.provenance),
                **dict(request.metadata),
                "execution_reconciliation_boundary": self.boundary_name,
                "execution_reconciliation_id": reconciliation_id,
                "source_post_delivery_verification_result_id": verification.result_id,
                "source_execution_receipt_id": verification.receipt_id,
            },
        )

    @staticmethod
    def _classify(
        request: ExecutionReconciliationRequest,
    ) -> tuple[ExecutionReconciliationDisposition, str]:
        disposition = request.verification_result.disposition

        if disposition is PostDeliveryVerificationDisposition.REJECTED:
            return (
                ExecutionReconciliationDisposition.ABORT,
                "verification_evidence_rejected",
            )
        if disposition is PostDeliveryVerificationDisposition.VERIFIED:
            return (
                ExecutionReconciliationDisposition.SATISFIED,
                "expected_state_verified",
            )
        if not request.assumptions_current:
            return (
                ExecutionReconciliationDisposition.REEVALUATE,
                "execution_assumptions_no_longer_current",
            )
        if disposition is PostDeliveryVerificationDisposition.PENDING:
            return (
                ExecutionReconciliationDisposition.REEVALUATE,
                "verification_evidence_still_pending",
            )
        if disposition is PostDeliveryVerificationDisposition.MISMATCHED:
            if request.mismatch_persistent:
                return (
                    ExecutionReconciliationDisposition.OPERATOR_INTERVENTION_REQUIRED,
                    "persistent_observed_state_mismatch",
                )
            return (
                ExecutionReconciliationDisposition.REEVALUATE,
                "new_observed_state_requires_reevaluation",
            )
        if disposition is PostDeliveryVerificationDisposition.UNAVAILABLE:
            return (
                ExecutionReconciliationDisposition.OPERATOR_INTERVENTION_REQUIRED,
                "equipment_observation_unavailable",
            )
        if disposition in {
            PostDeliveryVerificationDisposition.STALE,
            PostDeliveryVerificationDisposition.TIMED_OUT,
        }:
            if request.retry_allowed:
                return (
                    ExecutionReconciliationDisposition.RETRY_RECOMMENDED,
                    "verification_evidence_expired_retry_permitted",
                )
            return (
                ExecutionReconciliationDisposition.OPERATOR_INTERVENTION_REQUIRED,
                "verification_evidence_expired_retry_not_permitted",
            )
        return ExecutionReconciliationDisposition.ABORT, "unsupported_verification_evidence"


__all__ = [
    "ExecutionReconciliationDisposition",
    "ExecutionReconciliationPlanner",
    "ExecutionReconciliationRequest",
    "ExecutionReconciliationResult",
]
