"""Deterministic shadow parity between HA and native IntelliCenter observations."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from enum import Enum
from hashlib import sha256
import json
import math
from types import MappingProxyType
from typing import Any, Iterable, Mapping

from .observations import PoolObservation

PARITY_DIAGNOSTIC_ISSUE_LIMIT = 40
_DIAGNOSTIC_TEXT_LIMIT = 64

TEMPERATURE_TRANSITION_GRACE = timedelta(seconds=45)
TEMPERATURE_TRANSITION_PARITY_CONCEPTS = frozenset(
    {
        "pool.temperature",
        "spa.temperature",
        "water.temperature",
    }
)


class ObservationParityStatus(str, Enum):
    MATCH = "MATCH"
    VALUE_MISMATCH = "VALUE_MISMATCH"
    MISSING_NATIVE = "MISSING_NATIVE"
    MISSING_HA = "MISSING_HA"
    STALE_NATIVE = "STALE_NATIVE"
    STALE_HA = "STALE_HA"
    TYPE_MISMATCH = "TYPE_MISMATCH"


PARITY_TOLERANCES: Mapping[str, float] = MappingProxyType(
    {
        "air.temperature": 0.5,
        "pool.target_temperature": 0.5,
        "pool.temperature": 1.0,
        "pump.gpm": 1.0,
        "pump.power": 50.0,
        "pump.rpm": 25.0,
        "solar.temperature": 0.5,
        "spa.target_temperature": 0.5,
        "spa.temperature": 1.0,
        "water.temperature": 1.0,
    }
)


@dataclass(frozen=True, slots=True)
class ObservationParityDetail:
    concept: str
    status: ObservationParityStatus
    ha_value: Any
    native_value: Any
    tolerance: float | None
    ha_observed_at: datetime | None
    ha_sampled_at: datetime | None
    native_observed_at: datetime | None
    ha_stale: bool
    native_stale: bool
    ha_source_id: str | None
    native_source_id: str | None

    def to_dict(self) -> dict[str, Any]:
        return {
            "concept": self.concept,
            "status": self.status.value,
            "ha_value": self.ha_value,
            "native_value": self.native_value,
            "tolerance": self.tolerance,
            "ha_observed_at": (
                None if self.ha_observed_at is None else self.ha_observed_at.isoformat()
            ),
            "ha_sampled_at": (
                None if self.ha_sampled_at is None else self.ha_sampled_at.isoformat()
            ),
            "native_observed_at": (
                None
                if self.native_observed_at is None
                else self.native_observed_at.isoformat()
            ),
            "ha_stale": self.ha_stale,
            "native_stale": self.native_stale,
            "ha_source_id": self.ha_source_id,
            "native_source_id": self.native_source_id,
        }


@dataclass(frozen=True, slots=True)
class ObservationParityReport:
    report_id: str
    generated_at: datetime
    native_source_available: bool
    ha_source_available: bool
    compared_concept_count: int
    match_count: int
    mismatch_count: int
    missing_native_count: int
    missing_ha_count: int
    stale_native_count: int
    stale_ha_count: int
    parity_ratio: float
    details: tuple[ObservationParityDetail, ...]
    excluded_concepts: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if self.generated_at.tzinfo is None or self.generated_at.utcoffset() is None:
            raise ValueError("parity generated_at must be timezone-aware")
        object.__setattr__(self, "details", tuple(self.details))
        object.__setattr__(self, "excluded_concepts", tuple(sorted(self.excluded_concepts)))

    def to_dict(self, *, include_details: bool = True) -> dict[str, Any]:
        result: dict[str, Any] = {
            "report_id": self.report_id,
            "generated_at": self.generated_at.isoformat(),
            "native_source_available": self.native_source_available,
            "ha_source_available": self.ha_source_available,
            "compared_concept_count": self.compared_concept_count,
            "match_count": self.match_count,
            "mismatch_count": self.mismatch_count,
            "missing_native_count": self.missing_native_count,
            "missing_ha_count": self.missing_ha_count,
            "stale_native_count": self.stale_native_count,
            "stale_ha_count": self.stale_ha_count,
            "parity_ratio": self.parity_ratio,
            "excluded_concept_count": len(self.excluded_concepts),
            "excluded_concepts": list(self.excluded_concepts),
            "authority": "none",
            "command_delivery_enabled": False,
            "authoritative_source": "home_assistant",
        }
        if include_details:
            result["details"] = [item.to_dict() for item in self.details]
        return result

    def diagnostic_attributes(self) -> dict[str, Any]:
        """Return bounded detail sufficient to diagnose shadow parity failures."""

        issues = tuple(
            item for item in self.details if item.status is not ObservationParityStatus.MATCH
        )
        status_breakdown = {
            status.value: sum(item.status is status for item in self.details)
            for status in ObservationParityStatus
        }
        return {
            **self.to_dict(include_details=False),
            "available": True,
            "status_breakdown": status_breakdown,
            "issue_count": len(issues),
            "displayed_issue_count": min(len(issues), PARITY_DIAGNOSTIC_ISSUE_LIMIT),
            "issues_truncated": len(issues) > PARITY_DIAGNOSTIC_ISSUE_LIMIT,
            "issues": [
                _diagnostic_detail(item)
                for item in issues[:PARITY_DIAGNOSTIC_ISSUE_LIMIT]
            ],
        }


@dataclass(frozen=True, slots=True)
class ObservationParityPolicy:
    stale_after: timedelta = timedelta(minutes=5)
    tolerances: Mapping[str, float] = PARITY_TOLERANCES

    def __post_init__(self) -> None:
        if self.stale_after <= timedelta(0):
            raise ValueError("parity stale_after must be positive")
        normalized = {str(key): float(value) for key, value in self.tolerances.items()}
        if any(value < 0 or not math.isfinite(value) for value in normalized.values()):
            raise ValueError("parity tolerances must be finite and non-negative")
        object.__setattr__(self, "tolerances", MappingProxyType(dict(sorted(normalized.items()))))


class TemperatureParityEligibilityTracker:
    """Gate body/water temperature parity on stable circulation."""

    def __init__(
        self,
        grace_period: timedelta = TEMPERATURE_TRANSITION_GRACE,
    ) -> None:
        if grace_period <= timedelta(0):
            raise ValueError("temperature parity grace period must be positive")

        self.grace_period = grace_period
        self._last_signature: tuple[bool, bool, bool] | None = None
        self._grace_until: datetime | None = None

    def eligible_concepts(
        self,
        base_eligible_concepts: frozenset[str],
        observations: Iterable[PoolObservation],
        *,
        observed_at: datetime,
    ) -> frozenset[str]:
        """Return concepts eligible for parity at one observation time."""

        if observed_at.tzinfo is None or observed_at.utcoffset() is None:
            raise ValueError(
                "temperature parity observed_at must be timezone-aware"
            )

        by_concept = {
            observation.observation_id: observation
            for observation in observations
        }

        signature = (
            _observation_is_true(by_concept.get("pool.active")),
            _observation_is_true(by_concept.get("spa.active")),
            _observation_is_positive(by_concept.get("pump.rpm")),
        )

        if self._last_signature is None:
            # Establish the current hydraulic/body baseline without inventing
            # a transition merely because PoolOS itself restarted.
            self._last_signature = signature
        elif signature != self._last_signature:
            self._last_signature = signature
            self._grace_until = observed_at + self.grace_period

        circulating = signature[2]

        # With no active circulation, the equipment-pad water sensor does not
        # represent current bulk pool/spa water. Retained values from HA and
        # native IntelliCenter may therefore legitimately differ for minutes
        # or hours and are not meaningful parity evidence.
        if not circulating:
            return _without_transition_temperatures(base_eligible_concepts)

        # After circulation/body transitions, allow stagnant plumbing water
        # and asynchronous body/sensor updates to stabilize before comparing
        # the three physical body/water temperature concepts.
        if self._grace_until is not None:
            if observed_at < self._grace_until:
                return _without_transition_temperatures(base_eligible_concepts)

            self._grace_until = None

        return base_eligible_concepts


def _without_transition_temperatures(
    concepts: frozenset[str],
) -> frozenset[str]:
    return frozenset(
        concept
        for concept in concepts
        if concept not in TEMPERATURE_TRANSITION_PARITY_CONCEPTS
    )


def _observation_is_true(
    observation: PoolObservation | None,
) -> bool:
    return observation is not None and observation.value is True


def _observation_is_positive(
    observation: PoolObservation | None,
) -> bool:
    if observation is None:
        return False

    value = observation.value

    if isinstance(value, bool):
        return False

    if not isinstance(value, (int, float)):
        return False

    numeric = float(value)
    return math.isfinite(numeric) and numeric > 0


class ObservationParityEngine:
    """Compare two canonical snapshots without selecting an operational source."""

    def __init__(self, policy: ObservationParityPolicy | None = None) -> None:
        self.policy = policy or ObservationParityPolicy()

    def compare(
        self,
        ha_observations: Iterable[PoolObservation],
        native_observations: Iterable[PoolObservation],
        *,
        generated_at: datetime,
        ha_source_available: bool,
        native_source_available: bool,
        ha_sampled_at_by_concept: Mapping[str, datetime] | None = None,
        eligible_concepts: frozenset[str] | None = None,
    ) -> ObservationParityReport:
        if generated_at.tzinfo is None or generated_at.utcoffset() is None:
            raise ValueError("generated_at must be timezone-aware")
        ha = _by_concept(ha_observations, "HA")
        native = _by_concept(native_observations, "native")
        sampled = _validated_sample_times(ha_sampled_at_by_concept or {})
        all_concepts = set(ha) | set(native)
        concepts = tuple(
            sorted(
                all_concepts
                if eligible_concepts is None
                else all_concepts.intersection(eligible_concepts)
            )
        )
        excluded = tuple(
            sorted(
                ()
                if eligible_concepts is None
                else all_concepts.difference(eligible_concepts)
            )
        )
        details = tuple(
            self._compare_one(
                concept,
                ha.get(concept),
                native.get(concept),
                generated_at,
                ha_sampled_at=sampled.get(concept),
            )
            for concept in concepts
        )
        match_count = sum(item.status is ObservationParityStatus.MATCH for item in details)
        mismatch_count = sum(
            item.status
            in {
                ObservationParityStatus.VALUE_MISMATCH,
                ObservationParityStatus.TYPE_MISMATCH,
            }
            for item in details
        )
        compared = len(details)
        payload = {
            "generated_at": generated_at.isoformat(),
            "native_source_available": native_source_available,
            "ha_source_available": ha_source_available,
            "details": [item.to_dict() for item in details],
            "excluded_concepts": list(excluded),
        }
        report_id = "observation-parity-" + sha256(
            _canonical_json(payload).encode("utf-8")
        ).hexdigest()[:24]
        return ObservationParityReport(
            report_id=report_id,
            generated_at=generated_at,
            native_source_available=native_source_available,
            ha_source_available=ha_source_available,
            compared_concept_count=compared,
            match_count=match_count,
            mismatch_count=mismatch_count,
            missing_native_count=sum(
                item.status is ObservationParityStatus.MISSING_NATIVE for item in details
            ),
            missing_ha_count=sum(
                item.status is ObservationParityStatus.MISSING_HA for item in details
            ),
            stale_native_count=sum(item.native_stale for item in details),
            stale_ha_count=sum(item.ha_stale for item in details),
            parity_ratio=0.0 if compared == 0 else round(match_count / compared, 6),
            details=details,
            excluded_concepts=excluded,
        )

    def _compare_one(
        self,
        concept: str,
        ha: PoolObservation | None,
        native: PoolObservation | None,
        generated_at: datetime,
        *,
        ha_sampled_at: datetime | None,
    ) -> ObservationParityDetail:
        ha_stale = _stale(
            ha,
            generated_at,
            self.policy.stale_after,
            sampled_at=ha_sampled_at,
        )
        native_stale = _stale(native, generated_at, self.policy.stale_after)
        if native is None:
            status = ObservationParityStatus.MISSING_NATIVE
        elif ha is None:
            status = ObservationParityStatus.MISSING_HA
        elif native_stale:
            status = ObservationParityStatus.STALE_NATIVE
        elif ha_stale:
            status = ObservationParityStatus.STALE_HA
        elif not _same_value_type(ha.value, native.value):
            status = ObservationParityStatus.TYPE_MISMATCH
        elif _values_match(
            ha.value,
            native.value,
            tolerance=self.policy.tolerances.get(concept),
        ):
            status = ObservationParityStatus.MATCH
        else:
            status = ObservationParityStatus.VALUE_MISMATCH
        return ObservationParityDetail(
            concept=concept,
            status=status,
            ha_value=None if ha is None else ha.value,
            native_value=None if native is None else native.value,
            tolerance=self.policy.tolerances.get(concept),
            ha_observed_at=None if ha is None else ha.observed_at,
            ha_sampled_at=ha_sampled_at,
            native_observed_at=None if native is None else native.observed_at,
            ha_stale=ha_stale,
            native_stale=native_stale,
            ha_source_id=None if ha is None else ha.source_id,
            native_source_id=None if native is None else native.source_id,
        )


def _by_concept(
    observations: Iterable[PoolObservation], label: str
) -> dict[str, PoolObservation]:
    result: dict[str, PoolObservation] = {}
    for observation in observations:
        if observation.observation_id in result:
            raise ValueError(f"duplicate {label} observation concept")
        result[observation.observation_id] = observation
    return result


def _stale(
    observation: PoolObservation | None,
    generated_at: datetime,
    stale_after: timedelta,
    *,
    sampled_at: datetime | None = None,
) -> bool:
    if observation is None:
        return False
    freshness_timestamp = sampled_at or observation.observed_at
    if freshness_timestamp is None:
        return True
    if freshness_timestamp.tzinfo is None or freshness_timestamp.utcoffset() is None:
        raise ValueError("parity observation timestamps must be timezone-aware")
    return generated_at - freshness_timestamp > stale_after


def _validated_sample_times(
    values: Mapping[str, datetime],
) -> Mapping[str, datetime]:
    result: dict[str, datetime] = {}
    for concept, sampled_at in values.items():
        normalized = concept.strip()
        if not normalized:
            raise ValueError("parity sample concept must not be blank")
        if sampled_at.tzinfo is None or sampled_at.utcoffset() is None:
            raise ValueError("parity sample timestamps must be timezone-aware")
        result[normalized] = sampled_at
    return MappingProxyType(dict(sorted(result.items())))


def _same_value_type(left: Any, right: Any) -> bool:
    if isinstance(left, bool) or isinstance(right, bool):
        return isinstance(left, bool) and isinstance(right, bool)
    if isinstance(left, (int, float)) and isinstance(right, (int, float)):
        return True
    return type(left) is type(right)


def _values_match(left: Any, right: Any, *, tolerance: float | None) -> bool:
    if (
        not isinstance(left, bool)
        and not isinstance(right, bool)
        and isinstance(left, (int, float))
        and isinstance(right, (int, float))
    ):
        allowed = 0.0 if tolerance is None else tolerance
        return math.isclose(float(left), float(right), rel_tol=0.0, abs_tol=allowed)
    return bool(left == right)


def _diagnostic_detail(detail: ObservationParityDetail) -> dict[str, Any]:
    result: dict[str, Any] = {
        "concept": detail.concept,
        "status": detail.status.value,
        "ha_value": _compact_diagnostic_value(detail.ha_value),
        "native_value": _compact_diagnostic_value(detail.native_value),
    }
    if detail.tolerance is not None:
        result["tolerance"] = detail.tolerance
    if detail.ha_observed_at is not None:
        result["ha_observed_at"] = detail.ha_observed_at.isoformat()
    if detail.ha_sampled_at is not None:
        result["ha_sampled_at"] = detail.ha_sampled_at.isoformat()
    if detail.native_observed_at is not None:
        result["native_observed_at"] = detail.native_observed_at.isoformat()
    if detail.ha_source_id is not None:
        result["ha_source_id"] = detail.ha_source_id[:_DIAGNOSTIC_TEXT_LIMIT]
    if detail.native_source_id is not None:
        result["native_source_id"] = detail.native_source_id[
            :_DIAGNOSTIC_TEXT_LIMIT
        ]
    return result


def _compact_diagnostic_value(value: Any) -> Any:
    if isinstance(value, str):
        return value[:_DIAGNOSTIC_TEXT_LIMIT]
    if isinstance(value, (bool, int, float)) or value is None:
        return value
    return str(value)[:_DIAGNOSTIC_TEXT_LIMIT]


def _canonical_json(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False)


__all__ = [
    "PARITY_DIAGNOSTIC_ISSUE_LIMIT",
    "PARITY_TOLERANCES",
    "TEMPERATURE_TRANSITION_GRACE",
    "TEMPERATURE_TRANSITION_PARITY_CONCEPTS",
    "TemperatureParityEligibilityTracker",
    "ObservationParityDetail",
    "ObservationParityEngine",
    "ObservationParityPolicy",
    "ObservationParityReport",
    "ObservationParityStatus",
]
