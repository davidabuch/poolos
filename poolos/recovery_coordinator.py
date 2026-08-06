"""Deterministic recovery coordination without recovery execution.

This boundary consumes one execution reconciliation recommendation and explicit
recovery policy. It emits an immutable directive for a later subsystem. It does
not submit reevaluations, queue retries, notify operators, mutate execution
state, contact Home Assistant, or actuate equipment.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from hashlib import sha256
import json
from types import MappingProxyType
from typing import Mapping

from .execution_reconciliation_planning import (
    ExecutionReconciliationDisposition,
    ExecutionReconciliationResult,
)


class RecoveryDirectiveDisposition(str, Enum):
    """Policy-authorized directive for a later recovery subsystem."""

    NO_ACTION = "no_action"
    REQUEST_REEVALUATION = "request_reevaluation"
    QUEUE_RETRY_REQUEST = "queue_retry_request"
    REQUEST_OPERATOR_INTERVENTION = "request_operator_intervention"


@dataclass(frozen=True, slots=True, kw_only=True)
class RecoveryPolicy:
    """Explicit permissions governing recovery directive production."""

    policy_id: str
    allow_reevaluation_request: bool = True
    allow_retry_request: bool = False
    allow_operator_intervention_request: bool = True
    metadata: Mapping[str, str] = field(default_factory=dict)

    def __post_init__(self) -> None:
        policy_id = self.policy_id.strip()
        if not policy_id:
            raise ValueError("policy_id must not be empty")
        object.__setattr__(self, "policy_id", policy_id)
        object.__setattr__(self, "metadata", MappingProxyType(dict(self.metadata)))


@dataclass(frozen=True, slots=True, kw_only=True)
class RecoveryCoordinationRequest:
    """One immutable reconciliation result plus current recovery policy."""

    reconciliation_result: ExecutionReconciliationResult
    policy: RecoveryPolicy
    coordinated_at: datetime
    metadata: Mapping[str, str] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if self.coordinated_at.tzinfo is None or self.coordinated_at.utcoffset() is None:
            raise ValueError("coordinated_at must be timezone-aware")
        if self.coordinated_at < self.reconciliation_result.evaluated_at:
            raise ValueError(
                "coordinated_at cannot precede reconciliation_result.evaluated_at"
            )
        object.__setattr__(self, "metadata", MappingProxyType(dict(self.metadata)))


@dataclass(frozen=True, slots=True, kw_only=True)
class RecoveryDirective:
    """Immutable policy-authorized instruction that performs no action itself."""

    directive_id: str
    disposition: RecoveryDirectiveDisposition
    coordinated_at: datetime
    reconciliation_id: str
    verification_result_id: str
    receipt_id: str
    plan_id: str
    step_id: str
    policy_id: str
    reason: str
    provenance: Mapping[str, str] = field(default_factory=dict)
    schema_version: int = 1

    def __post_init__(self) -> None:
        for name in (
            "directive_id",
            "reconciliation_id",
            "verification_result_id",
            "receipt_id",
            "plan_id",
            "step_id",
            "policy_id",
            "reason",
        ):
            value = getattr(self, name).strip()
            if not value:
                raise ValueError(f"{name} must not be empty")
            object.__setattr__(self, name, value)
        if self.coordinated_at.tzinfo is None or self.coordinated_at.utcoffset() is None:
            raise ValueError("coordinated_at must be timezone-aware")
        if self.schema_version < 1:
            raise ValueError("schema_version must be at least 1")
        object.__setattr__(self, "provenance", MappingProxyType(dict(self.provenance)))

    @property
    def requires_follow_up(self) -> bool:
        """Return whether a later subsystem or operator must act."""

        return self.disposition is not RecoveryDirectiveDisposition.NO_ACTION


@dataclass(frozen=True, slots=True)
class RecoveryCoordinator:
    """Apply explicit recovery policy to reconciliation evidence."""

    boundary_name: str = "poolos.recovery_coordinator"

    def __post_init__(self) -> None:
        if not self.boundary_name.strip():
            raise ValueError("boundary_name must not be empty")

    def coordinate(self, request: RecoveryCoordinationRequest) -> RecoveryDirective:
        reconciliation = request.reconciliation_result
        disposition, reason = self._classify(reconciliation, request.policy)
        payload = {
            "boundary_name": self.boundary_name,
            "reconciliation_id": reconciliation.reconciliation_id,
            "verification_result_id": reconciliation.verification_result_id,
            "receipt_id": reconciliation.receipt_id,
            "plan_id": reconciliation.plan_id,
            "step_id": reconciliation.step_id,
            "policy_id": request.policy.policy_id,
            "coordinated_at": request.coordinated_at.isoformat(),
            "allow_reevaluation_request": request.policy.allow_reevaluation_request,
            "allow_retry_request": request.policy.allow_retry_request,
            "allow_operator_intervention_request": (
                request.policy.allow_operator_intervention_request
            ),
            "disposition": disposition.value,
            "reason": reason,
        }
        canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"))
        directive_id = "recovery-directive-" + sha256(
            canonical.encode("utf-8")
        ).hexdigest()[:24]
        return RecoveryDirective(
            directive_id=directive_id,
            disposition=disposition,
            coordinated_at=request.coordinated_at,
            reconciliation_id=reconciliation.reconciliation_id,
            verification_result_id=reconciliation.verification_result_id,
            receipt_id=reconciliation.receipt_id,
            plan_id=reconciliation.plan_id,
            step_id=reconciliation.step_id,
            policy_id=request.policy.policy_id,
            reason=reason,
            provenance={
                **dict(reconciliation.provenance),
                **dict(request.policy.metadata),
                **dict(request.metadata),
                "recovery_coordinator_boundary": self.boundary_name,
                "recovery_directive_id": directive_id,
                "recovery_policy_id": request.policy.policy_id,
                "source_execution_reconciliation_id": (
                    reconciliation.reconciliation_id
                ),
            },
        )

    @staticmethod
    def _classify(
        reconciliation: ExecutionReconciliationResult,
        policy: RecoveryPolicy,
    ) -> tuple[RecoveryDirectiveDisposition, str]:
        disposition = reconciliation.disposition

        if disposition is ExecutionReconciliationDisposition.SATISFIED:
            return RecoveryDirectiveDisposition.NO_ACTION, "execution_satisfied"
        if disposition is ExecutionReconciliationDisposition.REEVALUATE:
            if policy.allow_reevaluation_request:
                return (
                    RecoveryDirectiveDisposition.REQUEST_REEVALUATION,
                    "reevaluation_authorized_by_policy",
                )
            return RecoveryCoordinator._operator_or_no_action(
                policy, "reevaluation_blocked_by_policy"
            )
        if disposition is ExecutionReconciliationDisposition.RETRY_RECOMMENDED:
            if policy.allow_retry_request:
                return (
                    RecoveryDirectiveDisposition.QUEUE_RETRY_REQUEST,
                    "retry_request_authorized_by_policy",
                )
            return RecoveryCoordinator._operator_or_no_action(
                policy, "retry_request_blocked_by_policy"
            )
        if disposition in {
            ExecutionReconciliationDisposition.OPERATOR_INTERVENTION_REQUIRED,
            ExecutionReconciliationDisposition.ABORT,
        }:
            return RecoveryCoordinator._operator_or_no_action(
                policy,
                "operator_intervention_authorized_by_policy"
                if disposition
                is ExecutionReconciliationDisposition.OPERATOR_INTERVENTION_REQUIRED
                else "aborted_execution_requires_operator_review",
            )
        return RecoveryCoordinator._operator_or_no_action(
            policy, "unsupported_reconciliation_disposition"
        )

    @staticmethod
    def _operator_or_no_action(
        policy: RecoveryPolicy, reason: str
    ) -> tuple[RecoveryDirectiveDisposition, str]:
        if policy.allow_operator_intervention_request:
            return RecoveryDirectiveDisposition.REQUEST_OPERATOR_INTERVENTION, reason
        return (
            RecoveryDirectiveDisposition.NO_ACTION,
            f"{reason}_and_operator_request_blocked",
        )


__all__ = [
    "RecoveryCoordinationRequest",
    "RecoveryCoordinator",
    "RecoveryDirective",
    "RecoveryDirectiveDisposition",
    "RecoveryPolicy",
]
