"""Pure observation-based verification for PoolOS execution steps.

The verification engine compares one immutable :class:`ExecutionStep` with
canonical typed observations already present in an :class:`ObservationStore`.
It does not translate operations, deliver commands, advance coordination, or
contact Home Assistant, Pentair, simulators, transports, or equipment.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta
from enum import Enum
from hashlib import sha256
import json
from types import MappingProxyType
from typing import Any, Mapping

from .clock import FixedClock
from .execution_models import ExecutionStep, VerificationStatus
from .integration import SetPumpSpeed
from .observations import (
    FreshnessPolicy,
    ObservationFreshness,
    ObservationQuality,
    ObservationSourceKind,
    ObservationStore,
)


class VerificationEvidenceDisposition(str, Enum):
    """Disposition of one expected observation."""

    MATCHED = "matched"
    MISMATCHED = "mismatched"
    MISSING = "missing"
    STALE = "stale"
    FUTURE = "future"
    UNUSABLE = "unusable"
    LOW_CONFIDENCE = "low_confidence"


@dataclass(frozen=True, slots=True, kw_only=True)
class ExecutionVerificationEvidence:
    """Immutable evidence for one expected observation."""

    observation_id: str
    expected_value: Any
    actual_value: Any | None
    disposition: VerificationEvidenceDisposition
    observed_at: datetime | None = None
    source_kind: ObservationSourceKind | None = None
    source_id: str | None = None
    quality: ObservationQuality | None = None
    confidence: float | None = None
    reason: str = ""

    def __post_init__(self) -> None:
        observation_id = self.observation_id.strip()
        if not observation_id:
            raise ValueError("observation_id must not be empty")
        object.__setattr__(self, "observation_id", observation_id)
        if self.observed_at is not None and self.observed_at.tzinfo is None:
            raise ValueError("observed_at must be timezone-aware")
        if self.source_id is not None:
            source_id = self.source_id.strip()
            if not source_id:
                raise ValueError("source_id must not be empty when provided")
            object.__setattr__(self, "source_id", source_id)
        if self.confidence is not None and not 0.0 <= self.confidence <= 1.0:
            raise ValueError("confidence must be between 0 and 1")
        reason = self.reason.strip()
        if not reason:
            raise ValueError("reason must not be empty")
        object.__setattr__(self, "reason", reason)
        object.__setattr__(self, "expected_value", _freeze_value(self.expected_value))
        object.__setattr__(self, "actual_value", _freeze_value(self.actual_value))


@dataclass(frozen=True, slots=True, kw_only=True)
class ExecutionVerificationRequest:
    """Inputs for deterministic verification of one execution step."""

    plan_id: str
    step: ExecutionStep
    observations: ObservationStore
    verification_started_at: datetime
    evaluated_at: datetime
    timeout: timedelta
    freshness_policy: FreshnessPolicy
    source_kind: ObservationSourceKind = ObservationSourceKind.SIMULATED
    source_id: str | None = None
    minimum_confidence: float = 0.5
    accepted_qualities: tuple[ObservationQuality, ...] = (
        ObservationQuality.GOOD,
        ObservationQuality.DEGRADED,
    )
    metadata: Mapping[str, str] = field(default_factory=dict)

    def __post_init__(self) -> None:
        plan_id = self.plan_id.strip()
        if not plan_id:
            raise ValueError("plan_id must not be empty")
        object.__setattr__(self, "plan_id", plan_id)
        if self.verification_started_at.tzinfo is None:
            raise ValueError("verification_started_at must be timezone-aware")
        if self.evaluated_at.tzinfo is None:
            raise ValueError("evaluated_at must be timezone-aware")
        if self.evaluated_at < self.verification_started_at:
            raise ValueError("evaluated_at cannot precede verification_started_at")
        if self.timeout < timedelta(0):
            raise ValueError("timeout must not be negative")
        if self.source_id is not None:
            source_id = self.source_id.strip()
            if not source_id:
                raise ValueError("source_id must not be empty when provided")
            object.__setattr__(self, "source_id", source_id)
        if not 0.0 <= self.minimum_confidence <= 1.0:
            raise ValueError("minimum_confidence must be between 0 and 1")
        qualities = tuple(self.accepted_qualities)
        if not qualities:
            raise ValueError("accepted_qualities must not be empty")
        if len(qualities) != len(set(qualities)):
            raise ValueError("accepted_qualities must be unique")
        object.__setattr__(self, "accepted_qualities", qualities)
        object.__setattr__(self, "metadata", MappingProxyType(dict(self.metadata)))

    @property
    def deadline(self) -> datetime:
        """Return the inclusive verification deadline."""

        return self.verification_started_at + self.timeout


@dataclass(frozen=True, slots=True, kw_only=True)
class ExecutionVerificationResult:
    """Immutable result of one evidence evaluation."""

    verification_id: str
    plan_id: str
    step_id: str
    status: VerificationStatus
    evaluated_at: datetime
    deadline: datetime
    reason: str
    evidence: tuple[ExecutionVerificationEvidence, ...]
    metadata: Mapping[str, str] = field(default_factory=dict)
    schema_version: int = 1

    def __post_init__(self) -> None:
        for field_name in ("verification_id", "plan_id", "step_id", "reason"):
            value = getattr(self, field_name).strip()
            if not value:
                raise ValueError(f"{field_name} must not be empty")
            object.__setattr__(self, field_name, value)
        if self.evaluated_at.tzinfo is None:
            raise ValueError("evaluated_at must be timezone-aware")
        if self.deadline.tzinfo is None:
            raise ValueError("deadline must be timezone-aware")
        if self.schema_version < 1:
            raise ValueError("schema_version must be at least 1")
        evidence = tuple(self.evidence)
        evidence_ids = [item.observation_id for item in evidence]
        if len(evidence_ids) != len(set(evidence_ids)):
            raise ValueError("evidence observation IDs must be unique")
        if self.status is VerificationStatus.NOT_REQUIRED and evidence:
            raise ValueError("not-required verification cannot contain evidence")
        if self.status is not VerificationStatus.NOT_REQUIRED and not evidence:
            raise ValueError("verification result requires evidence")
        object.__setattr__(self, "evidence", evidence)
        object.__setattr__(self, "metadata", MappingProxyType(dict(self.metadata)))

    @property
    def terminal(self) -> bool:
        """Return whether this verification attempt has a terminal result."""

        return self.status in {
            VerificationStatus.NOT_REQUIRED,
            VerificationStatus.VERIFIED,
            VerificationStatus.FAILED,
            VerificationStatus.TIMED_OUT,
        }


@dataclass(frozen=True, slots=True)
class ExecutionVerificationEngine:
    """Evaluate expected observations without causing external side effects."""

    verification_id_prefix: str = "execution-verification"

    def __post_init__(self) -> None:
        if not self.verification_id_prefix.strip():
            raise ValueError("verification_id_prefix must not be empty")

    def verify(
        self, request: ExecutionVerificationRequest
    ) -> ExecutionVerificationResult:
        """Evaluate current canonical observations for one plan step."""

        step = request.step
        if not step.verification_required:
            return self._result(
                request,
                status=VerificationStatus.NOT_REQUIRED,
                reason="verification_not_required",
                evidence=(),
            )

        clock = FixedClock(request.evaluated_at)
        evidence = tuple(
            self._evaluate_expectation(
                observation_id,
                expected_value,
                request=request,
                clock=clock,
            )
            for observation_id, expected_value in sorted(
                step.expected_observations.items()
            )
        )
        matched = sum(
            item.disposition is VerificationEvidenceDisposition.MATCHED
            for item in evidence
        )
        mismatched = sum(
            item.disposition is VerificationEvidenceDisposition.MISMATCHED
            for item in evidence
        )
        unresolved = len(evidence) - matched - mismatched
        bounded_pump_settling = _is_bounded_pump_settling_step(step)

        if matched == len(evidence):
            status = VerificationStatus.VERIFIED
            reason = "all_expected_observations_verified"
        elif request.evaluated_at >= request.deadline:
            status = VerificationStatus.TIMED_OUT
            reason = "verification_deadline_reached"
        elif mismatched and unresolved == 0 and bounded_pump_settling:
            status = VerificationStatus.PENDING
            reason = "transient_observation_mismatch_pending"
        elif mismatched and unresolved == 0:
            status = VerificationStatus.FAILED
            reason = "fresh_observations_do_not_match_expectations"
        elif matched:
            status = VerificationStatus.PARTIAL
            reason = "some_expected_observations_verified"
        else:
            status = VerificationStatus.PENDING
            reason = "verification_evidence_pending"

        return self._result(
            request,
            status=status,
            reason=reason,
            evidence=evidence,
        )

    def _evaluate_expectation(
        self,
        observation_id: str,
        expected_value: Any,
        *,
        request: ExecutionVerificationRequest,
        clock: FixedClock,
    ) -> ExecutionVerificationEvidence:
        observation = request.observations.get(
            observation_id,
            source_kind=request.source_kind,
            source_id=request.source_id,
        )
        if observation is None:
            return ExecutionVerificationEvidence(
                observation_id=observation_id,
                expected_value=expected_value,
                actual_value=None,
                disposition=VerificationEvidenceDisposition.MISSING,
                reason="matching_observation_not_found",
            )

        freshness = observation.freshness(
            clock=clock,
            policy=request.freshness_policy,
        )
        common = {
            "observation_id": observation_id,
            "expected_value": expected_value,
            "actual_value": observation.value,
            "observed_at": observation.observed_at,
            "source_kind": observation.source_kind,
            "source_id": observation.source_id,
            "quality": observation.quality,
            "confidence": observation.confidence,
        }
        if freshness is ObservationFreshness.STALE:
            return ExecutionVerificationEvidence(
                **common,
                disposition=VerificationEvidenceDisposition.STALE,
                reason="observation_is_stale",
            )
        if freshness is ObservationFreshness.FUTURE:
            return ExecutionVerificationEvidence(
                **common,
                disposition=VerificationEvidenceDisposition.FUTURE,
                reason="observation_is_future_dated",
            )
        if freshness is ObservationFreshness.UNKNOWN:
            return ExecutionVerificationEvidence(
                **common,
                disposition=VerificationEvidenceDisposition.UNUSABLE,
                reason="observation_freshness_unknown",
            )
        if observation.quality not in request.accepted_qualities:
            return ExecutionVerificationEvidence(
                **common,
                disposition=VerificationEvidenceDisposition.UNUSABLE,
                reason=f"observation_quality_not_accepted:{observation.quality.value}",
            )
        if observation.confidence < request.minimum_confidence:
            return ExecutionVerificationEvidence(
                **common,
                disposition=VerificationEvidenceDisposition.LOW_CONFIDENCE,
                reason="observation_confidence_below_minimum",
            )
        tolerance = _numeric_tolerance(request.step, observation_id)
        exact_match = observation.value == expected_value
        tolerance_match = (
            tolerance is not None
            and _is_number(observation.value)
            and _is_number(expected_value)
            and abs(float(observation.value) - float(expected_value)) <= tolerance
        )
        if exact_match or tolerance_match:
            return ExecutionVerificationEvidence(
                **common,
                disposition=VerificationEvidenceDisposition.MATCHED,
                reason=(
                    "observation_matches_expectation"
                    if exact_match
                    else "observation_within_numeric_tolerance"
                ),
            )
        return ExecutionVerificationEvidence(
            **common,
            disposition=VerificationEvidenceDisposition.MISMATCHED,
            reason="observation_does_not_match_expectation",
        )

    def _result(
        self,
        request: ExecutionVerificationRequest,
        *,
        status: VerificationStatus,
        reason: str,
        evidence: tuple[ExecutionVerificationEvidence, ...],
    ) -> ExecutionVerificationResult:
        payload = {
            "plan_id": request.plan_id,
            "step_id": request.step.step_id,
            "status": status.value,
            "evaluated_at": request.evaluated_at.isoformat(),
            "deadline": request.deadline.isoformat(),
            "reason": reason,
            "evidence": [
                {
                    "observation_id": item.observation_id,
                    "expected_value": _json_value(item.expected_value),
                    "actual_value": _json_value(item.actual_value),
                    "disposition": item.disposition.value,
                    "observed_at": (
                        item.observed_at.isoformat() if item.observed_at else None
                    ),
                    "source_kind": (
                        item.source_kind.value if item.source_kind else None
                    ),
                    "source_id": item.source_id,
                    "quality": item.quality.value if item.quality else None,
                    "confidence": item.confidence,
                    "reason": item.reason,
                }
                for item in evidence
            ],
            "metadata": dict(request.metadata),
        }
        canonical = json.dumps(
            payload,
            ensure_ascii=True,
            separators=(",", ":"),
            sort_keys=True,
        )
        digest = sha256(canonical.encode("utf-8")).hexdigest()[:16]
        verification_id = (
            f"{self.verification_id_prefix}:{request.plan_id}:"
            f"{request.step.step_id}:{digest}"
        )
        return ExecutionVerificationResult(
            verification_id=verification_id,
            plan_id=request.plan_id,
            step_id=request.step.step_id,
            status=status,
            evaluated_at=request.evaluated_at,
            deadline=request.deadline,
            reason=reason,
            evidence=evidence,
            metadata=request.metadata,
        )


def _freeze_value(value: Any) -> Any:
    if isinstance(value, Mapping):
        return MappingProxyType(
            {str(key): _freeze_value(item) for key, item in value.items()}
        )
    if isinstance(value, list):
        return tuple(_freeze_value(item) for item in value)
    if isinstance(value, tuple):
        return tuple(_freeze_value(item) for item in value)
    if isinstance(value, set):
        return frozenset(_freeze_value(item) for item in value)
    return value


def _numeric_tolerance(step: ExecutionStep, observation_id: str) -> float | None:
    if not _is_bounded_pump_settling_step(step) or observation_id != "pump.rpm":
        return None
    raw = step.metadata.get(f"numeric_tolerance:{observation_id}")
    if raw is None:
        return None
    try:
        tolerance = float(raw)
    except ValueError as exc:
        raise ValueError("numeric observation tolerance must be a number") from exc
    if tolerance < 0:
        raise ValueError("numeric observation tolerance must not be negative")
    return tolerance


def _is_bounded_pump_settling_step(step: ExecutionStep) -> bool:
    return (
        isinstance(step.operation, SetPumpSpeed)
        and set(step.expected_observations) == {"pump.rpm"}
    )


def _is_number(value: Any) -> bool:
    return not isinstance(value, bool) and isinstance(value, (int, float))


def _json_value(value: Any) -> Any:
    if isinstance(value, Mapping):
        return {str(key): _json_value(item) for key, item in value.items()}
    if isinstance(value, (tuple, list)):
        return [_json_value(item) for item in value]
    if isinstance(value, (set, frozenset)):
        return sorted(_json_value(item) for item in value)
    return value


__all__ = [
    "ExecutionVerificationEngine",
    "ExecutionVerificationEvidence",
    "ExecutionVerificationRequest",
    "ExecutionVerificationResult",
    "VerificationEvidenceDisposition",
]
