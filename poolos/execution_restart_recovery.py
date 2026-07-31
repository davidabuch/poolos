"""Safe restart classification for recorded PoolOS execution histories.

Execution restart recovery interprets append-only flight-recorder facts.  It
never restores execution authority, rebuilds a coordinator cursor, retries an
operation, or contacts an external system.  Any interrupted execution is
classified for reconciliation and fresh reevaluation.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from hashlib import sha256
import json
from types import MappingProxyType
from typing import Mapping

from .execution_flight_recorder import (
    ExecutionFlightRecord,
    ExecutionRecordType,
    ExecutionTimeline,
)
from .execution_models import (
    AuthorizationDisposition,
    ExecutionAuthorization,
    ExecutionLifecycleStatus,
    ExecutionOutcome,
    ExecutionPlan,
    ExecutionProposal,
    VerificationStatus,
)
from .execution_state_machine import ExecutionStateTransition
from .execution_verification import ExecutionVerificationResult


def _require_identifier(value: str, label: str) -> str:
    normalized = value.strip()
    if not normalized:
        raise ValueError(f"{label} must not be empty")
    return normalized


def _require_aware(value: datetime, label: str) -> None:
    if value.tzinfo is None:
        raise ValueError(f"{label} must be timezone-aware")


def _freeze_string_mapping(value: Mapping[str, str]) -> Mapping[str, str]:
    return MappingProxyType(dict(value))


class ExecutionRecoveryClassification(str, Enum):
    """Deterministic classification of one recorded execution lineage."""

    NO_HISTORY = "no_history"
    AUTHORIZATION_DEFERRED = "authorization_deferred"
    AUTHORIZATION_REJECTED = "authorization_rejected"
    INTERRUPTED_BEFORE_AUTHORIZATION = "interrupted_before_authorization"
    INTERRUPTED_BEFORE_PLAN = "interrupted_before_plan"
    INTERRUPTED_BEFORE_EXECUTION = "interrupted_before_execution"
    INTERRUPTED_DURING_EXECUTION = "interrupted_during_execution"
    INTERRUPTED_DURING_VERIFICATION = "interrupted_during_verification"
    INCOMPLETE_AFTER_VERIFICATION = "incomplete_after_verification"
    INCOMPLETE_AFTER_TERMINAL_TRANSITION = "incomplete_after_terminal_transition"
    COMPLETED = "completed"
    TERMINAL_FAILURE = "terminal_failure"
    CORRUPT_HISTORY = "corrupt_history"


class ExecutionRecoveryRecommendation(str, Enum):
    """Non-actuating recommendations emitted by restart classification."""

    NO_ACTION_REQUIRED = "no_action_required"
    REEVALUATE = "reevaluate"
    MARK_SUPERSEDED = "mark_superseded"
    RECORD_CORRUPTION = "record_corruption"
    AWAIT_OPERATOR = "await_operator"


class ExecutionRecoveryDisposition(str, Enum):
    """Whether history was safely classified or found invalid."""

    ASSESSED = "assessed"
    CORRUPT = "corrupt"


@dataclass(frozen=True, slots=True, kw_only=True)
class ExecutionRecoveryRequest:
    """Immutable execution history snapshot presented after restart."""

    records: tuple[ExecutionFlightRecord, ...]
    recovered_at: datetime
    proposal_id: str | None = None
    metadata: Mapping[str, str] = field(default_factory=dict)
    schema_version: int = 1

    def __post_init__(self) -> None:
        object.__setattr__(self, "records", tuple(self.records))
        _require_aware(self.recovered_at, "recovered_at")
        if self.proposal_id is not None:
            object.__setattr__(
                self,
                "proposal_id",
                _require_identifier(self.proposal_id, "proposal_id"),
            )
        if self.schema_version < 1:
            raise ValueError("schema_version must be at least 1")
        object.__setattr__(self, "metadata", _freeze_string_mapping(self.metadata))


@dataclass(frozen=True, slots=True, kw_only=True)
class ExecutionRecoveryAssessment:
    """Immutable command-free assessment of one execution lineage."""

    assessment_id: str
    disposition: ExecutionRecoveryDisposition
    classification: ExecutionRecoveryClassification
    recommendations: tuple[ExecutionRecoveryRecommendation, ...]
    recovered_at: datetime
    reason: str
    proposal_id: str | None = None
    authorization_id: str | None = None
    plan_id: str | None = None
    session_id: str | None = None
    decision_id: str | None = None
    context_id: str | None = None
    latest_record_sequence: int | None = None
    latest_record_type: ExecutionRecordType | None = None
    latest_lifecycle_status: ExecutionLifecycleStatus | None = None
    latest_verification_status: VerificationStatus | None = None
    record_count: int = 0
    metadata: Mapping[str, str] = field(default_factory=dict)
    schema_version: int = 1

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "assessment_id",
            _require_identifier(self.assessment_id, "assessment_id"),
        )
        object.__setattr__(self, "reason", _require_identifier(self.reason, "reason"))
        _require_aware(self.recovered_at, "recovered_at")
        for name in (
            "proposal_id",
            "authorization_id",
            "plan_id",
            "session_id",
            "decision_id",
            "context_id",
        ):
            value = getattr(self, name)
            if value is not None:
                object.__setattr__(self, name, _require_identifier(value, name))
        recommendations = tuple(self.recommendations)
        if not recommendations:
            raise ValueError("recommendations must not be empty")
        if len(recommendations) != len(set(recommendations)):
            raise ValueError("recommendations must be unique")
        object.__setattr__(self, "recommendations", recommendations)
        if self.record_count < 0:
            raise ValueError("record_count must not be negative")
        if self.latest_record_sequence is not None and self.latest_record_sequence < 1:
            raise ValueError("latest_record_sequence must be at least 1")
        if self.disposition is ExecutionRecoveryDisposition.CORRUPT:
            required = {
                ExecutionRecoveryRecommendation.RECORD_CORRUPTION,
                ExecutionRecoveryRecommendation.AWAIT_OPERATOR,
            }
            if not required.issubset(set(recommendations)):
                raise ValueError(
                    "corrupt assessments must record corruption and await operator"
                )
        if self.classification is ExecutionRecoveryClassification.NO_HISTORY:
            if self.record_count != 0:
                raise ValueError("no-history assessment cannot contain records")
        if self.schema_version < 1:
            raise ValueError("schema_version must be at least 1")
        object.__setattr__(self, "metadata", _freeze_string_mapping(self.metadata))

    @property
    def resume_permitted(self) -> bool:
        """Execution restart recovery never grants authority to resume."""

        return False

    @property
    def requires_reevaluation(self) -> bool:
        """Return whether fresh observation and decision evaluation is advised."""

        return ExecutionRecoveryRecommendation.REEVALUATE in self.recommendations


@dataclass(frozen=True, slots=True)
class ExecutionRestartRecoveryEngine:
    """Classify execution history without restoring or exercising authority."""

    assessment_id_prefix: str = "execution-recovery"

    def __post_init__(self) -> None:
        if not self.assessment_id_prefix.strip():
            raise ValueError("assessment_id_prefix must not be empty")

    def recover(self, request: ExecutionRecoveryRequest) -> ExecutionRecoveryAssessment:
        """Classify a recorded lineage and emit non-actuating recommendations."""

        records = request.records
        if not records:
            return self._assessment(
                request=request,
                lineage=(),
                disposition=ExecutionRecoveryDisposition.ASSESSED,
                classification=ExecutionRecoveryClassification.NO_HISTORY,
                recommendations=(
                    ExecutionRecoveryRecommendation.NO_ACTION_REQUIRED,
                ),
                reason="no_execution_history",
            )

        corruption = self._validate_global_history(records, request.recovered_at)
        if corruption is not None:
            return self._corrupt(request, records, corruption)

        proposal_id = request.proposal_id or self._latest_proposal_id(records)
        if proposal_id is None:
            return self._corrupt(request, records, "history_contains_no_proposal")
        lineage = tuple(
            record for record in records if record.proposal_id == proposal_id
        )
        if not lineage:
            return self._corrupt(
                request,
                records,
                f"requested_proposal_not_found:{proposal_id}",
            )

        corruption = self._validate_lineage(lineage)
        if corruption is not None:
            return self._corrupt(request, lineage, corruption)

        proposal = self._single_artifact(lineage, ExecutionRecordType.PROPOSAL)
        authorization = self._single_artifact(
            lineage, ExecutionRecordType.AUTHORIZATION, required=False
        )
        plan = self._single_artifact(lineage, ExecutionRecordType.PLAN, required=False)
        outcomes = tuple(
            record.artifact
            for record in lineage
            if record.record_type is ExecutionRecordType.OUTCOME
        )
        verifications = tuple(
            record.artifact
            for record in lineage
            if record.record_type is ExecutionRecordType.VERIFICATION
        )
        transitions = tuple(
            record.artifact
            for record in lineage
            if record.record_type is ExecutionRecordType.LIFECYCLE_TRANSITION
        )

        assert isinstance(proposal, ExecutionProposal)
        if outcomes:
            latest_outcome = outcomes[-1]
            assert isinstance(latest_outcome, ExecutionOutcome)
            if latest_outcome.completed_at is not None:
                if latest_outcome.status in {
                    ExecutionLifecycleStatus.VERIFIED,
                    ExecutionLifecycleStatus.COMPLETED,
                }:
                    return self._classified(
                        request,
                        lineage,
                        ExecutionRecoveryClassification.COMPLETED,
                        (ExecutionRecoveryRecommendation.NO_ACTION_REQUIRED,),
                        "execution_outcome_completed",
                    )
                return self._classified(
                    request,
                    lineage,
                    ExecutionRecoveryClassification.TERMINAL_FAILURE,
                    (ExecutionRecoveryRecommendation.REEVALUATE,),
                    f"execution_outcome_terminal:{latest_outcome.status.value}",
                )

        if authorization is None:
            return self._classified(
                request,
                lineage,
                ExecutionRecoveryClassification.INTERRUPTED_BEFORE_AUTHORIZATION,
                (
                    ExecutionRecoveryRecommendation.MARK_SUPERSEDED,
                    ExecutionRecoveryRecommendation.REEVALUATE,
                ),
                "proposal_recorded_without_authorization",
            )
        assert isinstance(authorization, ExecutionAuthorization)
        if authorization.disposition is AuthorizationDisposition.REJECTED:
            return self._classified(
                request,
                lineage,
                ExecutionRecoveryClassification.AUTHORIZATION_REJECTED,
                (ExecutionRecoveryRecommendation.NO_ACTION_REQUIRED,),
                "authorization_was_rejected",
            )
        if authorization.disposition is AuthorizationDisposition.DEFERRED:
            return self._classified(
                request,
                lineage,
                ExecutionRecoveryClassification.AUTHORIZATION_DEFERRED,
                (ExecutionRecoveryRecommendation.REEVALUATE,),
                "authorization_was_deferred",
            )
        if plan is None:
            return self._classified(
                request,
                lineage,
                ExecutionRecoveryClassification.INTERRUPTED_BEFORE_PLAN,
                (
                    ExecutionRecoveryRecommendation.MARK_SUPERSEDED,
                    ExecutionRecoveryRecommendation.REEVALUATE,
                ),
                "authorized_proposal_has_no_plan",
            )
        assert isinstance(plan, ExecutionPlan)

        latest_transition_status = self._latest_transition_status(transitions)
        latest_verification_status = self._latest_verification_status(verifications)

        if latest_transition_status in {
            ExecutionLifecycleStatus.REJECTED,
            ExecutionLifecycleStatus.FAILED,
            ExecutionLifecycleStatus.TIMED_OUT,
            ExecutionLifecycleStatus.ABORTED,
            ExecutionLifecycleStatus.SUPERSEDED,
            ExecutionLifecycleStatus.COMPLETED,
        }:
            return self._classified(
                request,
                lineage,
                ExecutionRecoveryClassification.INCOMPLETE_AFTER_TERMINAL_TRANSITION,
                (ExecutionRecoveryRecommendation.REEVALUATE,),
                (
                    "terminal_transition_without_final_outcome:"
                    f"{latest_transition_status.value}"
                ),
            )

        if latest_verification_status in {
            VerificationStatus.VERIFIED,
            VerificationStatus.FAILED,
            VerificationStatus.TIMED_OUT,
            VerificationStatus.NOT_REQUIRED,
        }:
            return self._classified(
                request,
                lineage,
                ExecutionRecoveryClassification.INCOMPLETE_AFTER_VERIFICATION,
                (
                    ExecutionRecoveryRecommendation.MARK_SUPERSEDED,
                    ExecutionRecoveryRecommendation.REEVALUATE,
                ),
                (
                    "terminal_verification_without_final_outcome:"
                    f"{latest_verification_status.value}"
                ),
            )
        if latest_verification_status in {
            VerificationStatus.PENDING,
            VerificationStatus.PARTIAL,
        } or latest_transition_status is ExecutionLifecycleStatus.VERIFYING:
            return self._classified(
                request,
                lineage,
                ExecutionRecoveryClassification.INTERRUPTED_DURING_VERIFICATION,
                (
                    ExecutionRecoveryRecommendation.MARK_SUPERSEDED,
                    ExecutionRecoveryRecommendation.REEVALUATE,
                ),
                "verification_was_incomplete_at_restart",
            )

        if latest_transition_status in {
            ExecutionLifecycleStatus.EXECUTING,
            ExecutionLifecycleStatus.DELIVERING,
            ExecutionLifecycleStatus.DELIVERED,
        } or any(
            record.record_type is ExecutionRecordType.COORDINATION_EVENT
            for record in lineage
        ):
            return self._classified(
                request,
                lineage,
                ExecutionRecoveryClassification.INTERRUPTED_DURING_EXECUTION,
                (
                    ExecutionRecoveryRecommendation.MARK_SUPERSEDED,
                    ExecutionRecoveryRecommendation.REEVALUATE,
                ),
                "execution_activity_was_incomplete_at_restart",
            )

        return self._classified(
            request,
            lineage,
            ExecutionRecoveryClassification.INTERRUPTED_BEFORE_EXECUTION,
            (
                ExecutionRecoveryRecommendation.MARK_SUPERSEDED,
                ExecutionRecoveryRecommendation.REEVALUATE,
            ),
            "plan_recorded_without_execution_activity",
        )

    @staticmethod
    def _validate_global_history(
        records: tuple[ExecutionFlightRecord, ...], recovered_at: datetime
    ) -> str | None:
        try:
            ExecutionTimeline(records=records)
        except ValueError as exc:
            return f"invalid_timeline:{exc}"
        if any(record.occurred_at > recovered_at for record in records):
            return "history_contains_future_record"
        return None

    @staticmethod
    def _latest_proposal_id(
        records: tuple[ExecutionFlightRecord, ...]
    ) -> str | None:
        for record in reversed(records):
            if record.record_type is ExecutionRecordType.PROPOSAL:
                return record.proposal_id
        return None

    @staticmethod
    def _validate_lineage(records: tuple[ExecutionFlightRecord, ...]) -> str | None:
        proposal_records = tuple(
            record
            for record in records
            if record.record_type is ExecutionRecordType.PROPOSAL
        )
        if len(proposal_records) != 1:
            return "lineage_requires_exactly_one_proposal"
        if records[0].record_type is not ExecutionRecordType.PROPOSAL:
            return "proposal_must_be_first_lineage_record"
        if sum(
            record.record_type is ExecutionRecordType.AUTHORIZATION
            for record in records
        ) > 1:
            return "lineage_contains_multiple_authorizations"
        if (
            sum(record.record_type is ExecutionRecordType.PLAN for record in records)
            > 1
        ):
            return "lineage_contains_multiple_plans"
        plan_records = tuple(
            record
            for record in records
            if record.record_type is ExecutionRecordType.PLAN
        )
        for record in records:
            if record.record_type in {
                ExecutionRecordType.LIFECYCLE_TRANSITION,
                ExecutionRecordType.COORDINATION_EVENT,
                ExecutionRecordType.VERIFICATION,
                ExecutionRecordType.OUTCOME,
            } and not plan_records:
                return "plan_scoped_record_exists_without_plan"
        if plan_records:
            plan_record = plan_records[0]
            for record in records:
                if record.plan_id is not None and record.plan_id != plan_record.plan_id:
                    return "lineage_contains_cross_plan_record"
                if (
                    record.session_id is not None
                    and record.session_id != plan_record.session_id
                ):
                    return "lineage_contains_cross_session_record"
        return None

    @staticmethod
    def _single_artifact(
        records: tuple[ExecutionFlightRecord, ...],
        record_type: ExecutionRecordType,
        *,
        required: bool = True,
    ) -> object | None:
        matches = tuple(
            record.artifact for record in records if record.record_type is record_type
        )
        if not matches:
            if required:
                raise ValueError(f"missing required {record_type.value} artifact")
            return None
        return matches[0]

    @staticmethod
    def _latest_transition_status(
        transitions: tuple[object, ...]
    ) -> ExecutionLifecycleStatus | None:
        if not transitions:
            return None
        transition = transitions[-1]
        assert isinstance(transition, ExecutionStateTransition)
        return transition.to_status

    @staticmethod
    def _latest_verification_status(
        verifications: tuple[object, ...]
    ) -> VerificationStatus | None:
        if not verifications:
            return None
        verification = verifications[-1]
        assert isinstance(verification, ExecutionVerificationResult)
        return verification.status

    def _classified(
        self,
        request: ExecutionRecoveryRequest,
        lineage: tuple[ExecutionFlightRecord, ...],
        classification: ExecutionRecoveryClassification,
        recommendations: tuple[ExecutionRecoveryRecommendation, ...],
        reason: str,
    ) -> ExecutionRecoveryAssessment:
        return self._assessment(
            request=request,
            lineage=lineage,
            disposition=ExecutionRecoveryDisposition.ASSESSED,
            classification=classification,
            recommendations=recommendations,
            reason=reason,
        )

    def _corrupt(
        self,
        request: ExecutionRecoveryRequest,
        lineage: tuple[ExecutionFlightRecord, ...],
        reason: str,
    ) -> ExecutionRecoveryAssessment:
        return self._assessment(
            request=request,
            lineage=lineage,
            disposition=ExecutionRecoveryDisposition.CORRUPT,
            classification=ExecutionRecoveryClassification.CORRUPT_HISTORY,
            recommendations=(
                ExecutionRecoveryRecommendation.RECORD_CORRUPTION,
                ExecutionRecoveryRecommendation.AWAIT_OPERATOR,
            ),
            reason=reason,
        )

    def _assessment(
        self,
        *,
        request: ExecutionRecoveryRequest,
        lineage: tuple[ExecutionFlightRecord, ...],
        disposition: ExecutionRecoveryDisposition,
        classification: ExecutionRecoveryClassification,
        recommendations: tuple[ExecutionRecoveryRecommendation, ...],
        reason: str,
    ) -> ExecutionRecoveryAssessment:
        latest = lineage[-1] if lineage else None
        proposal = next(
            (
                record
                for record in lineage
                if record.record_type is ExecutionRecordType.PROPOSAL
            ),
            None,
        )
        authorization = next(
            (
                record
                for record in lineage
                if record.record_type is ExecutionRecordType.AUTHORIZATION
            ),
            None,
        )
        plan = next(
            (
                record
                for record in lineage
                if record.record_type is ExecutionRecordType.PLAN
            ),
            None,
        )
        transitions = tuple(
            record.artifact
            for record in lineage
            if record.record_type is ExecutionRecordType.LIFECYCLE_TRANSITION
        )
        verifications = tuple(
            record.artifact
            for record in lineage
            if record.record_type is ExecutionRecordType.VERIFICATION
        )
        payload = {
            "classification": classification.value,
            "disposition": disposition.value,
            "latest_record_id": latest.record_id if latest else None,
            "proposal_id": proposal.proposal_id if proposal else request.proposal_id,
            "reason": reason,
            "recommendations": [item.value for item in recommendations],
            "recovered_at": request.recovered_at.isoformat(),
            "record_ids": [record.record_id for record in lineage],
            "metadata": dict(sorted(request.metadata.items())),
        }
        digest = sha256(
            json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
        ).hexdigest()[:24]
        return ExecutionRecoveryAssessment(
            assessment_id=f"{self.assessment_id_prefix}-{digest}",
            disposition=disposition,
            classification=classification,
            recommendations=recommendations,
            recovered_at=request.recovered_at,
            reason=reason,
            proposal_id=proposal.proposal_id if proposal else request.proposal_id,
            authorization_id=(
                authorization.authorization_id if authorization else None
            ),
            plan_id=plan.plan_id if plan else (latest.plan_id if latest else None),
            session_id=(
                plan.session_id if plan else (latest.session_id if latest else None)
            ),
            decision_id=proposal.decision_id if proposal else None,
            context_id=proposal.context_id if proposal else None,
            latest_record_sequence=latest.sequence if latest else None,
            latest_record_type=latest.record_type if latest else None,
            latest_lifecycle_status=self._latest_transition_status(transitions),
            latest_verification_status=self._latest_verification_status(verifications),
            record_count=len(lineage),
            metadata=request.metadata,
        )
