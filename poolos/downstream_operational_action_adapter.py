"""Deterministic non-hardware adapter boundary for operational actions.

The adapter contract consumes only immutable ``OperationalActionPipelineResult``
objects.  The first implementation handles no-op, reevaluation, and operator
review routes without invoking schedulers, execution systems, vendor gateways,
Home Assistant, or physical equipment.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from hashlib import sha256
import json
from types import MappingProxyType
from typing import Mapping, Protocol

from .operational_action_pipeline import (
    OperationalActionPipelineReason,
    OperationalActionPipelineResult,
    OperationalActionPipelineStatus,
)
from .operational_disposition_orchestrator import OperationalAction, OperationalTarget


class DownstreamOperationalActionOutcome(str, Enum):
    """Terminal outcome emitted by a downstream operational-action adapter."""

    ACCEPTED = "accepted"
    REJECTED = "rejected"
    DEFERRED = "deferred"
    NO_OP = "no_op"


class DownstreamOperationalActionReason(str, Enum):
    """Stable machine-readable reasons for downstream adapter outcomes."""

    OPERATOR_REVIEW_ACCEPTED = "operator_review_accepted"
    PIPELINE_NOT_ACCEPTED = "pipeline_not_accepted"
    PIPELINE_EVIDENCE_INVALID = "pipeline_evidence_invalid"
    REEVALUATION_DEFERRED = "reevaluation_deferred"
    NO_ACTION_REQUIRED = "no_action_required"
    UNSUPPORTED_TARGET = "unsupported_target"


_OUTCOME_BY_REASON: Mapping[
    DownstreamOperationalActionReason,
    DownstreamOperationalActionOutcome,
] = MappingProxyType(
    {
        DownstreamOperationalActionReason.OPERATOR_REVIEW_ACCEPTED: (
            DownstreamOperationalActionOutcome.ACCEPTED
        ),
        DownstreamOperationalActionReason.PIPELINE_NOT_ACCEPTED: (
            DownstreamOperationalActionOutcome.REJECTED
        ),
        DownstreamOperationalActionReason.PIPELINE_EVIDENCE_INVALID: (
            DownstreamOperationalActionOutcome.REJECTED
        ),
        DownstreamOperationalActionReason.REEVALUATION_DEFERRED: (
            DownstreamOperationalActionOutcome.DEFERRED
        ),
        DownstreamOperationalActionReason.NO_ACTION_REQUIRED: (
            DownstreamOperationalActionOutcome.NO_OP
        ),
        DownstreamOperationalActionReason.UNSUPPORTED_TARGET: (
            DownstreamOperationalActionOutcome.REJECTED
        ),
    }
)


def _canonical_json(value: object) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True)


@dataclass(frozen=True, slots=True)
class DownstreamOperationalActionReceipt:
    """Immutable evidence emitted for one downstream adaptation attempt."""

    receipt_id: str
    adapter_name: str
    outcome: DownstreamOperationalActionOutcome
    reason: DownstreamOperationalActionReason
    pipeline_result: OperationalActionPipelineResult
    provenance: Mapping[str, str] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not self.receipt_id.strip():
            raise ValueError("receipt_id must not be empty")
        if not self.adapter_name.strip():
            raise ValueError("adapter_name must not be empty")
        if _OUTCOME_BY_REASON[self.reason] is not self.outcome:
            raise ValueError("receipt reason must match its outcome")
        object.__setattr__(self, "provenance", MappingProxyType(dict(self.provenance)))

    @property
    def action_id(self) -> str:
        """Return the canonical action identity preserved from the pipeline."""

        return self.pipeline_result.action.action_id

    @property
    def context_id(self) -> str:
        """Return the originating operational-context identity."""

        return self.pipeline_result.action.context_id

    @property
    def decision_id(self) -> str | None:
        """Return the originating decision identity when one exists."""

        return self.pipeline_result.action.decision_id

    @property
    def plan_id(self) -> str | None:
        """Return the originating plan identity when one exists."""

        return self.pipeline_result.action.plan_id

    @property
    def correlation_id(self) -> str | None:
        """Return the originating correlation identity when one exists."""

        return self.pipeline_result.action.correlation_id


class DownstreamOperationalActionAdapter(Protocol):
    """Vendor-neutral contract for adapting validated operational actions."""

    def adapt(
        self,
        pipeline_result: OperationalActionPipelineResult,
    ) -> DownstreamOperationalActionReceipt:
        """Adapt one pipeline result without performing physical actuation."""


_SUPPORTED_BOUNDARIES: Mapping[OperationalTarget, tuple[OperationalAction, str]] = (
    MappingProxyType(
        {
            OperationalTarget.NONE: (OperationalAction.NO_ACTION, "none"),
            OperationalTarget.REEVALUATION_SCHEDULER: (
                OperationalAction.REQUEST_REEVALUATION,
                "reevaluation_scheduler",
            ),
            OperationalTarget.OPERATOR_REVIEW: (
                OperationalAction.HALT,
                "operator_review",
            ),
        }
    )
)


@dataclass(frozen=True, slots=True)
class NonHardwareOperationalActionAdapter:
    """Adapt safe operational routes into immutable, non-actuating receipts."""

    adapter_name: str = "poolos.non_hardware_operational_action_adapter"

    def __post_init__(self) -> None:
        if not self.adapter_name.strip():
            raise ValueError("adapter_name must not be empty")

    @property
    def supported_targets(self) -> tuple[OperationalTarget, ...]:
        """Return the complete, deterministic set of supported logical targets."""

        return tuple(_SUPPORTED_BOUNDARIES)

    def adapt(
        self,
        pipeline_result: OperationalActionPipelineResult,
    ) -> DownstreamOperationalActionReceipt:
        """Return downstream evidence without invoking any external subsystem."""

        if pipeline_result.status is not OperationalActionPipelineStatus.ACCEPTED:
            return self._receipt(
                pipeline_result,
                outcome=DownstreamOperationalActionOutcome.REJECTED,
                reason=DownstreamOperationalActionReason.PIPELINE_NOT_ACCEPTED,
            )

        if not self._has_valid_pipeline_evidence(pipeline_result):
            return self._receipt(
                pipeline_result,
                outcome=DownstreamOperationalActionOutcome.REJECTED,
                reason=DownstreamOperationalActionReason.PIPELINE_EVIDENCE_INVALID,
            )

        target = pipeline_result.routed_target
        if target is OperationalTarget.NONE:
            return self._receipt(
                pipeline_result,
                outcome=DownstreamOperationalActionOutcome.NO_OP,
                reason=DownstreamOperationalActionReason.NO_ACTION_REQUIRED,
            )
        if target is OperationalTarget.REEVALUATION_SCHEDULER:
            hint = pipeline_result.action.reevaluation_hint
            if hint is None or not hint.strip():
                return self._receipt(
                    pipeline_result,
                    outcome=DownstreamOperationalActionOutcome.REJECTED,
                    reason=DownstreamOperationalActionReason.PIPELINE_EVIDENCE_INVALID,
                )
            return self._receipt(
                pipeline_result,
                outcome=DownstreamOperationalActionOutcome.DEFERRED,
                reason=DownstreamOperationalActionReason.REEVALUATION_DEFERRED,
            )
        if target is OperationalTarget.OPERATOR_REVIEW:
            return self._receipt(
                pipeline_result,
                outcome=DownstreamOperationalActionOutcome.ACCEPTED,
                reason=DownstreamOperationalActionReason.OPERATOR_REVIEW_ACCEPTED,
            )
        return self._receipt(
            pipeline_result,
            outcome=DownstreamOperationalActionOutcome.REJECTED,
            reason=DownstreamOperationalActionReason.UNSUPPORTED_TARGET,
        )

    @staticmethod
    def _has_valid_pipeline_evidence(
        pipeline_result: OperationalActionPipelineResult,
    ) -> bool:
        action = pipeline_result.action
        expected_route = _SUPPORTED_BOUNDARIES.get(pipeline_result.routed_target)
        if pipeline_result.reason is not OperationalActionPipelineReason.ROUTE_ACCEPTED:
            return False
        if action.action_id not in pipeline_result.accepted_action_ids:
            return False
        if pipeline_result.routed_target is not action.target:
            return False
        if expected_route is None:
            return True
        expected_action, expected_boundary = expected_route
        return (
            action.action is expected_action
            and pipeline_result.boundary_name == expected_boundary
        )

    def _receipt(
        self,
        pipeline_result: OperationalActionPipelineResult,
        *,
        outcome: DownstreamOperationalActionOutcome,
        reason: DownstreamOperationalActionReason,
    ) -> DownstreamOperationalActionReceipt:
        action = pipeline_result.action
        identity_payload = {
            "action_id": action.action_id,
            "adapter_name": self.adapter_name,
            "boundary_name": pipeline_result.boundary_name,
            "correlation_id": action.correlation_id,
            "outcome": outcome.value,
            "pipeline_reason": pipeline_result.reason.value,
            "pipeline_status": pipeline_result.status.value,
            "reason": reason.value,
            "target": pipeline_result.routed_target.value,
        }
        receipt_id = "downstream-operational-receipt-" + sha256(
            _canonical_json(identity_payload).encode("utf-8")
        ).hexdigest()[:24]
        provenance = {
            **dict(action.diagnostics),
            **dict(pipeline_result.diagnostics),
            "downstream_adapter": self.adapter_name,
            "downstream_outcome": outcome.value,
            "downstream_reason": reason.value,
            "downstream_receipt_id": receipt_id,
            "source_action_id": action.action_id,
            "source_context_id": action.context_id,
            "source_decision_id": action.decision_id or "",
            "source_plan_id": action.plan_id or "",
            "source_correlation_id": action.correlation_id or "",
        }
        return DownstreamOperationalActionReceipt(
            receipt_id=receipt_id,
            adapter_name=self.adapter_name,
            outcome=outcome,
            reason=reason,
            pipeline_result=pipeline_result,
            provenance=provenance,
        )
