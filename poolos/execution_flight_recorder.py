"""Append-only execution history for the PoolOS supervisory pipeline.

The execution flight recorder preserves immutable proposal, authorization, plan,
lifecycle, coordination, verification, and outcome artifacts in deterministic
append order.  It records facts only; it does not coordinate execution, deliver
commands, verify observations, or contact external systems.
"""

from __future__ import annotations

from dataclasses import dataclass, field, fields, is_dataclass
from datetime import datetime
from enum import Enum
from hashlib import sha256
import json
from types import MappingProxyType
from typing import Any, Mapping, Protocol, TypeAlias

from .execution_coordinator import ExecutionCoordinationEvent
from .execution_models import (
    AuthorizationDisposition,
    ExecutionAuthorization,
    ExecutionOutcome,
    ExecutionPlan,
    ExecutionProposal,
)
from .execution_state_machine import ExecutionStateTransition
from .execution_verification import ExecutionVerificationResult


ExecutionArtifact: TypeAlias = (
    ExecutionProposal
    | ExecutionAuthorization
    | ExecutionPlan
    | ExecutionStateTransition
    | ExecutionCoordinationEvent
    | ExecutionVerificationResult
    | ExecutionOutcome
)


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


def _json_value(value: Any) -> Any:
    """Return a deterministic JSON-compatible snapshot of supported values."""

    if value is None or isinstance(value, (bool, int, float, str)):
        return value
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, Enum):
        return value.value
    if isinstance(value, Mapping):
        return {
            str(key): _json_value(item)
            for key, item in sorted(value.items(), key=lambda pair: str(pair[0]))
        }
    if isinstance(value, (tuple, list)):
        return [_json_value(item) for item in value]
    if isinstance(value, (set, frozenset)):
        return sorted((_json_value(item) for item in value), key=repr)
    if is_dataclass(value) and not isinstance(value, type):
        return {
            item.name: _json_value(getattr(value, item.name))
            for item in fields(value)
        }
    raise TypeError(f"unsupported flight-recorder value: {type(value).__name__}")


class ExecutionRecordType(str, Enum):
    """Kinds of immutable execution artifacts preserved by the recorder."""

    PROPOSAL = "proposal"
    AUTHORIZATION = "authorization"
    PLAN = "plan"
    LIFECYCLE_TRANSITION = "lifecycle_transition"
    COORDINATION_EVENT = "coordination_event"
    VERIFICATION = "verification"
    OUTCOME = "outcome"


_ARTIFACT_TYPES: Mapping[ExecutionRecordType, type[object]] = MappingProxyType(
    {
        ExecutionRecordType.PROPOSAL: ExecutionProposal,
        ExecutionRecordType.AUTHORIZATION: ExecutionAuthorization,
        ExecutionRecordType.PLAN: ExecutionPlan,
        ExecutionRecordType.LIFECYCLE_TRANSITION: ExecutionStateTransition,
        ExecutionRecordType.COORDINATION_EVENT: ExecutionCoordinationEvent,
        ExecutionRecordType.VERIFICATION: ExecutionVerificationResult,
        ExecutionRecordType.OUTCOME: ExecutionOutcome,
    }
)


def _artifact_id(record_type: ExecutionRecordType, artifact: ExecutionArtifact) -> str:
    attributes = {
        ExecutionRecordType.PROPOSAL: "proposal_id",
        ExecutionRecordType.AUTHORIZATION: "authorization_id",
        ExecutionRecordType.PLAN: "plan_id",
        ExecutionRecordType.LIFECYCLE_TRANSITION: "transition_id",
        ExecutionRecordType.COORDINATION_EVENT: "event_id",
        ExecutionRecordType.VERIFICATION: "verification_id",
        ExecutionRecordType.OUTCOME: "outcome_id",
    }
    return str(getattr(artifact, attributes[record_type]))


class ExecutionRecorder(Protocol):
    """Persistence contract for append-only supervisory execution history."""

    def record_proposal(self, proposal: ExecutionProposal) -> "ExecutionFlightRecord":
        ...

    def record_authorization(
        self, authorization: ExecutionAuthorization
    ) -> "ExecutionFlightRecord":
        ...

    def record_plan(
        self, plan: ExecutionPlan, *, session_id: str | None = None
    ) -> "ExecutionFlightRecord":
        ...

    def record_transition(
        self, transition: ExecutionStateTransition
    ) -> "ExecutionFlightRecord":
        ...

    def record_coordination_event(
        self, event: ExecutionCoordinationEvent
    ) -> "ExecutionFlightRecord":
        ...

    def record_verification(
        self, verification: ExecutionVerificationResult
    ) -> "ExecutionFlightRecord":
        ...

    def record_outcome(self, outcome: ExecutionOutcome) -> "ExecutionFlightRecord":
        ...


@dataclass(frozen=True, slots=True, kw_only=True)
class ExecutionFlightRecord:
    """One immutable artifact entry in an execution timeline."""

    sequence: int
    record_id: str
    record_type: ExecutionRecordType
    occurred_at: datetime
    artifact_id: str
    decision_id: str
    context_id: str
    proposal_id: str
    authorization_id: str | None
    plan_id: str | None
    session_id: str | None
    artifact: ExecutionArtifact
    metadata: Mapping[str, str] = field(default_factory=dict)
    schema_version: int = 1

    def __post_init__(self) -> None:
        if self.sequence < 1:
            raise ValueError("sequence must be at least 1")
        for field_name in (
            "record_id",
            "artifact_id",
            "decision_id",
            "context_id",
            "proposal_id",
        ):
            object.__setattr__(
                self,
                field_name,
                _require_identifier(getattr(self, field_name), field_name),
            )
        for field_name in ("authorization_id", "plan_id", "session_id"):
            value = getattr(self, field_name)
            if value is not None:
                object.__setattr__(
                    self, field_name, _require_identifier(value, field_name)
                )
        _require_aware(self.occurred_at, "occurred_at")
        if self.schema_version < 1:
            raise ValueError("schema_version must be at least 1")
        expected_type = _ARTIFACT_TYPES[self.record_type]
        if not isinstance(self.artifact, expected_type):
            raise TypeError(
                f"{self.record_type.value} records require {expected_type.__name__}"
            )
        if _artifact_id(self.record_type, self.artifact) != self.artifact_id:
            raise ValueError("artifact_id must match the recorded artifact")
        object.__setattr__(self, "metadata", _freeze_string_mapping(self.metadata))

    def to_dict(self) -> dict[str, Any]:
        """Return a deterministic JSON-compatible record snapshot."""

        return {
            "sequence": self.sequence,
            "record_id": self.record_id,
            "record_type": self.record_type.value,
            "occurred_at": self.occurred_at.isoformat(),
            "artifact_id": self.artifact_id,
            "decision_id": self.decision_id,
            "context_id": self.context_id,
            "proposal_id": self.proposal_id,
            "authorization_id": self.authorization_id,
            "plan_id": self.plan_id,
            "session_id": self.session_id,
            "artifact": _json_value(self.artifact),
            "metadata": dict(sorted(self.metadata.items())),
            "schema_version": self.schema_version,
        }


@dataclass(frozen=True, slots=True, kw_only=True)
class ExecutionTimeline:
    """Immutable ordered view of recorded execution history."""

    records: tuple[ExecutionFlightRecord, ...]

    def __post_init__(self) -> None:
        records = tuple(self.records)
        record_ids: set[str] = set()
        artifact_keys: set[tuple[ExecutionRecordType, str]] = set()
        previous_time: datetime | None = None
        for expected_sequence, record in enumerate(records, start=1):
            if record.sequence != expected_sequence:
                raise ValueError("timeline sequences must be contiguous from 1")
            if record.record_id in record_ids:
                raise ValueError("timeline record IDs must be unique")
            artifact_key = (record.record_type, record.artifact_id)
            if artifact_key in artifact_keys:
                raise ValueError("timeline artifacts must not be duplicated")
            if previous_time is not None and record.occurred_at < previous_time:
                raise ValueError("timeline records must be chronologically ordered")
            record_ids.add(record.record_id)
            artifact_keys.add(artifact_key)
            previous_time = record.occurred_at
        object.__setattr__(self, "records", records)

    @property
    def latest(self) -> ExecutionFlightRecord | None:
        """Return the latest recorded execution fact, if present."""

        return self.records[-1] if self.records else None

    def of_type(
        self, record_type: ExecutionRecordType
    ) -> tuple[ExecutionFlightRecord, ...]:
        """Return all records of one artifact type in append order."""

        return tuple(
            record for record in self.records if record.record_type is record_type
        )


@dataclass(slots=True)
class InMemoryExecutionFlightRecorder:
    """Deterministic append-only in-memory execution recorder."""

    _records: list[ExecutionFlightRecord] = field(default_factory=list)
    _proposals: dict[str, ExecutionProposal] = field(default_factory=dict)
    _authorizations: dict[str, ExecutionAuthorization] = field(default_factory=dict)
    _plans: dict[str, ExecutionPlan] = field(default_factory=dict)
    _session_ids: dict[str, str] = field(default_factory=dict)
    _artifact_keys: set[tuple[ExecutionRecordType, str]] = field(
        default_factory=set
    )
    _closed_plans: set[str] = field(default_factory=set)

    def record_proposal(self, proposal: ExecutionProposal) -> ExecutionFlightRecord:
        """Append a proposal as the first fact in its execution lineage."""

        record = self._append(
            record_type=ExecutionRecordType.PROPOSAL,
            artifact=proposal,
            occurred_at=proposal.created_at,
            decision_id=proposal.decision_id,
            context_id=proposal.context_id,
            proposal_id=proposal.proposal_id,
            authorization_id=None,
            plan_id=None,
            session_id=None,
        )
        self._proposals[proposal.proposal_id] = proposal
        return record

    def record_authorization(
        self, authorization: ExecutionAuthorization
    ) -> ExecutionFlightRecord:
        """Append authorization after its proposal has been recorded."""

        proposal = self._require_proposal(authorization.proposal_id)
        if authorization.evaluated_at < proposal.created_at:
            raise ValueError("authorization cannot predate its proposal")
        record = self._append(
            record_type=ExecutionRecordType.AUTHORIZATION,
            artifact=authorization,
            occurred_at=authorization.evaluated_at,
            decision_id=proposal.decision_id,
            context_id=proposal.context_id,
            proposal_id=proposal.proposal_id,
            authorization_id=authorization.authorization_id,
            plan_id=None,
            session_id=None,
        )
        self._authorizations[authorization.authorization_id] = authorization
        return record

    def record_plan(
        self, plan: ExecutionPlan, *, session_id: str | None = None
    ) -> ExecutionFlightRecord:
        """Append an authorized plan and establish its stable session identity."""

        proposal = self._require_proposal(plan.proposal_id)
        authorization = self._require_authorization(plan.authorization_id)
        if authorization.proposal_id != plan.proposal_id:
            raise ValueError("plan authorization must reference the plan proposal")
        if authorization.disposition is not AuthorizationDisposition.AUTHORIZED:
            raise ValueError("only authorized execution plans may be recorded")
        if plan.decision_id != proposal.decision_id:
            raise ValueError("plan decision_id must match the recorded proposal")
        if plan.context_id != proposal.context_id:
            raise ValueError("plan context_id must match the recorded proposal")
        if plan.created_at < authorization.evaluated_at:
            raise ValueError("plan cannot predate its authorization")
        normalized_session_id = (
            _require_identifier(session_id, "session_id")
            if session_id is not None
            else f"execution-session-{plan.plan_id}"
        )
        if normalized_session_id in self._session_ids.values():
            raise ValueError("session_id must be unique")
        record = self._append(
            record_type=ExecutionRecordType.PLAN,
            artifact=plan,
            occurred_at=plan.created_at,
            decision_id=plan.decision_id,
            context_id=plan.context_id,
            proposal_id=plan.proposal_id,
            authorization_id=plan.authorization_id,
            plan_id=plan.plan_id,
            session_id=normalized_session_id,
        )
        self._plans[plan.plan_id] = plan
        self._session_ids[plan.plan_id] = normalized_session_id
        return record

    def record_transition(
        self, transition: ExecutionStateTransition
    ) -> ExecutionFlightRecord:
        """Append one accepted lifecycle transition."""

        plan = self._require_open_plan(transition.plan_id)
        return self._append_for_plan(
            record_type=ExecutionRecordType.LIFECYCLE_TRANSITION,
            artifact=transition,
            occurred_at=transition.occurred_at,
            plan=plan,
        )

    def record_coordination_event(
        self, event: ExecutionCoordinationEvent
    ) -> ExecutionFlightRecord:
        """Append one accepted coordinator event."""

        plan = self._require_open_plan(event.plan_id)
        if event.step_id is not None and event.step_id not in {
            step.step_id for step in plan.steps
        }:
            raise ValueError("coordination event step_id is not part of the plan")
        return self._append_for_plan(
            record_type=ExecutionRecordType.COORDINATION_EVENT,
            artifact=event,
            occurred_at=event.occurred_at,
            plan=plan,
        )

    def record_verification(
        self, verification: ExecutionVerificationResult
    ) -> ExecutionFlightRecord:
        """Append one immutable verification evidence evaluation."""

        plan = self._require_open_plan(verification.plan_id)
        if verification.step_id not in {step.step_id for step in plan.steps}:
            raise ValueError("verification step_id is not part of the plan")
        return self._append_for_plan(
            record_type=ExecutionRecordType.VERIFICATION,
            artifact=verification,
            occurred_at=verification.evaluated_at,
            plan=plan,
        )

    def record_outcome(self, outcome: ExecutionOutcome) -> ExecutionFlightRecord:
        """Append a final or interim execution outcome for one plan."""

        plan = self._require_open_plan(outcome.plan_id)
        if outcome.proposal_id != plan.proposal_id:
            raise ValueError("outcome proposal_id must match the recorded plan")
        if outcome.decision_id != plan.decision_id:
            raise ValueError("outcome decision_id must match the recorded plan")
        if outcome.context_id != plan.context_id:
            raise ValueError("outcome context_id must match the recorded plan")
        plan_step_ids = {step.step_id for step in plan.steps}
        if any(step.step_id not in plan_step_ids for step in outcome.step_outcomes):
            raise ValueError("outcome contains a step that is not part of the plan")
        occurred_at = outcome.completed_at or outcome.started_at
        record = self._append_for_plan(
            record_type=ExecutionRecordType.OUTCOME,
            artifact=outcome,
            occurred_at=occurred_at,
            plan=plan,
        )
        if outcome.completed_at is not None:
            self._closed_plans.add(plan.plan_id)
        return record

    @property
    def records(self) -> tuple[ExecutionFlightRecord, ...]:
        """Return all execution records in append order."""

        return tuple(self._records)

    @property
    def timeline(self) -> ExecutionTimeline:
        """Return an immutable validated view of the complete history."""

        return ExecutionTimeline(records=self.records)

    @property
    def latest(self) -> ExecutionFlightRecord | None:
        """Return the latest record, if present."""

        return self._records[-1] if self._records else None

    def history_for_plan(self, plan_id: str) -> tuple[ExecutionFlightRecord, ...]:
        """Return all plan-scoped records in append order."""

        return tuple(record for record in self._records if record.plan_id == plan_id)

    def history_for_decision(
        self, decision_id: str
    ) -> tuple[ExecutionFlightRecord, ...]:
        """Return all records associated with one decision."""

        return tuple(
            record for record in self._records if record.decision_id == decision_id
        )

    def history_for_session(
        self, session_id: str
    ) -> tuple[ExecutionFlightRecord, ...]:
        """Return all records associated with one execution session."""

        return tuple(
            record for record in self._records if record.session_id == session_id
        )

    def export_json(self) -> str:
        """Export complete execution history as stable compact JSON."""

        return json.dumps(
            [record.to_dict() for record in self._records],
            sort_keys=True,
            separators=(",", ":"),
        )

    def _append_for_plan(
        self,
        *,
        record_type: ExecutionRecordType,
        artifact: ExecutionArtifact,
        occurred_at: datetime,
        plan: ExecutionPlan,
    ) -> ExecutionFlightRecord:
        return self._append(
            record_type=record_type,
            artifact=artifact,
            occurred_at=occurred_at,
            decision_id=plan.decision_id,
            context_id=plan.context_id,
            proposal_id=plan.proposal_id,
            authorization_id=plan.authorization_id,
            plan_id=plan.plan_id,
            session_id=self._session_ids[plan.plan_id],
        )

    def _append(
        self,
        *,
        record_type: ExecutionRecordType,
        artifact: ExecutionArtifact,
        occurred_at: datetime,
        decision_id: str,
        context_id: str,
        proposal_id: str,
        authorization_id: str | None,
        plan_id: str | None,
        session_id: str | None,
    ) -> ExecutionFlightRecord:
        _require_aware(occurred_at, "occurred_at")
        artifact_id = _artifact_id(record_type, artifact)
        artifact_key = (record_type, artifact_id)
        if artifact_key in self._artifact_keys:
            raise ValueError("execution artifact has already been recorded")
        if self._records and occurred_at < self._records[-1].occurred_at:
            raise ValueError("execution records must be appended chronologically")
        sequence = len(self._records) + 1
        payload = {
            "sequence": sequence,
            "record_type": record_type.value,
            "artifact_id": artifact_id,
            "occurred_at": occurred_at.isoformat(),
            "decision_id": decision_id,
            "context_id": context_id,
            "proposal_id": proposal_id,
            "authorization_id": authorization_id,
            "plan_id": plan_id,
            "session_id": session_id,
        }
        record_id = f"execution-record-{sha256(json.dumps(payload, sort_keys=True, separators=(',', ':')).encode()).hexdigest()[:24]}"
        record = ExecutionFlightRecord(
            sequence=sequence,
            record_id=record_id,
            record_type=record_type,
            occurred_at=occurred_at,
            artifact_id=artifact_id,
            decision_id=decision_id,
            context_id=context_id,
            proposal_id=proposal_id,
            authorization_id=authorization_id,
            plan_id=plan_id,
            session_id=session_id,
            artifact=artifact,
        )
        self._records.append(record)
        self._artifact_keys.add(artifact_key)
        return record

    def _require_proposal(self, proposal_id: str) -> ExecutionProposal:
        try:
            return self._proposals[proposal_id]
        except KeyError as exc:
            raise ValueError("proposal must be recorded first") from exc

    def _require_authorization(
        self, authorization_id: str
    ) -> ExecutionAuthorization:
        try:
            return self._authorizations[authorization_id]
        except KeyError as exc:
            raise ValueError("authorization must be recorded first") from exc

    def _require_open_plan(self, plan_id: str) -> ExecutionPlan:
        try:
            plan = self._plans[plan_id]
        except KeyError as exc:
            raise ValueError("plan must be recorded first") from exc
        if plan_id in self._closed_plans:
            raise ValueError("completed execution histories are append-closed")
        return plan
