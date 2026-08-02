"""Deterministic persistence and restart recovery for reevaluation state.

The boundary captures immutable scheduling evidence and completed request
identities in a versioned snapshot.  It serializes and restores that snapshot
without performing storage I/O, reading a clock, invoking a runtime, or
submitting evaluation triggers.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from hashlib import sha256
import json
from types import MappingProxyType
from typing import Any, Mapping

from .downstream_operational_action_adapter import (
    DownstreamOperationalActionOutcome,
    DownstreamOperationalActionReason,
    DownstreamOperationalActionReceipt,
)
from .operational_action_pipeline import (
    CanonicalOperationalAction,
    OperationalActionPipelineReason,
    OperationalActionPipelineResult,
    OperationalActionPipelineStatus,
)
from .operational_disposition_orchestrator import OperationalAction, OperationalTarget
from .reevaluation_scheduling import (
    ReevaluationScheduleOutcome,
    ReevaluationScheduleReason,
    ReevaluationScheduleRequest,
    ReevaluationScheduleResult,
)


REEVALUATION_STATE_SCHEMA_VERSION = 2


class ReevaluationStatePersistenceError(ValueError):
    """Persisted reevaluation state is malformed, incompatible, or inconsistent."""


def _canonical_json(value: object) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True)


def _require_aware(value: datetime, field_name: str) -> None:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ReevaluationStatePersistenceError(
            f"{field_name} must be timezone-aware"
        )


def _mapping_payload(value: Mapping[str, str]) -> dict[str, str]:
    return dict(sorted(value.items()))


def _derived_id(prefix: str, payload: object) -> str:
    return prefix + sha256(_canonical_json(payload).encode("utf-8")).hexdigest()[:24]


def _action_payload(action: CanonicalOperationalAction) -> dict[str, object]:
    return {
        "action_id": action.action_id,
        "action": action.action.value,
        "target": action.target.value,
        "context_id": action.context_id,
        "disposition": action.disposition,
        "reason_code": action.reason_code,
        "reason": action.reason,
        "decision_id": action.decision_id,
        "plan_id": action.plan_id,
        "reevaluation_hint": action.reevaluation_hint,
        "correlation_id": action.correlation_id,
        "diagnostics": _mapping_payload(action.diagnostics),
    }


def _pipeline_payload(result: OperationalActionPipelineResult) -> dict[str, object]:
    return {
        "status": result.status.value,
        "reason": result.reason.value,
        "action": _action_payload(result.action),
        "routed_target": result.routed_target.value,
        "boundary_name": result.boundary_name,
        "accepted_action_ids": list(result.accepted_action_ids),
        "diagnostics": _mapping_payload(result.diagnostics),
    }


def _receipt_payload(receipt: DownstreamOperationalActionReceipt) -> dict[str, object]:
    return {
        "receipt_id": receipt.receipt_id,
        "adapter_name": receipt.adapter_name,
        "outcome": receipt.outcome.value,
        "reason": receipt.reason.value,
        "pipeline_result": _pipeline_payload(receipt.pipeline_result),
        "provenance": _mapping_payload(receipt.provenance),
    }


def _request_payload(request: ReevaluationScheduleRequest) -> dict[str, object]:
    return {
        "request_id": request.request_id,
        "receipt": _receipt_payload(request.receipt),
        "requested_at": request.requested_at.isoformat(),
        "scheduled_for": request.scheduled_for.isoformat(),
        "provenance": _mapping_payload(request.provenance),
    }


def _result_payload(result: ReevaluationScheduleResult) -> dict[str, object]:
    return {
        "result_id": result.result_id,
        "outcome": result.outcome.value,
        "reason": result.reason.value,
        "request": _request_payload(result.request),
        "processed_at": result.processed_at.isoformat(),
        "cancellation_reason": result.cancellation_reason,
        "provenance": _mapping_payload(result.provenance),
    }


def _state_payload(
    *,
    captured_at: datetime,
    schedule_results: tuple[ReevaluationScheduleResult, ...],
    completed_request_ids: tuple[str, ...],
    accepted_submission_ids: tuple[str, ...],
) -> dict[str, object]:
    return {
        "schema_version": REEVALUATION_STATE_SCHEMA_VERSION,
        "captured_at": captured_at.isoformat(),
        "schedule_results": [_result_payload(result) for result in schedule_results],
        "completed_request_ids": list(completed_request_ids),
        "accepted_submission_ids": list(accepted_submission_ids),
    }


@dataclass(frozen=True, slots=True)
class ReevaluationStateSnapshot:
    """Immutable restart-safe reevaluation scheduling and completion evidence."""

    captured_at: datetime
    schedule_results: tuple[ReevaluationScheduleResult, ...]
    completed_request_ids: tuple[str, ...]
    accepted_submission_ids: tuple[str, ...] = ()
    schema_version: int = REEVALUATION_STATE_SCHEMA_VERSION
    snapshot_id: str = field(init=False)

    def __post_init__(self) -> None:
        if self.schema_version != REEVALUATION_STATE_SCHEMA_VERSION:
            raise ReevaluationStatePersistenceError(
                "unsupported reevaluation state schema version "
                f"{self.schema_version}; expected {REEVALUATION_STATE_SCHEMA_VERSION}"
            )
        _require_aware(self.captured_at, "captured_at")
        results = tuple(self.schedule_results)
        completed_ids = tuple(self.completed_request_ids)
        accepted_ids = tuple(self.accepted_submission_ids)
        request_ids = tuple(result.request_id for result in results)
        if results != tuple(sorted(results, key=lambda item: item.request_id)):
            raise ReevaluationStatePersistenceError(
                "schedule results must be sorted by request identity"
            )
        if len(set(request_ids)) != len(request_ids):
            raise ReevaluationStatePersistenceError(
                "schedule results must contain unique request identities"
            )
        if any(not request_id.strip() for request_id in completed_ids):
            raise ReevaluationStatePersistenceError(
                "completed request identities must not be empty"
            )
        if completed_ids != tuple(sorted(completed_ids)):
            raise ReevaluationStatePersistenceError(
                "completed request identities must be sorted"
            )
        if len(set(completed_ids)) != len(completed_ids):
            raise ReevaluationStatePersistenceError(
                "completed request identities must be unique"
            )
        if any(not submission_id.strip() for submission_id in accepted_ids):
            raise ReevaluationStatePersistenceError(
                "accepted submission identities must not be empty"
            )
        if accepted_ids != tuple(sorted(accepted_ids)):
            raise ReevaluationStatePersistenceError(
                "accepted submission identities must be sorted"
            )
        if len(set(accepted_ids)) != len(accepted_ids):
            raise ReevaluationStatePersistenceError(
                "accepted submission identities must be unique"
            )
        if any(not self._valid_submission_id(value) for value in accepted_ids):
            raise ReevaluationStatePersistenceError(
                "accepted submission identities must use the canonical format"
            )
        if len(accepted_ids) > len(completed_ids):
            raise ReevaluationStatePersistenceError(
                "accepted submissions cannot exceed emitted reevaluation requests"
            )
        result_by_request = {result.request_id: result for result in results}
        unknown_completed = set(completed_ids) - set(result_by_request)
        if unknown_completed:
            raise ReevaluationStatePersistenceError(
                "completed request identities must reference persisted schedules"
            )
        for result in results:
            self._validate_result(result)
        for request_id in completed_ids:
            result = result_by_request[request_id]
            if result.outcome is ReevaluationScheduleOutcome.CANCELLED:
                raise ReevaluationStatePersistenceError(
                    "cancelled schedules cannot have completion evidence"
                )
            if result.scheduled_for > self.captured_at:
                raise ReevaluationStatePersistenceError(
                    "completed schedules cannot be captured before they are due"
                )
        payload = _state_payload(
            captured_at=self.captured_at,
            schedule_results=results,
            completed_request_ids=completed_ids,
            accepted_submission_ids=accepted_ids,
        )
        snapshot_id = "reevaluation-state-snapshot-" + sha256(
            _canonical_json(payload).encode("utf-8")
        ).hexdigest()[:24]
        object.__setattr__(self, "schedule_results", results)
        object.__setattr__(self, "completed_request_ids", completed_ids)
        object.__setattr__(self, "accepted_submission_ids", accepted_ids)
        object.__setattr__(self, "snapshot_id", snapshot_id)

    @staticmethod
    def _valid_submission_id(value: str) -> bool:
        prefix = "reevaluation-runtime-submission-"
        digest = value.removeprefix(prefix)
        return (
            value.startswith(prefix)
            and len(digest) == 24
            and all(character in "0123456789abcdef" for character in digest)
        )

    def _validate_result(self, result: ReevaluationScheduleResult) -> None:
        if result.outcome not in {
            ReevaluationScheduleOutcome.SCHEDULED,
            ReevaluationScheduleOutcome.CANCELLED,
        }:
            raise ReevaluationStatePersistenceError(
                "only current scheduled or cancelled evidence may be persisted"
            )
        if result.processed_at > self.captured_at:
            raise ReevaluationStatePersistenceError(
                "schedule evidence cannot be captured before it was processed"
            )
        if result.request.requested_at > result.processed_at:
            raise ReevaluationStatePersistenceError(
                "schedule processing cannot precede its request"
            )
        if result.request.scheduled_for < result.request.requested_at:
            raise ReevaluationStatePersistenceError(
                "scheduled time cannot precede its request"
            )
        pipeline = result.request.receipt.pipeline_result
        action = pipeline.action
        expected_action_id = _derived_id(
            "operational-action-",
            {
                "action": action.action.value,
                "context_id": action.context_id,
                "decision_id": action.decision_id,
                "disposition": action.disposition,
                "plan_id": action.plan_id,
                "reason_code": action.reason_code,
                "reevaluation_hint": action.reevaluation_hint,
                "target": action.target.value,
            },
        )
        if action.action_id != expected_action_id:
            raise ReevaluationStatePersistenceError(
                "operational action identity does not match its evidence"
            )
        receipt = result.request.receipt
        expected_receipt_id = _derived_id(
            "downstream-operational-receipt-",
            {
                "action_id": action.action_id,
                "adapter_name": receipt.adapter_name,
                "boundary_name": pipeline.boundary_name,
                "correlation_id": action.correlation_id,
                "outcome": receipt.outcome.value,
                "pipeline_reason": pipeline.reason.value,
                "pipeline_status": pipeline.status.value,
                "reason": receipt.reason.value,
                "target": pipeline.routed_target.value,
            },
        )
        if receipt.receipt_id != expected_receipt_id:
            raise ReevaluationStatePersistenceError(
                "downstream receipt identity does not match its evidence"
            )
        if (
            receipt.outcome is not DownstreamOperationalActionOutcome.DEFERRED
            or receipt.reason
            is not DownstreamOperationalActionReason.REEVALUATION_DEFERRED
            or pipeline.status is not OperationalActionPipelineStatus.ACCEPTED
            or pipeline.reason is not OperationalActionPipelineReason.ROUTE_ACCEPTED
            or action.action_id not in pipeline.accepted_action_ids
            or pipeline.routed_target is not OperationalTarget.REEVALUATION_SCHEDULER
            or pipeline.boundary_name != "reevaluation_scheduler"
            or action.action is not OperationalAction.REQUEST_REEVALUATION
            or action.target is not OperationalTarget.REEVALUATION_SCHEDULER
            or action.reevaluation_hint is None
            or not action.reevaluation_hint.strip()
        ):
            raise ReevaluationStatePersistenceError(
                "persisted schedule does not contain valid reevaluation route evidence"
            )
        scheduler_name = result.provenance.get("reevaluation_scheduler")
        if scheduler_name is None or not scheduler_name.strip():
            raise ReevaluationStatePersistenceError(
                "persisted schedule is missing scheduler identity provenance"
            )
        expected_result_id = _derived_id(
            "reevaluation-schedule-result-",
            {
                "cancellation_reason": result.cancellation_reason,
                "outcome": result.outcome.value,
                "processed_at": result.processed_at.isoformat(),
                "reason": result.reason.value,
                "request_id": result.request_id,
                "scheduler_name": scheduler_name,
            },
        )
        if result.result_id != expected_result_id:
            raise ReevaluationStatePersistenceError(
                "reevaluation schedule result identity does not match its evidence"
            )
        expected_provenance = {
            "reevaluation_request_id": result.request_id,
            "reevaluation_result_id": result.result_id,
            "reevaluation_schedule_outcome": result.outcome.value,
            "reevaluation_schedule_reason": result.reason.value,
            "reevaluation_requested_at": result.request.requested_at.isoformat(),
            "reevaluation_scheduled_for": result.scheduled_for.isoformat(),
            "reevaluation_processed_at": result.processed_at.isoformat(),
            "reevaluation_hint": action.reevaluation_hint,
        }
        if any(
            result.provenance.get(key) != value
            for key, value in expected_provenance.items()
        ):
            raise ReevaluationStatePersistenceError(
                "reevaluation schedule provenance is inconsistent with its evidence"
            )


@dataclass(frozen=True, slots=True)
class ReevaluationStatePersistenceBoundary:
    """Capture and restore versioned state without choosing a storage backend."""

    schema_version: int = REEVALUATION_STATE_SCHEMA_VERSION

    def __post_init__(self) -> None:
        if self.schema_version != REEVALUATION_STATE_SCHEMA_VERSION:
            raise ReevaluationStatePersistenceError(
                "unsupported reevaluation persistence boundary schema version"
            )

    def capture(
        self,
        schedule_results: tuple[ReevaluationScheduleResult, ...],
        *,
        completed_request_ids: tuple[str, ...] = (),
        accepted_submission_ids: tuple[str, ...] = (),
        captured_at: datetime,
    ) -> ReevaluationStateSnapshot:
        """Normalize explicit evidence into one deterministic immutable snapshot."""

        ordered_results = tuple(
            sorted(schedule_results, key=lambda result: result.request_id)
        )
        ordered_completed = tuple(sorted(completed_request_ids))
        ordered_accepted = tuple(sorted(accepted_submission_ids))
        return ReevaluationStateSnapshot(
            captured_at=captured_at,
            schedule_results=ordered_results,
            completed_request_ids=ordered_completed,
            accepted_submission_ids=ordered_accepted,
            schema_version=self.schema_version,
        )

    def serialize(self, snapshot: ReevaluationStateSnapshot) -> str:
        """Return stable compact JSON suitable for a vendor-neutral adapter."""

        if snapshot.schema_version != self.schema_version:
            raise ReevaluationStatePersistenceError(
                "snapshot schema does not match the persistence boundary"
            )
        payload = _state_payload(
            captured_at=snapshot.captured_at,
            schedule_results=snapshot.schedule_results,
            completed_request_ids=snapshot.completed_request_ids,
            accepted_submission_ids=snapshot.accepted_submission_ids,
        )
        payload["snapshot_id"] = snapshot.snapshot_id
        return _canonical_json(payload)

    def restore(self, serialized: str) -> ReevaluationStateSnapshot:
        """Restore equivalent typed state, rejecting invalid evidence fail-closed."""

        try:
            raw = json.loads(serialized)
            root = _require_mapping(raw, "reevaluation state")
            version = _require_int(root, "schema_version")
            if version != self.schema_version:
                raise ReevaluationStatePersistenceError(
                    "unsupported reevaluation state schema version "
                    f"{version}; expected {self.schema_version}"
                )
            raw_results = _require_list(root, "schedule_results")
            snapshot = ReevaluationStateSnapshot(
                captured_at=_require_datetime(root, "captured_at"),
                schedule_results=tuple(
                    _restore_result(_require_mapping(item, "schedule result"))
                    for item in raw_results
                ),
                completed_request_ids=_require_string_tuple(
                    root, "completed_request_ids"
                ),
                accepted_submission_ids=_require_string_tuple(
                    root, "accepted_submission_ids"
                ),
                schema_version=version,
            )
            persisted_snapshot_id = _require_string(root, "snapshot_id")
            if persisted_snapshot_id != snapshot.snapshot_id:
                raise ReevaluationStatePersistenceError(
                    "reevaluation state snapshot identity does not match its evidence"
                )
            expected_keys = {
                "schema_version",
                "snapshot_id",
                "captured_at",
                "schedule_results",
                "completed_request_ids",
                "accepted_submission_ids",
            }
            if set(root) != expected_keys:
                raise ReevaluationStatePersistenceError(
                    "reevaluation state contains unknown or missing fields"
                )
            if _canonical_json(root) != self.serialize(snapshot):
                raise ReevaluationStatePersistenceError(
                    "reevaluation state is not canonical or contains unknown evidence"
                )
            return snapshot
        except ReevaluationStatePersistenceError:
            raise
        except (KeyError, TypeError, ValueError, json.JSONDecodeError) as exc:
            raise ReevaluationStatePersistenceError(
                "malformed persisted reevaluation state"
            ) from exc


def _require_mapping(value: object, field_name: str) -> Mapping[str, Any]:
    if not isinstance(value, dict) or any(not isinstance(key, str) for key in value):
        raise ReevaluationStatePersistenceError(f"{field_name} must be an object")
    return value


def _require_string(mapping: Mapping[str, Any], key: str) -> str:
    value = mapping[key]
    if not isinstance(value, str) or not value.strip():
        raise ReevaluationStatePersistenceError(f"{key} must be a non-empty string")
    return value


def _optional_string(mapping: Mapping[str, Any], key: str) -> str | None:
    value = mapping[key]
    if value is not None and not isinstance(value, str):
        raise ReevaluationStatePersistenceError(f"{key} must be a string or null")
    return value


def _require_int(mapping: Mapping[str, Any], key: str) -> int:
    value = mapping[key]
    if not isinstance(value, int) or isinstance(value, bool):
        raise ReevaluationStatePersistenceError(f"{key} must be an integer")
    return value


def _require_list(mapping: Mapping[str, Any], key: str) -> list[Any]:
    value = mapping[key]
    if not isinstance(value, list):
        raise ReevaluationStatePersistenceError(f"{key} must be an array")
    return value


def _require_string_tuple(
    mapping: Mapping[str, Any], key: str
) -> tuple[str, ...]:
    values = _require_list(mapping, key)
    if any(not isinstance(value, str) for value in values):
        raise ReevaluationStatePersistenceError(f"{key} must contain strings")
    return tuple(values)


def _require_string_mapping(
    mapping: Mapping[str, Any], key: str
) -> Mapping[str, str]:
    value = _require_mapping(mapping[key], key)
    if any(not isinstance(item, str) for item in value.values()):
        raise ReevaluationStatePersistenceError(f"{key} values must be strings")
    return MappingProxyType(dict(value))


def _require_datetime(mapping: Mapping[str, Any], key: str) -> datetime:
    value = _require_string(mapping, key)
    parsed = datetime.fromisoformat(value)
    _require_aware(parsed, key)
    return parsed


def _restore_action(raw: Mapping[str, Any]) -> CanonicalOperationalAction:
    return CanonicalOperationalAction(
        action_id=_require_string(raw, "action_id"),
        action=OperationalAction(_require_string(raw, "action")),
        target=OperationalTarget(_require_string(raw, "target")),
        context_id=_require_string(raw, "context_id"),
        disposition=_require_string(raw, "disposition"),
        reason_code=_require_string(raw, "reason_code"),
        reason=_require_string(raw, "reason"),
        decision_id=_optional_string(raw, "decision_id"),
        plan_id=_optional_string(raw, "plan_id"),
        reevaluation_hint=_optional_string(raw, "reevaluation_hint"),
        correlation_id=_optional_string(raw, "correlation_id"),
        diagnostics=_require_string_mapping(raw, "diagnostics"),
    )


def _restore_pipeline(raw: Mapping[str, Any]) -> OperationalActionPipelineResult:
    return OperationalActionPipelineResult(
        status=OperationalActionPipelineStatus(_require_string(raw, "status")),
        reason=OperationalActionPipelineReason(_require_string(raw, "reason")),
        action=_restore_action(_require_mapping(raw["action"], "action")),
        routed_target=OperationalTarget(_require_string(raw, "routed_target")),
        boundary_name=_optional_string(raw, "boundary_name"),
        accepted_action_ids=_require_string_tuple(raw, "accepted_action_ids"),
        diagnostics=_require_string_mapping(raw, "diagnostics"),
    )


def _restore_receipt(raw: Mapping[str, Any]) -> DownstreamOperationalActionReceipt:
    return DownstreamOperationalActionReceipt(
        receipt_id=_require_string(raw, "receipt_id"),
        adapter_name=_require_string(raw, "adapter_name"),
        outcome=DownstreamOperationalActionOutcome(_require_string(raw, "outcome")),
        reason=DownstreamOperationalActionReason(_require_string(raw, "reason")),
        pipeline_result=_restore_pipeline(
            _require_mapping(raw["pipeline_result"], "pipeline_result")
        ),
        provenance=_require_string_mapping(raw, "provenance"),
    )


def _restore_request(raw: Mapping[str, Any]) -> ReevaluationScheduleRequest:
    request = ReevaluationScheduleRequest(
        receipt=_restore_receipt(_require_mapping(raw["receipt"], "receipt")),
        requested_at=_require_datetime(raw, "requested_at"),
        scheduled_for=_require_datetime(raw, "scheduled_for"),
        provenance=_require_string_mapping(raw, "provenance"),
    )
    if _require_string(raw, "request_id") != request.request_id:
        raise ReevaluationStatePersistenceError(
            "reevaluation request identity does not match its evidence"
        )
    return request


def _restore_result(raw: Mapping[str, Any]) -> ReevaluationScheduleResult:
    return ReevaluationScheduleResult(
        result_id=_require_string(raw, "result_id"),
        outcome=ReevaluationScheduleOutcome(_require_string(raw, "outcome")),
        reason=ReevaluationScheduleReason(_require_string(raw, "reason")),
        request=_restore_request(_require_mapping(raw["request"], "request")),
        processed_at=_require_datetime(raw, "processed_at"),
        cancellation_reason=_optional_string(raw, "cancellation_reason"),
        provenance=_require_string_mapping(raw, "provenance"),
    )
