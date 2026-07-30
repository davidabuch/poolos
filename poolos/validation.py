"""Deterministic scenario validation and golden-rule verification for PoolOS."""

from __future__ import annotations

import hashlib
import json
from collections import Counter
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from types import MappingProxyType
from typing import Any

from .simulation import Simulation, SimulationResult, SimulationScenario


class ValidationStatus(str, Enum):
    """Outcome for one expectation, case, or validation suite."""

    PASSED = "passed"
    FAILED = "failed"
    ERROR = "error"


class ExpectationKind(str, Enum):
    """Built-in assertions supported by the decision-validation runner."""

    FINAL_GRID_AVAILABLE = "final_grid_available"
    FINAL_EQUIPMENT_ACTIVE = "final_equipment_active"
    FINAL_EQUIPMENT_AVAILABLE = "final_equipment_available"
    FINAL_BODY_CIRCULATION = "final_body_circulation"
    FINAL_BODY_HEATING = "final_body_heating"
    FINAL_BODY_TEMPERATURE = "final_body_temperature"
    APPLIED_EVENT_COUNT = "applied_event_count"
    SNAPSHOT_COUNT = "snapshot_count"
    TIMELINE_MONOTONIC = "timeline_monotonic"
    GOLDEN_FINGERPRINT = "golden_fingerprint"


@dataclass(frozen=True, slots=True)
class DecisionExpectation:
    """One serializable expected outcome for a simulation result."""

    kind: ExpectationKind
    expected: Any
    subject_id: str | None = None
    tolerance: float = 0.0
    description: str = ""

    def __post_init__(self) -> None:
        if self.tolerance < 0:
            raise ValueError("expectation tolerance must not be negative")
        subject_required = self.kind in {
            ExpectationKind.FINAL_EQUIPMENT_ACTIVE,
            ExpectationKind.FINAL_EQUIPMENT_AVAILABLE,
            ExpectationKind.FINAL_BODY_CIRCULATION,
            ExpectationKind.FINAL_BODY_HEATING,
            ExpectationKind.FINAL_BODY_TEMPERATURE,
        }
        if subject_required and not (self.subject_id and self.subject_id.strip()):
            raise ValueError(f"{self.kind.value} requires subject_id")
        if self.kind is ExpectationKind.GOLDEN_FINGERPRINT:
            if not isinstance(self.expected, str) or len(self.expected) != 64:
                raise ValueError("golden fingerprint must be a SHA-256 hex digest")


@dataclass(frozen=True, slots=True)
class DecisionValidationCase:
    """A named deterministic scenario and its expected outcomes."""

    name: str
    scenario: SimulationScenario
    expectations: tuple[DecisionExpectation, ...]
    tags: frozenset[str] = frozenset()

    def __post_init__(self) -> None:
        if not self.name.strip():
            raise ValueError("validation case name must not be empty")
        if not self.expectations:
            raise ValueError("validation case requires at least one expectation")
        if any(not tag.strip() for tag in self.tags):
            raise ValueError("validation case tags must not be empty")


@dataclass(frozen=True, slots=True)
class ExpectationResult:
    """Diagnostic result for one expectation."""

    expectation: DecisionExpectation
    status: ValidationStatus
    actual: Any
    message: str


@dataclass(frozen=True, slots=True)
class DecisionValidationReport:
    """Immutable result of running one decision-validation case."""

    case_name: str
    status: ValidationStatus
    started_at: datetime | None
    ended_at: datetime | None
    checks: tuple[ExpectationResult, ...]
    fingerprint: str | None
    error: str | None = None

    @property
    def passed(self) -> bool:
        return self.status is ValidationStatus.PASSED


@dataclass(frozen=True, slots=True)
class DecisionValidationSuiteReport:
    """Aggregate report for a batch of independent validation cases."""

    status: ValidationStatus
    reports: tuple[DecisionValidationReport, ...]
    counts: Mapping[ValidationStatus, int] = field(default_factory=dict)

    def __post_init__(self) -> None:
        object.__setattr__(self, "counts", MappingProxyType(dict(self.counts)))

    @property
    def passed(self) -> bool:
        return self.status is ValidationStatus.PASSED


SimulationFactory = Callable[[], Simulation]


@dataclass(slots=True)
class DecisionValidationRunner:
    """Execute scenario cases against fresh simulator instances."""

    simulation_factory: SimulationFactory

    def run_case(self, case: DecisionValidationCase) -> DecisionValidationReport:
        try:
            simulation = self.simulation_factory()
            result = simulation.run_scenario(case.scenario)
            fingerprint = simulation_fingerprint(result)
            checks = tuple(
                _evaluate_expectation(expectation, result, fingerprint)
                for expectation in case.expectations
            )
        except Exception as exc:
            return DecisionValidationReport(
                case_name=case.name,
                status=ValidationStatus.ERROR,
                started_at=None,
                ended_at=None,
                checks=(),
                fingerprint=None,
                error=f"{type(exc).__name__}: {exc}",
            )
        status = (
            ValidationStatus.PASSED
            if all(check.status is ValidationStatus.PASSED for check in checks)
            else ValidationStatus.FAILED
        )
        return DecisionValidationReport(
            case_name=case.name,
            status=status,
            started_at=result.started_at,
            ended_at=result.ended_at,
            checks=checks,
            fingerprint=fingerprint,
        )

    def run_suite(
        self, cases: Sequence[DecisionValidationCase]
    ) -> DecisionValidationSuiteReport:
        names = [case.name for case in cases]
        if len(names) != len(set(names)):
            raise ValueError("validation case names must be unique within a suite")
        reports = tuple(self.run_case(case) for case in cases)
        counts = Counter(report.status for report in reports)
        if any(report.status is ValidationStatus.ERROR for report in reports):
            status = ValidationStatus.ERROR
        elif any(report.status is ValidationStatus.FAILED for report in reports):
            status = ValidationStatus.FAILED
        else:
            status = ValidationStatus.PASSED
        return DecisionValidationSuiteReport(status, reports, counts)


def simulation_fingerprint(result: SimulationResult) -> str:
    """Return a stable SHA-256 digest of behaviorally relevant simulation state."""

    payload = {
        "started_at": result.started_at.isoformat(),
        "ended_at": result.ended_at.isoformat(),
        "snapshots": [_snapshot_payload(snapshot) for snapshot in result.snapshots],
        "event_kinds": [event.kind.value for event in result.applied_events],
    }
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def _snapshot_payload(snapshot: Any) -> dict[str, Any]:
    return {
        "recorded_at": snapshot.recorded_at.isoformat(),
        "grid_available": snapshot.grid_available,
        "weather": {
            "ambient_temperature": snapshot.weather.ambient_temperature,
            "solar_intensity": snapshot.weather.solar_intensity,
            "wind_factor": snapshot.weather.wind_factor,
        },
        "bodies": {
            body_id: {
                "body": state.body.value,
                "temperature": {
                    "current": state.temperature.current,
                    "target": state.temperature.target,
                    "heating": state.temperature.heating,
                },
                "circulation_running": state.circulation_running,
                "sanitizer_enabled": state.sanitizer_enabled,
            }
            for body_id, state in sorted(snapshot.bodies.items())
        },
        "equipment": {
            equipment_id: {
                "available": state.available,
                "active": state.active,
                "attributes": _normalize(state.attributes),
            }
            for equipment_id, state in sorted(snapshot.equipment.items())
        },
    }


def _normalize(value: Any) -> Any:
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, Enum):
        return value.value
    if isinstance(value, Mapping):
        return {str(key): _normalize(item) for key, item in sorted(value.items(), key=lambda pair: str(pair[0]))}
    if isinstance(value, (list, tuple)):
        return [_normalize(item) for item in value]
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    return repr(value)


def _evaluate_expectation(
    expectation: DecisionExpectation,
    result: SimulationResult,
    fingerprint: str,
) -> ExpectationResult:
    try:
        actual = _actual_value(expectation, result, fingerprint)
    except (KeyError, TypeError, ValueError) as exc:
        return ExpectationResult(
            expectation,
            ValidationStatus.FAILED,
            None,
            f"could not evaluate expectation: {exc}",
        )
    passed = _matches(expectation, actual)
    message = "expectation satisfied" if passed else (
        f"expected {expectation.expected!r}, observed {actual!r}"
    )
    return ExpectationResult(
        expectation,
        ValidationStatus.PASSED if passed else ValidationStatus.FAILED,
        actual,
        message,
    )


def _actual_value(
    expectation: DecisionExpectation,
    result: SimulationResult,
    fingerprint: str,
) -> Any:
    kind = expectation.kind
    subject_id = expectation.subject_id or ""
    if kind is ExpectationKind.FINAL_GRID_AVAILABLE:
        return result.final.grid_available
    if kind is ExpectationKind.FINAL_EQUIPMENT_ACTIVE:
        return result.final.equipment[subject_id].active
    if kind is ExpectationKind.FINAL_EQUIPMENT_AVAILABLE:
        return result.final.equipment[subject_id].available
    if kind is ExpectationKind.FINAL_BODY_CIRCULATION:
        return result.final.bodies[subject_id].circulation_running
    if kind is ExpectationKind.FINAL_BODY_HEATING:
        return result.final.bodies[subject_id].temperature.heating
    if kind is ExpectationKind.FINAL_BODY_TEMPERATURE:
        return result.final.bodies[subject_id].temperature.current
    if kind is ExpectationKind.APPLIED_EVENT_COUNT:
        return len(result.applied_events)
    if kind is ExpectationKind.SNAPSHOT_COUNT:
        return len(result.snapshots)
    if kind is ExpectationKind.TIMELINE_MONOTONIC:
        times = [snapshot.recorded_at for snapshot in result.snapshots]
        return all(first <= second for first, second in zip(times, times[1:]))
    if kind is ExpectationKind.GOLDEN_FINGERPRINT:
        return fingerprint
    raise ValueError(f"unsupported expectation kind: {kind.value}")


def _matches(expectation: DecisionExpectation, actual: Any) -> bool:
    if expectation.kind is ExpectationKind.FINAL_BODY_TEMPERATURE:
        if isinstance(actual, bool) or isinstance(expectation.expected, bool):
            return False
        if not isinstance(actual, (int, float)) or not isinstance(
            expectation.expected, (int, float)
        ):
            return False
        return abs(float(actual) - float(expectation.expected)) <= expectation.tolerance
    return actual == expectation.expected


__all__ = [
    "DecisionExpectation",
    "DecisionValidationCase",
    "DecisionValidationReport",
    "DecisionValidationRunner",
    "DecisionValidationSuiteReport",
    "ExpectationKind",
    "ExpectationResult",
    "ValidationStatus",
    "simulation_fingerprint",
]
