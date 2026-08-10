"""Deterministic daily operational retrospective and counterfactual reporting.

This module summarizes durable observed PoolOS evidence and compares supported
facts with canonical 11.2 operator-recommendation evidence. It is advisory only:
it creates no commands, execution plans, Home Assistant service calls, vendor
requests, or physical actuation.
"""
from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import UTC, datetime, timedelta
from enum import Enum
from hashlib import sha256
import json
import math
import os
from pathlib import Path
import statistics
from types import MappingProxyType
from typing import Any, Iterable, Mapping

from .behavioral_inference import (
    BehavioralInferenceEngine,
    InferredBehaviorEvent,
    SolarEpisode,
    SolarEpisodeState,
)
from .expected_outage import ExpectedOutageAcknowledgment, intervals_intersect
from .operator_recommendation import OperatorRecommendation, OperatorRecommendationStatus
from .observations import RecordedObservationEvent

SCHEMA_VERSION = "1.0.0"
RETROSPECTIVE_SCHEMA_VERSION = "1.2.0"
_MIN_RUNNING_RPM = 100.0
_MINIMUM_MEDIAN_SAMPLES = 2


class CounterfactualStatus(str, Enum):
    """How completely the available 11.2 advisory evidence supports comparison."""

    NOT_AVAILABLE = "NOT_AVAILABLE"
    NO_CHANGE_RECOMMENDED = "NO_CHANGE_RECOMMENDED"
    CHANGE_RECOMMENDED = "CHANGE_RECOMMENDED"
    ADVISORY_LIMITED = "ADVISORY_LIMITED"


class SoakQualityStatus(str, Enum):
    """Whether one reporting window is trustworthy for behavioral learning."""

    GOOD = "GOOD"
    DEGRADED = "DEGRADED"
    EXCLUDED = "EXCLUDED"


class SoakQualityReason(str, Enum):
    """Stable machine-readable reasons supporting a soak-quality classification."""

    INSUFFICIENT_COVERAGE = "INSUFFICIENT_COVERAGE"
    INSUFFICIENT_HEALTHY_COVERAGE = "INSUFFICIENT_HEALTHY_COVERAGE"
    LARGE_EVIDENCE_GAP = "LARGE_EVIDENCE_GAP"
    OBSERVATION_HEALTH_INCIDENT = "OBSERVATION_HEALTH_INCIDENT"
    REQUIRED_ENTITY_UNAVAILABLE = "REQUIRED_ENTITY_UNAVAILABLE"
    REQUIRED_ENTITY_STALE = "REQUIRED_ENTITY_STALE"
    REQUIRED_MAPPING_MISSING = "REQUIRED_MAPPING_MISSING"
    STARTUP_OR_RESTART_WINDOW = "STARTUP_OR_RESTART_WINDOW"
    COMPLETE_HEALTHY_WINDOW = "COMPLETE_HEALTHY_WINDOW"
    COMPLETE_HEALTHY_DAY = "COMPLETE_HEALTHY_DAY"


class ObservationIncidentState(str, Enum):
    """Whether an observation incident has explicit recovery evidence."""

    OPEN = "OPEN"
    RECOVERED = "RECOVERED"


class ObservationIncidentClassification(str, Enum):
    """Whether an actual incident has durable explanatory context."""

    UNEXPECTED = "UNEXPECTED"
    EXPECTED_OUTAGE = "EXPECTED_OUTAGE"


class SolarLearningQuality(str, Enum):
    """How daily solar evidence may be used for later engineering analysis."""

    INCLUDED = "INCLUDED"
    DEGRADED = "DEGRADED"
    EXCLUDED = "EXCLUDED"
    INSUFFICIENT_EVIDENCE = "INSUFFICIENT_EVIDENCE"


@dataclass(frozen=True, slots=True)
class SoakQualityPolicy:
    """Explicit conservative engineering thresholds; not scientifically validated."""

    good_coverage_ratio: float = 0.95
    exclusion_coverage_ratio: float = 0.75
    maximum_good_gap: timedelta = timedelta(minutes=15)
    exclusion_gap: timedelta = timedelta(hours=2)
    exclusion_unhealthy_duration: timedelta = timedelta(hours=2)
    startup_health_grace: timedelta = timedelta(seconds=60)

    def __post_init__(self) -> None:
        if not 0.0 < self.exclusion_coverage_ratio <= self.good_coverage_ratio <= 1.0:
            raise ValueError("coverage thresholds must satisfy 0 < exclusion <= good <= 1")
        if self.maximum_good_gap <= timedelta(0):
            raise ValueError("maximum_good_gap must be positive")
        if self.exclusion_gap < self.maximum_good_gap:
            raise ValueError("exclusion_gap must not be shorter than maximum_good_gap")
        if self.exclusion_unhealthy_duration <= timedelta(0):
            raise ValueError("exclusion_unhealthy_duration must be positive")
        if self.startup_health_grace <= timedelta(0):
            raise ValueError("startup_health_grace must be positive")


@dataclass(frozen=True, slots=True)
class ObservationIncident:
    """One continuous neutral upstream observation failure or degradation."""

    incident_id: str
    incident_type: str
    state: ObservationIncidentState
    started_at: datetime
    ended_at: datetime | None
    duration_seconds: float
    recovered: bool
    health_state: str
    reasons: tuple[str, ...]
    missing_required: tuple[str, ...]
    unavailable_observations: tuple[str, ...]
    stale_observations: tuple[str, ...]
    source_event_ids: tuple[str, ...]
    expected: bool = False
    classification: ObservationIncidentClassification = (
        ObservationIncidentClassification.UNEXPECTED
    )
    acknowledged_by_operator: bool = False
    acknowledgment_ids: tuple[str, ...] = ()
    matched_acknowledgments: tuple[ExpectedOutageAcknowledgment, ...] = ()
    troubleshooting_required: bool = True

    def to_dict(self) -> dict[str, Any]:
        return {
            "incident_id": self.incident_id,
            "incident_type": self.incident_type,
            "state": self.state.value,
            "started_at": self.started_at.isoformat(),
            "ended_at": None if self.ended_at is None else self.ended_at.isoformat(),
            "duration_seconds": round(self.duration_seconds, 3),
            "recovered": self.recovered,
            "health_state": self.health_state,
            "reasons": list(self.reasons),
            "missing_required": list(self.missing_required),
            "unavailable_observations": list(self.unavailable_observations),
            "stale_observations": list(self.stale_observations),
            "source_event_ids": list(self.source_event_ids),
            "expected": self.expected,
            "classification": self.classification.value,
            "acknowledged_by_operator": self.acknowledged_by_operator,
            "acknowledgment_ids": list(self.acknowledgment_ids),
            "matched_acknowledgments": [
                item.to_dict() for item in self.matched_acknowledgments
            ],
            "troubleshooting_required": self.troubleshooting_required,
        }


@dataclass(frozen=True, slots=True)
class SoakQualityAssessment:
    """Immutable daily observation completeness and health assessment."""

    status: SoakQualityStatus
    observation_coverage_ratio: float
    healthy_observation_coverage_ratio: float
    largest_evidence_gap_seconds: float
    unhealthy_duration_seconds: float
    unavailable_duration_seconds: float
    stale_duration_seconds: float
    unavailable_or_stale_duration_seconds: float
    incident_count: int
    startup_evidence_ids: tuple[str, ...]
    reason_codes: tuple[SoakQualityReason, ...]
    assessment: str
    source_evidence_ids: tuple[str, ...]
    expected_incident_count: int = 0
    unexpected_incident_count: int = 0
    expected_outage_duration_seconds: float = 0.0
    unexpected_unhealthy_duration_seconds: float = 0.0
    commissioning_healthy_coverage_ratio: float = 0.0

    def to_dict(self) -> dict[str, Any]:
        return {
            "status": self.status.value,
            "observation_coverage_ratio": round(self.observation_coverage_ratio, 6),
            "healthy_observation_coverage_ratio": round(
                self.healthy_observation_coverage_ratio, 6
            ),
            "largest_evidence_gap_seconds": round(
                self.largest_evidence_gap_seconds, 3
            ),
            "unhealthy_duration_seconds": round(self.unhealthy_duration_seconds, 3),
            "unavailable_duration_seconds": round(
                self.unavailable_duration_seconds, 3
            ),
            "stale_duration_seconds": round(self.stale_duration_seconds, 3),
            "unavailable_or_stale_duration_seconds": round(
                self.unavailable_or_stale_duration_seconds, 3
            ),
            "incident_count": self.incident_count,
            "startup_evidence_ids": list(self.startup_evidence_ids),
            "reason_codes": [item.value for item in self.reason_codes],
            "assessment": self.assessment,
            "source_evidence_ids": list(self.source_evidence_ids),
            "expected_incident_count": self.expected_incident_count,
            "unexpected_incident_count": self.unexpected_incident_count,
            "expected_outage_duration_seconds": round(
                self.expected_outage_duration_seconds, 3
            ),
            "unexpected_unhealthy_duration_seconds": round(
                self.unexpected_unhealthy_duration_seconds, 3
            ),
            "commissioning_healthy_coverage_ratio": round(
                self.commissioning_healthy_coverage_ratio, 6
            ),
        }


@dataclass(frozen=True, slots=True)
class DailySolarLearningSummary:
    """Daily empirical solar evidence, explicitly separate from control policy."""

    activation_count: int
    deactivation_count: int
    complete_episode_count: int
    open_episode_count: int
    total_observed_runtime_seconds: float
    first_activation_time: datetime | None
    last_deactivation_time: datetime | None
    activation_roof_temperatures_f: tuple[float, ...]
    activation_roof_to_pool_differentials_f: tuple[float, ...]
    deactivation_roof_to_pool_differentials_f: tuple[float, ...]
    median_activation_roof_temperature_f: float | None
    median_activation_differential_f: float | None
    median_deactivation_differential_f: float | None
    provisional_hysteresis_differential_f: float | None
    learning_quality: SolarLearningQuality
    usable_for_learning: bool
    assessment: str
    limitations: tuple[str, ...]
    episodes: tuple[SolarEpisode, ...]
    source_evidence_ids: tuple[str, ...]

    def to_dict(self) -> dict[str, Any]:
        return {
            "activation_count": self.activation_count,
            "deactivation_count": self.deactivation_count,
            "complete_episode_count": self.complete_episode_count,
            "open_episode_count": self.open_episode_count,
            "total_observed_runtime_seconds": round(
                self.total_observed_runtime_seconds, 3
            ),
            "first_activation_time": (
                None
                if self.first_activation_time is None
                else self.first_activation_time.isoformat()
            ),
            "last_deactivation_time": (
                None
                if self.last_deactivation_time is None
                else self.last_deactivation_time.isoformat()
            ),
            "activation_roof_temperatures_f": list(
                self.activation_roof_temperatures_f
            ),
            "activation_roof_to_pool_differentials_f": list(
                self.activation_roof_to_pool_differentials_f
            ),
            "deactivation_roof_to_pool_differentials_f": list(
                self.deactivation_roof_to_pool_differentials_f
            ),
            "median_activation_roof_temperature_f": self.median_activation_roof_temperature_f,
            "median_activation_differential_f": self.median_activation_differential_f,
            "median_deactivation_differential_f": self.median_deactivation_differential_f,
            "provisional_hysteresis_differential_f": self.provisional_hysteresis_differential_f,
            "learning_quality": self.learning_quality.value,
            "usable_for_learning": self.usable_for_learning,
            "assessment": self.assessment,
            "limitations": list(self.limitations),
            "episodes": [item.to_dict() for item in self.episodes],
            "source_evidence_ids": list(self.source_evidence_ids),
            "empirical_evidence_only": True,
            "poolos_control_rule": False,
        }


@dataclass(frozen=True, slots=True)
class TemperatureSummary:
    """Time-weighted temperature evidence for one canonical observation."""

    average_f: float | None
    minimum_f: float | None
    maximum_f: float | None
    covered_seconds: float

    def to_dict(self) -> dict[str, float | None]:
        return {
            "average_f": self.average_f,
            "minimum_f": self.minimum_f,
            "maximum_f": self.maximum_f,
            "covered_seconds": round(self.covered_seconds, 3),
        }


@dataclass(frozen=True, slots=True)
class ActualOperationalMetrics:
    """Observed daily metrics reconstructed from durable evidence."""

    window_start: datetime
    window_end: datetime
    evidence_coverage_seconds: float
    healthy_coverage_seconds: float
    coverage_ratio: float
    pump_runtime_seconds: float
    runtime_by_mode_seconds: Mapping[str, float]
    priming_count: int
    inferred_priming_duration_seconds: float
    spa_runtime_seconds: float
    solar_runtime_seconds: float
    heater_runtime_seconds: float
    filtration_interruptions: int
    average_running_rpm: float | None
    pump_energy_kwh: float | None
    temperatures: Mapping[str, TemperatureSummary]
    source_event_ids: tuple[str, ...]

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "runtime_by_mode_seconds",
            MappingProxyType(dict(sorted(self.runtime_by_mode_seconds.items()))),
        )
        object.__setattr__(
            self,
            "temperatures",
            MappingProxyType(dict(sorted(self.temperatures.items()))),
        )
        object.__setattr__(self, "source_event_ids", tuple(self.source_event_ids))

    def to_dict(self) -> dict[str, Any]:
        return {
            "window_start": self.window_start.isoformat(),
            "window_end": self.window_end.isoformat(),
            "evidence_coverage_seconds": round(self.evidence_coverage_seconds, 3),
            "healthy_coverage_seconds": round(self.healthy_coverage_seconds, 3),
            "coverage_ratio": round(self.coverage_ratio, 3),
            "pump_runtime_seconds": round(self.pump_runtime_seconds, 3),
            "runtime_by_mode_seconds": {
                key: round(value, 3) for key, value in self.runtime_by_mode_seconds.items()
            },
            "priming_count": self.priming_count,
            "inferred_priming_duration_seconds": round(self.inferred_priming_duration_seconds, 3),
            "spa_runtime_seconds": round(self.spa_runtime_seconds, 3),
            "solar_runtime_seconds": round(self.solar_runtime_seconds, 3),
            "heater_runtime_seconds": round(self.heater_runtime_seconds, 3),
            "filtration_interruptions": self.filtration_interruptions,
            "average_running_rpm": _rounded(self.average_running_rpm),
            "pump_energy_kwh": _rounded(self.pump_energy_kwh, digits=4),
            "temperatures": {
                key: summary.to_dict() for key, summary in self.temperatures.items()
            },
            "source_event_count": len(self.source_event_ids),
            "source_event_ids": list(self.source_event_ids),
        }


@dataclass(frozen=True, slots=True)
class CounterfactualDifference:
    """One exact supported difference between observed and advisory evidence."""

    code: str
    actual: float | str | bool | None
    counterfactual: float | str | bool | None
    delta: float | None
    unit: str | None
    explanation: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "code": self.code,
            "actual": self.actual,
            "counterfactual": self.counterfactual,
            "delta": self.delta,
            "unit": self.unit,
            "explanation": self.explanation,
        }


@dataclass(frozen=True, slots=True)
class RecordedRecommendationEvent:
    """One durable canonical 11.2 recommendation snapshot."""

    event_id: str
    published_at: datetime
    recommendation: OperatorRecommendation | None

    def to_dict(self) -> dict[str, Any]:
        return {
            "event_id": self.event_id,
            "published_at": self.published_at.isoformat(),
            "recommendation": None if self.recommendation is None else self.recommendation.to_dict(),
        }


class PersistentRecommendationRecorder:
    """Persist recommendation changes so daily counterfactuals survive restarts."""

    def __init__(self, root: Path | str, *, retention_days: int = 35) -> None:
        if retention_days < 1:
            raise ValueError("retention_days must be at least 1")
        self.root = Path(root)
        self.retention_days = retention_days
        self._last_state_key: str | None = None
        self._started = False
        self._records_written = 0
        self._write_errors = 0
        self._last_error: str | None = None

    def record(self, recommendation: OperatorRecommendation | None, *, published_at: datetime) -> bool:
        if published_at.tzinfo is None or published_at.utcoffset() is None:
            raise ValueError("published_at must be timezone-aware")
        published_at = published_at.astimezone(UTC)
        if not self._started:
            self._restore_last_state()
        state_key = "NONE" if recommendation is None else recommendation.recommendation_id
        if self._last_state_key is None and recommendation is None:
            self._last_state_key = state_key
            return False
        if state_key == self._last_state_key:
            return False
        payload = {
            "schema_version": SCHEMA_VERSION,
            "published_at": published_at.isoformat(),
            "recommendation": None if recommendation is None else recommendation.to_dict(),
        }
        payload["event_id"] = sha256(_canonical_json(payload).encode("utf-8")).hexdigest()
        try:
            self.root.mkdir(parents=True, exist_ok=True)
            path = self.root / f"recommendations-{published_at.date().isoformat()}.jsonl"
            with path.open("a", encoding="utf-8") as handle:
                handle.write(_canonical_json(payload) + "\n")
                handle.flush()
                os.fsync(handle.fileno())
            self._prune(published_at)
        except OSError as exc:
            self._write_errors += 1
            self._last_error = str(exc)
            raise
        self._started = True
        self._last_state_key = state_key
        self._records_written += 1
        self._last_error = None
        return True

    def query(self, *, start: datetime, end: datetime) -> tuple[RecordedRecommendationEvent, ...]:
        _validate_window(start, end)
        records: list[RecordedRecommendationEvent] = []
        if not self.root.exists():
            return ()
        for path in sorted(self.root.glob("recommendations-*.jsonl")):
            with path.open("r", encoding="utf-8") as handle:
                for line in handle:
                    if not line.strip():
                        continue
                    payload = json.loads(line)
                    published_at = datetime.fromisoformat(payload["published_at"])
                    if start <= published_at < end:
                        records.append(_recorded_recommendation(payload))
        return tuple(sorted(records, key=lambda item: (item.published_at, item.event_id)))

    def _restore_last_state(self) -> None:
        """Restore the latest durable recommendation state after a restart."""

        self._started = True
        if not self.root.exists():
            return
        for path in sorted(self.root.glob("recommendations-*.jsonl"), reverse=True):
            lines = [line for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]
            if not lines:
                continue
            payload = json.loads(lines[-1])
            raw_recommendation = payload.get("recommendation")
            if raw_recommendation is None:
                self._last_state_key = "NONE"
            else:
                self._last_state_key = str(raw_recommendation["recommendation_id"])
            return

    def diagnostics(self) -> dict[str, Any]:
        return {
            "schema_version": SCHEMA_VERSION,
            "retention_days": self.retention_days,
            "records_written_this_runtime": self._records_written,
            "write_errors_this_runtime": self._write_errors,
            "last_error": self._last_error,
        }

    def _prune(self, now: datetime) -> None:
        cutoff = now.date() - timedelta(days=self.retention_days - 1)
        for path in self.root.glob("recommendations-*.jsonl"):
            try:
                file_date = datetime.strptime(path.stem.removeprefix("recommendations-"), "%Y-%m-%d").date()
            except ValueError:
                continue
            if file_date < cutoff:
                path.unlink(missing_ok=True)


@dataclass(frozen=True, slots=True)
class CounterfactualReport:
    """Read-only comparison against canonical 11.2 recommendation evidence."""

    status: CounterfactualStatus
    summary: str
    advisory_count: int
    advisory_event_ids: tuple[str, ...]
    recommendation_id: str | None
    recommendation_published_at: datetime | None
    recommendation_status: str | None
    recommendation: str | None
    selected_intent_ids: tuple[str, ...]
    rationale: tuple[str, ...]
    constraints: tuple[str, ...]
    expected_effect: str | None
    confidence: str
    exact_differences: tuple[CounterfactualDifference, ...]
    limitations: tuple[str, ...]

    def to_dict(self) -> dict[str, Any]:
        return {
            "status": self.status.value,
            "summary": self.summary,
            "advisory_count": self.advisory_count,
            "advisory_event_ids": list(self.advisory_event_ids),
            "recommendation_id": self.recommendation_id,
            "recommendation_published_at": (
                None if self.recommendation_published_at is None else self.recommendation_published_at.isoformat()
            ),
            "recommendation_status": self.recommendation_status,
            "recommendation": self.recommendation,
            "selected_intent_ids": list(self.selected_intent_ids),
            "rationale": list(self.rationale),
            "constraints": list(self.constraints),
            "expected_effect": self.expected_effect,
            "confidence": self.confidence,
            "exact_differences": [item.to_dict() for item in self.exact_differences],
            "limitations": list(self.limitations),
            "authority": "none",
            "command_delivery_enabled": False,
        }


@dataclass(frozen=True, slots=True)
class DailyOperationalRetrospective:
    """One deterministic daily observed-vs-counterfactual retrospective."""

    report_id: str
    schema_version: str
    report_date: str
    generated_at: datetime
    complete_day: bool
    actual: ActualOperationalMetrics
    counterfactual: CounterfactualReport
    soak_quality: SoakQualityAssessment
    incidents: tuple[ObservationIncident, ...]
    solar_learning: DailySolarLearningSummary
    daily_assessment: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "report_id": self.report_id,
            "schema_version": self.schema_version,
            "report_date": self.report_date,
            "generated_at": self.generated_at.isoformat(),
            "complete_day": self.complete_day,
            "actual": self.actual.to_dict(),
            "counterfactual": self.counterfactual.to_dict(),
            "soak_quality": self.soak_quality.to_dict(),
            "incidents": [item.to_dict() for item in self.incidents],
            "solar_learning": self.solar_learning.to_dict(),
            "daily_assessment": self.daily_assessment,
            "authority": "none",
            "command_delivery_enabled": False,
        }


@dataclass(frozen=True, slots=True)
class _Frame:
    event: RecordedObservationEvent
    values: Mapping[str, Any]
    units: Mapping[str, str | None]


@dataclass(slots=True)
class _TemperatureAccumulator:
    weighted_sum: float = 0.0
    covered_seconds: float = 0.0
    minimum: float | None = None
    maximum: float | None = None

    def add(self, value: float, seconds: float) -> None:
        if seconds <= 0:
            return
        self.weighted_sum += value * seconds
        self.covered_seconds += seconds
        self.minimum = value if self.minimum is None else min(self.minimum, value)
        self.maximum = value if self.maximum is None else max(self.maximum, value)

    def summary(self) -> TemperatureSummary:
        average = None
        if self.covered_seconds > 0:
            average = self.weighted_sum / self.covered_seconds
        return TemperatureSummary(
            average_f=_rounded(average),
            minimum_f=_rounded(self.minimum),
            maximum_f=_rounded(self.maximum),
            covered_seconds=self.covered_seconds,
        )


class DailyOperationalRetrospectiveEngine:
    """Build daily summaries from durable evidence without crossing control boundaries."""

    def __init__(
        self,
        *,
        maximum_evidence_gap: timedelta = timedelta(minutes=15),
        soak_quality_policy: SoakQualityPolicy | None = None,
    ) -> None:
        if maximum_evidence_gap <= timedelta(0):
            raise ValueError("maximum_evidence_gap must be positive")
        self.maximum_evidence_gap = maximum_evidence_gap
        self.soak_quality_policy = soak_quality_policy or SoakQualityPolicy()
        self._behavioral = BehavioralInferenceEngine()

    def generate(
        self,
        records: Iterable[RecordedObservationEvent],
        *,
        window_start: datetime,
        window_end: datetime,
        report_date: str,
        advisories: Iterable[RecordedRecommendationEvent] = (),
        recommendation: OperatorRecommendation | None = None,
        expected_outage_acknowledgments: Iterable[
            ExpectedOutageAcknowledgment
        ] = (),
        complete_day: bool,
    ) -> DailyOperationalRetrospective:
        """Generate one deterministic retrospective for the explicit reporting window."""

        _validate_window(window_start, window_end)
        evidence = tuple(records)
        if any(
            item.recorded_at.tzinfo is None or item.recorded_at.utcoffset() is None
            for item in evidence
        ):
            raise ValueError("retrospective evidence timestamps must be timezone-aware")
        ordered = tuple(
            sorted(evidence, key=lambda item: (item.recorded_at, item.event_id))
        )
        acknowledgments = tuple(
            sorted(
                expected_outage_acknowledgments,
                key=lambda item: (item.acknowledged_at, item.acknowledgment_id),
            )
        )
        actual = self._actual_metrics(ordered, window_start=window_start, window_end=window_end)
        raw_incidents = _observation_incidents(
            ordered,
            window_start=window_start,
            window_end=window_end,
            maximum_evidence_gap=self.maximum_evidence_gap,
            startup_health_grace=self.soak_quality_policy.startup_health_grace,
        )
        incidents = _classify_expected_outages(
            raw_incidents,
            acknowledgments=acknowledgments,
            window_end=window_end,
        )
        soak_quality = _soak_quality(
            ordered,
            actual=actual,
            incidents=incidents,
            window_start=window_start,
            window_end=window_end,
            maximum_evidence_gap=self.maximum_evidence_gap,
            policy=self.soak_quality_policy,
            complete_day=complete_day,
        )
        inference_records = tuple(
            item
            for item in ordered
            if window_start - self.maximum_evidence_gap <= item.recorded_at < window_end
        )
        inference = self._behavioral.infer(inference_records)
        solar_learning = _daily_solar_learning(
            inference.events,
            inference.solar_episodes,
            actual=actual,
            soak_quality=soak_quality,
            window_start=window_start,
            window_end=window_end,
            excluded_evidence_ids=frozenset(
                event_id
                for incident in incidents
                if incident.expected
                for event_id in incident.source_event_ids
            ),
            excluded_intervals=tuple(
                (incident.started_at, incident.ended_at or window_end)
                for incident in incidents
                if incident.expected
            ),
        )
        daily_assessment = _daily_assessment(soak_quality, solar_learning)
        ordered_advisories = tuple(
            sorted(
                (item for item in advisories if window_start <= item.published_at < window_end),
                key=lambda item: (item.published_at, item.event_id),
            )
        )
        counterfactual = _counterfactual(actual, ordered_advisories, recommendation)
        generated_at = window_end
        identity_payload = {
            "schema_version": RETROSPECTIVE_SCHEMA_VERSION,
            "report_date": report_date,
            "generated_at": generated_at.isoformat(),
            "complete_day": complete_day,
            "actual": actual.to_dict(),
            "counterfactual": counterfactual.to_dict(),
            "soak_quality": soak_quality.to_dict(),
            "incidents": [item.to_dict() for item in incidents],
            "solar_learning": solar_learning.to_dict(),
            "daily_assessment": daily_assessment,
        }
        report_id = "daily-retrospective-" + sha256(_canonical_json(identity_payload).encode("utf-8")).hexdigest()[:24]
        return DailyOperationalRetrospective(
            report_id=report_id,
            schema_version=RETROSPECTIVE_SCHEMA_VERSION,
            report_date=report_date,
            generated_at=generated_at,
            complete_day=complete_day,
            actual=actual,
            counterfactual=counterfactual,
            soak_quality=soak_quality,
            incidents=incidents,
            solar_learning=solar_learning,
            daily_assessment=daily_assessment,
        )

    def _actual_metrics(
        self,
        records: tuple[RecordedObservationEvent, ...],
        *,
        window_start: datetime,
        window_end: datetime,
    ) -> ActualOperationalMetrics:
        frames = tuple(_frame(item) for item in records if item.recorded_at < window_end)
        if not frames:
            return _empty_actual(window_start, window_end)

        startup_grace_intervals = _startup_grace_intervals(
            tuple(frame.event for frame in frames),
            window_start=window_start,
            window_end=window_end,
            startup_health_grace=self.soak_quality_policy.startup_health_grace,
        )

        seed_index = _seed_index(frames, window_start)
        if (
            seed_index is not None
            and frames[seed_index].event.recorded_at < window_start - self.maximum_evidence_gap
        ):
            seed_index = None
        if seed_index is None:
            seed_index = next(
                (index for index, frame in enumerate(frames) if frame.event.recorded_at >= window_start),
                None,
            )
        if seed_index is None:
            return _empty_actual(window_start, window_end)

        inference_records = tuple(
            frame.event
            for frame in frames
            if frame.event.recorded_at < window_end
            and frame.event.recorded_at >= window_start - self.maximum_evidence_gap
        )
        inferred = self._behavioral.infer(inference_records)
        priming_events = tuple(
            item
            for item in inferred.events
            if item.kind == "PUMP_PRIMING_INFERRED" and window_start <= item.occurred_at < window_end
        )
        priming_ranges = _priming_ranges(priming_events, window_start=window_start, window_end=window_end)

        coverage = 0.0
        healthy_coverage = 0.0
        pump_runtime = 0.0
        runtime_by_mode: dict[str, float] = {}
        spa_runtime = 0.0
        solar_runtime = 0.0
        heater_runtime = 0.0
        rpm_weighted = 0.0
        rpm_covered = 0.0
        energy_kwh = 0.0
        energy_covered = 0.0
        used_event_ids: list[str] = []
        temps = {
            "pool.temperature": _TemperatureAccumulator(),
            "spa.temperature": _TemperatureAccumulator(),
            "solar.temperature": _TemperatureAccumulator(),
            "air.temperature": _TemperatureAccumulator(),
        }

        for index in range(seed_index, len(frames)):
            frame = frames[index]
            if frame.event.recorded_at >= window_end:
                break
            interval_start = max(frame.event.recorded_at, window_start)
            if index == seed_index and frame.event.recorded_at <= window_start:
                interval_start = window_start
            next_at = window_end
            if index + 1 < len(frames):
                next_at = min(next_at, frames[index + 1].event.recorded_at)
            natural_seconds = max(0.0, (next_at - interval_start).total_seconds())
            seconds = min(natural_seconds, self.maximum_evidence_gap.total_seconds())
            if seconds <= 0:
                continue

            used_event_ids.append(frame.event.event_id)
            coverage += seconds
            if bool(frame.event.health.get("healthy", False)):
                healthy_coverage += seconds
            else:
                effective_end = interval_start + timedelta(seconds=seconds)
                healthy_coverage += seconds - _duration_outside_intervals(
                    interval_start,
                    effective_end,
                    startup_grace_intervals,
                )

            values = frame.values
            rpm = _number(values.get("pump.rpm"))
            running = rpm is not None and rpm >= _MIN_RUNNING_RPM
            mode = _mode(values, rpm)
            if running:
                assert rpm is not None
                pump_runtime += seconds
                effective_end = interval_start + timedelta(seconds=seconds)
                priming_overlap = _ranges_overlap_seconds(
                    interval_start,
                    effective_end,
                    priming_ranges,
                )
                if priming_overlap > 0:
                    runtime_by_mode["PRIMING"] = runtime_by_mode.get("PRIMING", 0.0) + priming_overlap
                base_mode_seconds = max(0.0, seconds - priming_overlap)
                if base_mode_seconds > 0:
                    runtime_by_mode[mode] = runtime_by_mode.get(mode, 0.0) + base_mode_seconds
                rpm_weighted += rpm * seconds
                rpm_covered += seconds
            if _boolean(values.get("spa.active")) is True:
                spa_runtime += seconds
            if _boolean(values.get("solar.active")) is True:
                solar_runtime += seconds
            if _boolean(values.get("heater.active")) is True:
                heater_runtime += seconds

            power = _number(values.get("pump.power"))
            power_unit = frame.units.get("pump.power")
            if power is not None and power >= 0 and power_unit in {"W", "kW"}:
                watts = power if power_unit == "W" else power * 1000.0
                energy_kwh += watts * seconds / 3_600_000.0
                energy_covered += seconds

            for observation_id, accumulator in temps.items():
                value = _number(values.get(observation_id))
                if value is not None:
                    accumulator.add(value, seconds)

        priming_seconds = sum((end - start).total_seconds() for start, end in priming_ranges)
        for item in priming_events:
            for event_id in item.evidence_event_ids:
                if event_id not in used_event_ids:
                    used_event_ids.append(event_id)

        interruptions = _filtration_interruptions(
            frames,
            window_start,
            window_end,
            maximum_evidence_gap=self.maximum_evidence_gap,
        )
        window_seconds = (window_end - window_start).total_seconds()
        return ActualOperationalMetrics(
            window_start=window_start,
            window_end=window_end,
            evidence_coverage_seconds=coverage,
            healthy_coverage_seconds=healthy_coverage,
            coverage_ratio=0.0 if window_seconds <= 0 else min(1.0, coverage / window_seconds),
            pump_runtime_seconds=pump_runtime,
            runtime_by_mode_seconds=runtime_by_mode,
            priming_count=len(priming_events),
            inferred_priming_duration_seconds=priming_seconds,
            spa_runtime_seconds=spa_runtime,
            solar_runtime_seconds=solar_runtime,
            heater_runtime_seconds=heater_runtime,
            filtration_interruptions=interruptions,
            average_running_rpm=None if rpm_covered <= 0 else rpm_weighted / rpm_covered,
            pump_energy_kwh=None if energy_covered <= 0 else energy_kwh,
            temperatures={key: accumulator.summary() for key, accumulator in temps.items()},
            source_event_ids=tuple(used_event_ids),
        )


def _observation_incidents(
    records: tuple[RecordedObservationEvent, ...],
    *,
    window_start: datetime,
    window_end: datetime,
    maximum_evidence_gap: timedelta,
    startup_health_grace: timedelta,
) -> tuple[ObservationIncident, ...]:
    relevant = _relevant_records(
        records,
        window_start=window_start,
        window_end=window_end,
        maximum_evidence_gap=maximum_evidence_gap,
    )
    spans = _supported_spans(
        records,
        window_start=window_start,
        window_end=window_end,
        maximum_evidence_gap=maximum_evidence_gap,
    )
    supported_end_by_event = {record.event_id: end for record, _, end in spans}
    grace_intervals = _startup_grace_intervals(
        records,
        window_start=window_start,
        window_end=window_end,
        startup_health_grace=startup_health_grace,
    )
    incidents: list[ObservationIncident] = []
    active: dict[str, Any] | None = None
    for record in relevant:
        issue_reasons = _health_reasons(record)
        if not issue_reasons:
            if active is not None and bool(record.health.get("healthy", False)):
                active["source_ids"].append(record.event_id)
                incidents.append(
                    _build_incident(
                        active,
                        ended_at=record.recorded_at,
                        window_end=window_end,
                    )
                )
                active = None
            continue
        issue_start = max(record.recorded_at, window_start)
        grace_end = _containing_grace_end(record.recorded_at, grace_intervals)
        if grace_end is not None:
            supported_end = supported_end_by_event.get(
                record.event_id, record.recorded_at
            )
            if supported_end <= grace_end:
                continue
            issue_start = max(grace_end, window_start)
        if active is None:
            active = {
                "started_at": issue_start,
                "reasons": set(),
                "missing": set(),
                "unavailable": set(),
                "stale": set(),
                "source_ids": [],
                "unhealthy": False,
            }
        active["reasons"].update(issue_reasons)
        active["missing"].update(_health_values(record, "missing_required"))
        active["unavailable"].update(
            _health_values(record, "unavailable_entities")
        )
        active["stale"].update(_health_values(record, "stale_entities"))
        active["source_ids"].append(record.event_id)
        active["unhealthy"] = active["unhealthy"] or not bool(
            record.health.get("healthy", False)
        )
    if active is not None:
        incidents.append(_build_incident(active, ended_at=None, window_end=window_end))
    return tuple(incidents)


def _build_incident(
    evidence: dict[str, Any],
    *,
    ended_at: datetime | None,
    window_end: datetime,
) -> ObservationIncident:
    started_at = evidence["started_at"]
    duration_end = window_end if ended_at is None else min(ended_at, window_end)
    source_ids = tuple(dict.fromkeys(str(item) for item in evidence["source_ids"]))
    reasons = tuple(sorted(str(item) for item in evidence["reasons"]))
    payload = {
        "incident_type": "UPSTREAM_OBSERVATION_FAILURE",
        "started_at": started_at.isoformat(),
        "first_source_event_id": source_ids[0],
    }
    incident_id = "observation-incident-" + sha256(
        _canonical_json(payload).encode("utf-8")
    ).hexdigest()[:24]
    recovered = ended_at is not None
    return ObservationIncident(
        incident_id=incident_id,
        incident_type="UPSTREAM_OBSERVATION_FAILURE",
        state=(
            ObservationIncidentState.RECOVERED
            if recovered
            else ObservationIncidentState.OPEN
        ),
        started_at=started_at,
        ended_at=ended_at,
        duration_seconds=max(0.0, (duration_end - started_at).total_seconds()),
        recovered=recovered,
        health_state="UNHEALTHY" if evidence["unhealthy"] else "DEGRADED",
        reasons=reasons,
        missing_required=tuple(sorted(evidence["missing"])),
        unavailable_observations=tuple(sorted(evidence["unavailable"])),
        stale_observations=tuple(sorted(evidence["stale"])),
        source_event_ids=source_ids,
    )


def _classify_expected_outages(
    incidents: tuple[ObservationIncident, ...],
    *,
    acknowledgments: tuple[ExpectedOutageAcknowledgment, ...],
    window_end: datetime,
) -> tuple[ObservationIncident, ...]:
    """Add operator context after raw incident construction and startup calibration."""

    classified: list[ObservationIncident] = []
    for incident in incidents:
        incident_end = incident.ended_at or window_end
        matched = tuple(
            acknowledgment
            for acknowledgment in acknowledgments
            if intervals_intersect(
                incident.started_at,
                incident_end,
                acknowledgment.matching_window_start,
                acknowledgment.matching_window_end,
            )
        )
        if not matched:
            classified.append(incident)
            continue
        classified.append(
            replace(
                incident,
                expected=True,
                classification=ObservationIncidentClassification.EXPECTED_OUTAGE,
                acknowledged_by_operator=True,
                acknowledgment_ids=tuple(
                    item.acknowledgment_id for item in matched
                ),
                matched_acknowledgments=matched,
                troubleshooting_required=False,
            )
        )
    return tuple(classified)


def _soak_quality(
    records: tuple[RecordedObservationEvent, ...],
    *,
    actual: ActualOperationalMetrics,
    incidents: tuple[ObservationIncident, ...],
    window_start: datetime,
    window_end: datetime,
    maximum_evidence_gap: timedelta,
    policy: SoakQualityPolicy,
    complete_day: bool,
) -> SoakQualityAssessment:
    window_seconds = (window_end - window_start).total_seconds()
    spans = _supported_spans(
        records,
        window_start=window_start,
        window_end=window_end,
        maximum_evidence_gap=maximum_evidence_gap,
    )
    grace_intervals = _startup_grace_intervals(
        records,
        window_start=window_start,
        window_end=window_end,
        startup_health_grace=policy.startup_health_grace,
    )
    expected_intervals = tuple(
        (incident.started_at, incident.ended_at or window_end)
        for incident in incidents
        if incident.expected
    )
    commissioning_exclusions = _merge_intervals(
        (*grace_intervals, *expected_intervals)
    )
    unhealthy_duration = sum(
        _duration_outside_intervals(start, end, grace_intervals)
        for record, start, end in spans
        if not bool(record.health.get("healthy", False))
    )
    raw_effective_healthy_coverage = sum(
        (end - start).total_seconds()
        if bool(record.health.get("healthy", False))
        else (end - start).total_seconds()
        - _duration_outside_intervals(start, end, grace_intervals)
        for record, start, end in spans
    )
    commissioning_effective_healthy_coverage = sum(
        (end - start).total_seconds()
        if bool(record.health.get("healthy", False))
        else (end - start).total_seconds()
        - _duration_outside_intervals(start, end, commissioning_exclusions)
        for record, start, end in spans
    )
    raw_healthy_ratio = (
        0.0
        if window_seconds <= 0
        else min(1.0, raw_effective_healthy_coverage / window_seconds)
    )
    commissioning_healthy_ratio = (
        0.0
        if window_seconds <= 0
        else min(1.0, commissioning_effective_healthy_coverage / window_seconds)
    )
    largest_gap = _largest_uncovered_gap(spans, window_start, window_end)
    unavailable_duration = sum(
        _duration_outside_intervals(start, end, grace_intervals)
        for record, start, end in spans
        if not bool(record.health.get("healthy", False))
        and _health_values(record, "unavailable_entities")
    )
    stale_duration = sum(
        _duration_outside_intervals(start, end, grace_intervals)
        for record, start, end in spans
        if not bool(record.health.get("healthy", False))
        and _health_values(record, "stale_entities")
    )
    unavailable_or_stale_duration = sum(
        _duration_outside_intervals(start, end, grace_intervals)
        for record, start, end in spans
        if not bool(record.health.get("healthy", False))
        and (
            _health_values(record, "unavailable_entities")
            or _health_values(record, "stale_entities")
        )
    )
    startup_ids = tuple(
        item.event_id
        for item in records
        if window_start <= item.recorded_at < window_end and item.kind == "baseline"
    )
    unexpected_incidents = tuple(item for item in incidents if not item.expected)
    all_reasons = {
        reason for incident in unexpected_incidents for reason in incident.reasons
    }
    reason_codes: list[SoakQualityReason] = []
    if actual.coverage_ratio < policy.good_coverage_ratio:
        reason_codes.append(SoakQualityReason.INSUFFICIENT_COVERAGE)
    if commissioning_healthy_ratio < policy.good_coverage_ratio:
        reason_codes.append(SoakQualityReason.INSUFFICIENT_HEALTHY_COVERAGE)
    if largest_gap > policy.maximum_good_gap.total_seconds():
        reason_codes.append(SoakQualityReason.LARGE_EVIDENCE_GAP)
    if unexpected_incidents:
        reason_codes.append(SoakQualityReason.OBSERVATION_HEALTH_INCIDENT)
    for value in (
        SoakQualityReason.REQUIRED_ENTITY_UNAVAILABLE,
        SoakQualityReason.REQUIRED_ENTITY_STALE,
        SoakQualityReason.REQUIRED_MAPPING_MISSING,
    ):
        if value.value in all_reasons:
            reason_codes.append(value)
    if startup_ids:
        reason_codes.append(SoakQualityReason.STARTUP_OR_RESTART_WINDOW)

    excluded = any(
        (
            actual.coverage_ratio < policy.exclusion_coverage_ratio,
            commissioning_healthy_ratio < policy.exclusion_coverage_ratio,
            largest_gap >= policy.exclusion_gap.total_seconds(),
            sum(
                _duration_outside_intervals(
                    start, end, commissioning_exclusions
                )
                for record, start, end in spans
                if not bool(record.health.get("healthy", False))
            )
            >= policy.exclusion_unhealthy_duration.total_seconds(),
        )
    )
    if excluded:
        status = SoakQualityStatus.EXCLUDED
    elif any(
        reason is not SoakQualityReason.STARTUP_OR_RESTART_WINDOW
        for reason in reason_codes
    ):
        status = SoakQualityStatus.DEGRADED
    else:
        status = SoakQualityStatus.GOOD
        reason_codes.append(
            SoakQualityReason.COMPLETE_HEALTHY_DAY
            if complete_day
            else SoakQualityReason.COMPLETE_HEALTHY_WINDOW
        )
    assessment = (
        f"Observation quality {status.value}: {actual.coverage_ratio * 100:.1f}% "
        f"coverage, {len(unexpected_incidents)} unexpected and "
        f"{len(incidents) - len(unexpected_incidents)} expected observation incidents."
    )
    source_ids = tuple(dict.fromkeys(record.event_id for record, _, _ in spans))
    return SoakQualityAssessment(
        status=status,
        observation_coverage_ratio=actual.coverage_ratio,
        healthy_observation_coverage_ratio=raw_healthy_ratio,
        largest_evidence_gap_seconds=largest_gap,
        unhealthy_duration_seconds=unhealthy_duration,
        unavailable_duration_seconds=unavailable_duration,
        stale_duration_seconds=stale_duration,
        unavailable_or_stale_duration_seconds=unavailable_or_stale_duration,
        incident_count=len(incidents),
        startup_evidence_ids=startup_ids,
        reason_codes=tuple(reason_codes),
        assessment=assessment,
        source_evidence_ids=source_ids,
        expected_incident_count=len(incidents) - len(unexpected_incidents),
        unexpected_incident_count=len(unexpected_incidents),
        expected_outage_duration_seconds=sum(
            item.duration_seconds for item in incidents if item.expected
        ),
        unexpected_unhealthy_duration_seconds=sum(
            _duration_outside_intervals(start, end, commissioning_exclusions)
            for record, start, end in spans
            if not bool(record.health.get("healthy", False))
        ),
        commissioning_healthy_coverage_ratio=commissioning_healthy_ratio,
    )


def _daily_solar_learning(
    events: tuple[InferredBehaviorEvent, ...],
    episodes: tuple[SolarEpisode, ...],
    *,
    actual: ActualOperationalMetrics,
    soak_quality: SoakQualityAssessment,
    window_start: datetime,
    window_end: datetime,
    excluded_evidence_ids: frozenset[str] = frozenset(),
    excluded_intervals: tuple[tuple[datetime, datetime], ...] = (),
) -> DailySolarLearningSummary:
    transitions = tuple(
        item
        for item in events
        if item.kind in {"SOLAR_ACTIVATED", "SOLAR_DEACTIVATED"}
        and window_start <= item.occurred_at < window_end
        and not excluded_evidence_ids.intersection(item.evidence_event_ids)
        and not _timestamp_in_intervals(item.occurred_at, excluded_intervals)
    )
    activations = tuple(item for item in transitions if item.kind == "SOLAR_ACTIVATED")
    deactivations = tuple(
        item for item in transitions if item.kind == "SOLAR_DEACTIVATED"
    )
    daily_episodes = tuple(
        item
        for item in episodes
        if window_start <= item.activation_time < window_end
        and not excluded_evidence_ids.intersection(item.source_event_ids)
        and not _episode_intersects_intervals(item, excluded_intervals, window_end)
    )
    complete = tuple(
        item for item in daily_episodes if item.state is SolarEpisodeState.CLOSED
    )
    activation_roofs = _attribute_values(activations, "solar_temperature_f")
    activation_diffs = _attribute_values(
        activations, "roof_to_pool_differential_f"
    )
    deactivation_diffs = _attribute_values(
        deactivations, "roof_to_pool_differential_f"
    )
    activation_median = _supported_median(activation_diffs)
    deactivation_median = _supported_median(deactivation_diffs)
    hysteresis = (
        None
        if activation_median is None or deactivation_median is None
        else round(activation_median - deactivation_median, 3)
    )
    if not complete:
        quality = SolarLearningQuality.INSUFFICIENT_EVIDENCE
        usable = False
    elif soak_quality.status is SoakQualityStatus.EXCLUDED:
        quality = SolarLearningQuality.EXCLUDED
        usable = False
    elif soak_quality.status is SoakQualityStatus.DEGRADED:
        quality = SolarLearningQuality.DEGRADED
        usable = True
    else:
        quality = SolarLearningQuality.INCLUDED
        usable = True

    limitations = [
        "Observed solar behavior is empirical Pentair evidence, not a PoolOS control rule.",
        "Transition medians require at least two available samples; missing values are not imputed.",
    ]
    if soak_quality.status is SoakQualityStatus.EXCLUDED:
        limitations.append(
            "This reporting window is excluded from behavioral-learning conclusions by soak quality."
        )
    elif soak_quality.status is SoakQualityStatus.DEGRADED:
        limitations.append(
            "This reporting window is degraded and requires review before cross-day learning."
        )
    if any(item.state is SolarEpisodeState.OPEN for item in daily_episodes):
        limitations.append(
            "At least one activation has no observed deactivation in this reporting window."
        )
    if not complete:
        assessment = "No complete solar episode supports daily learning."
    else:
        assessment = (
            f"Solar learning {quality.value}: {len(activations)} activation"
            f"{'s' if len(activations) != 1 else ''}, {len(complete)} complete episode"
            f"{'s' if len(complete) != 1 else ''}."
        )
    source_ids = tuple(
        dict.fromkeys(
            event_id
            for transition in transitions
            for event_id in transition.evidence_event_ids
        )
    )
    return DailySolarLearningSummary(
        activation_count=len(activations),
        deactivation_count=len(deactivations),
        complete_episode_count=len(complete),
        open_episode_count=sum(
            item.state is SolarEpisodeState.OPEN for item in daily_episodes
        ),
        total_observed_runtime_seconds=actual.solar_runtime_seconds,
        first_activation_time=(
            None if not activations else activations[0].occurred_at
        ),
        last_deactivation_time=(
            None if not deactivations else deactivations[-1].occurred_at
        ),
        activation_roof_temperatures_f=activation_roofs,
        activation_roof_to_pool_differentials_f=activation_diffs,
        deactivation_roof_to_pool_differentials_f=deactivation_diffs,
        median_activation_roof_temperature_f=_supported_median(activation_roofs),
        median_activation_differential_f=activation_median,
        median_deactivation_differential_f=deactivation_median,
        provisional_hysteresis_differential_f=hysteresis,
        learning_quality=quality,
        usable_for_learning=usable,
        assessment=assessment,
        limitations=tuple(limitations),
        episodes=daily_episodes,
        source_evidence_ids=source_ids,
    )


def _daily_assessment(
    quality: SoakQualityAssessment,
    solar: DailySolarLearningSummary,
) -> str:
    if solar.first_activation_time is None:
        solar_text = "No solar activation was observed."
    else:
        first = solar.first_activation_time.isoformat()
        first_diff = (
            None
            if not solar.activation_roof_to_pool_differentials_f
            else solar.activation_roof_to_pool_differentials_f[0]
        )
        differential_text = (
            " with no available roof-to-pool differential"
            if first_diff is None
            else f" at a {first_diff:.1f}°F roof-to-pool differential"
        )
        solar_text = (
            f"Solar activated {solar.activation_count} time"
            f"{'s' if solar.activation_count != 1 else ''}; first activation {first}"
            f"{differential_text}."
        )
    return f"{quality.assessment} {solar_text}"


def _relevant_records(
    records: tuple[RecordedObservationEvent, ...],
    *,
    window_start: datetime,
    window_end: datetime,
    maximum_evidence_gap: timedelta,
) -> tuple[RecordedObservationEvent, ...]:
    predecessor: RecordedObservationEvent | None = None
    inside: list[RecordedObservationEvent] = []
    for record in records:
        if record.recorded_at < window_start:
            predecessor = record
        elif record.recorded_at < window_end:
            inside.append(record)
    if (
        predecessor is not None
        and predecessor.recorded_at >= window_start - maximum_evidence_gap
    ):
        inside.insert(0, predecessor)
    return tuple(inside)


def _supported_spans(
    records: tuple[RecordedObservationEvent, ...],
    *,
    window_start: datetime,
    window_end: datetime,
    maximum_evidence_gap: timedelta,
) -> tuple[tuple[RecordedObservationEvent, datetime, datetime], ...]:
    relevant = _relevant_records(
        records,
        window_start=window_start,
        window_end=window_end,
        maximum_evidence_gap=maximum_evidence_gap,
    )
    spans: list[tuple[RecordedObservationEvent, datetime, datetime]] = []
    for index, record in enumerate(relevant):
        start = max(record.recorded_at, window_start)
        next_at = window_end
        if index + 1 < len(relevant):
            next_at = min(next_at, relevant[index + 1].recorded_at)
        end = min(next_at, start + maximum_evidence_gap, window_end)
        if end > start:
            spans.append((record, start, end))
    return tuple(spans)


def _largest_uncovered_gap(
    spans: tuple[tuple[RecordedObservationEvent, datetime, datetime], ...],
    window_start: datetime,
    window_end: datetime,
) -> float:
    cursor = window_start
    largest = 0.0
    for _, start, end in spans:
        if start > cursor:
            largest = max(largest, (start - cursor).total_seconds())
        cursor = max(cursor, end)
    if cursor < window_end:
        largest = max(largest, (window_end - cursor).total_seconds())
    return largest


def _health_values(record: RecordedObservationEvent, key: str) -> tuple[str, ...]:
    value = record.health.get(key, ())
    if not isinstance(value, (list, tuple)):
        return ()
    return tuple(sorted(str(item) for item in value if str(item).strip()))


def _health_reasons(record: RecordedObservationEvent) -> tuple[str, ...]:
    if bool(record.health.get("healthy", False)):
        return ()
    reasons: list[str] = []
    reasons.append(SoakQualityReason.OBSERVATION_HEALTH_INCIDENT.value)
    if _health_values(record, "missing_required"):
        reasons.append(SoakQualityReason.REQUIRED_MAPPING_MISSING.value)
    if _health_values(record, "unavailable_entities"):
        reasons.append(SoakQualityReason.REQUIRED_ENTITY_UNAVAILABLE.value)
    if _health_values(record, "stale_entities"):
        reasons.append(SoakQualityReason.REQUIRED_ENTITY_STALE.value)
    return tuple(reasons)


def _startup_grace_intervals(
    records: tuple[RecordedObservationEvent, ...],
    *,
    window_start: datetime,
    window_end: datetime,
    startup_health_grace: timedelta,
) -> tuple[tuple[datetime, datetime], ...]:
    intervals = [
        (max(record.recorded_at, window_start), min(record.recorded_at + startup_health_grace, window_end))
        for record in records
        if record.kind == "baseline"
        and record.recorded_at < window_end
        and record.recorded_at + startup_health_grace > window_start
    ]
    merged: list[tuple[datetime, datetime]] = []
    for start, end in sorted(intervals):
        if not merged or start > merged[-1][1]:
            merged.append((start, end))
        else:
            merged[-1] = (merged[-1][0], max(merged[-1][1], end))
    return tuple(merged)


def _containing_grace_end(
    timestamp: datetime,
    intervals: tuple[tuple[datetime, datetime], ...],
) -> datetime | None:
    return next(
        (end for start, end in intervals if start <= timestamp < end),
        None,
    )


def _duration_outside_intervals(
    start: datetime,
    end: datetime,
    intervals: tuple[tuple[datetime, datetime], ...],
) -> float:
    total = (end - start).total_seconds()
    suppressed = 0.0
    for interval_start, interval_end in intervals:
        overlap_start = max(start, interval_start)
        overlap_end = min(end, interval_end)
        if overlap_end > overlap_start:
            suppressed += (overlap_end - overlap_start).total_seconds()
    return max(0.0, total - suppressed)


def _merge_intervals(
    intervals: tuple[tuple[datetime, datetime], ...],
) -> tuple[tuple[datetime, datetime], ...]:
    merged: list[tuple[datetime, datetime]] = []
    for start, end in sorted(intervals):
        if end <= start:
            continue
        if not merged or start > merged[-1][1]:
            merged.append((start, end))
        else:
            merged[-1] = (merged[-1][0], max(merged[-1][1], end))
    return tuple(merged)


def _timestamp_in_intervals(
    timestamp: datetime,
    intervals: tuple[tuple[datetime, datetime], ...],
) -> bool:
    return any(start <= timestamp <= end for start, end in intervals)


def _episode_intersects_intervals(
    episode: SolarEpisode,
    intervals: tuple[tuple[datetime, datetime], ...],
    window_end: datetime,
) -> bool:
    episode_end = episode.deactivation_time or window_end
    return any(
        intervals_intersect(episode.activation_time, episode_end, start, end)
        for start, end in intervals
    )


def _attribute_values(
    events: tuple[InferredBehaviorEvent, ...], key: str
) -> tuple[float, ...]:
    values = [
        value
        for event in events
        if (value := _number(event.attributes.get(key))) is not None
    ]
    return tuple(values)


def _supported_median(values: tuple[float, ...]) -> float | None:
    if len(values) < _MINIMUM_MEDIAN_SAMPLES:
        return None
    return round(float(statistics.median(values)), 3)


def _priming_ranges(
    events: tuple[InferredBehaviorEvent, ...],
    *,
    window_start: datetime,
    window_end: datetime,
) -> tuple[tuple[datetime, datetime], ...]:
    ranges: list[tuple[datetime, datetime]] = []
    for event in events:
        elapsed = _number(event.attributes.get("elapsed_seconds"))
        if elapsed is None or elapsed <= 0:
            continue
        raw_start = event.occurred_at - timedelta(seconds=elapsed)
        start = max(raw_start, window_start)
        end = min(event.occurred_at, window_end)
        if end > start:
            ranges.append((start, end))
    return tuple(sorted(ranges))


def _ranges_overlap_seconds(
    start: datetime,
    end: datetime,
    ranges: tuple[tuple[datetime, datetime], ...],
) -> float:
    total = 0.0
    for range_start, range_end in ranges:
        overlap_start = max(start, range_start)
        overlap_end = min(end, range_end)
        if overlap_end > overlap_start:
            total += (overlap_end - overlap_start).total_seconds()
    return min((end - start).total_seconds(), total)


def _counterfactual(
    actual: ActualOperationalMetrics,
    advisories: tuple[RecordedRecommendationEvent, ...],
    fallback_recommendation: OperatorRecommendation | None,
) -> CounterfactualReport:
    limitations = (
        "The canonical 11.2 recommendation does not encode a daily runtime target, start time, stop time, or interruption-recovery duration; those differences are not invented.",
        "Counterfactual comparisons report only differences directly supported by recorded observations and recommendation evidence.",
        "When multiple advisory snapshots exist in one window, the latest advisory state is the comparison anchor and all advisory event IDs are preserved for provenance.",
    )
    latest_advisory = advisories[-1] if advisories else None
    recommendation = latest_advisory.recommendation if latest_advisory is not None else fallback_recommendation
    if recommendation is None:
        summary = (
            "The latest 11.2 advisory state in this reporting window cleared the active recommendation."
            if latest_advisory is not None
            else "No 11.2 operator-recommendation evidence was available for this reporting window."
        )
        return CounterfactualReport(
            status=CounterfactualStatus.NOT_AVAILABLE,
            summary=summary,
            advisory_count=len(advisories),
            advisory_event_ids=tuple(item.event_id for item in advisories),
            recommendation_id=None,
            recommendation_published_at=None if latest_advisory is None else latest_advisory.published_at,
            recommendation_status=None,
            recommendation=None,
            selected_intent_ids=(),
            rationale=(),
            constraints=(),
            expected_effect=None,
            confidence="not_available",
            exact_differences=(),
            limitations=limitations,
        )

    differences: list[CounterfactualDifference] = []
    status = CounterfactualStatus.ADVISORY_LIMITED
    if recommendation.status is OperatorRecommendationStatus.NO_ACTION:
        status = CounterfactualStatus.NO_CHANGE_RECOMMENDED
        summary = "The 11.2 advisory stack recommended no pump-operation change."
    elif recommendation.status is OperatorRecommendationStatus.BLOCKED:
        summary = "The 11.2 advisory stack could not produce a safe pump recommendation."
    else:
        recommended_rpm = recommendation.recommended_pump_rpm
        actual_rpm = actual.average_running_rpm
        if recommended_rpm is not None and actual_rpm is not None:
            delta = float(recommended_rpm) - actual_rpm
            differences.append(
                CounterfactualDifference(
                    code="average_running_rpm",
                    actual=_rounded(actual_rpm),
                    counterfactual=float(recommended_rpm),
                    delta=_rounded(delta),
                    unit="rpm",
                    explanation=(
                        "Counterfactual RPM minus the time-weighted observed running RPM. "
                        "This does not imply a daily duration or schedule change."
                    ),
                )
            )
            if abs(delta) < 1.0:
                status = CounterfactualStatus.NO_CHANGE_RECOMMENDED
                summary = "Observed average running RPM matched the available 11.2 pump recommendation."
            else:
                status = CounterfactualStatus.CHANGE_RECOMMENDED
                direction = "lower" if delta < 0 else "higher"
                summary = (
                    f"The available 11.2 advisory evidence would use a {abs(delta):.0f} RPM {direction} "
                    "pump target than the observed time-weighted running average."
                )
        elif recommended_rpm is not None and actual.pump_runtime_seconds <= 0:
            differences.append(
                CounterfactualDifference(
                    code="pump_operation_presence",
                    actual=False,
                    counterfactual=True,
                    delta=None,
                    unit=None,
                    explanation=(
                        f"No pump runtime was observed while the advisory evidence recommended operation at {recommended_rpm} RPM; "
                        "recommended duration is not encoded."
                    ),
                )
            )
            status = CounterfactualStatus.CHANGE_RECOMMENDED
            summary = "The available 11.2 advisory evidence called for pump operation, but no pump runtime was observed."
        else:
            summary = "The 11.2 advisory evidence was available, but the recorded evidence does not support an exact RPM difference."

    return CounterfactualReport(
        status=status,
        summary=summary,
        advisory_count=len(advisories) if advisories else (1 if fallback_recommendation is not None else 0),
        advisory_event_ids=tuple(item.event_id for item in advisories),
        recommendation_id=recommendation.recommendation_id,
        recommendation_published_at=None if latest_advisory is None else latest_advisory.published_at,
        recommendation_status=recommendation.status.value,
        recommendation=recommendation.summary,
        selected_intent_ids=recommendation.selected_intent_ids,
        rationale=recommendation.rationale,
        constraints=recommendation.constraints,
        expected_effect=recommendation.expected_effect,
        confidence=recommendation.confidence,
        exact_differences=tuple(differences),
        limitations=limitations,
    )


def _recorded_recommendation(payload: Mapping[str, Any]) -> RecordedRecommendationEvent:
    raw_recommendation = payload.get("recommendation")
    recommendation: OperatorRecommendation | None = None
    if raw_recommendation is not None:
        data = dict(raw_recommendation)
        recommendation = OperatorRecommendation(
            recommendation_id=str(data["recommendation_id"]),
            status=OperatorRecommendationStatus(str(data["status"])),
            summary=str(data["summary"]),
            recommended_pump_rpm=(
                None if data.get("recommended_pump_rpm") is None else int(data["recommended_pump_rpm"])
            ),
            selected_intent_ids=tuple(str(item) for item in data.get("selected_intent_ids", ())),
            rationale=tuple(str(item) for item in data.get("rationale", ())),
            constraints=tuple(str(item) for item in data.get("constraints", ())),
            expected_effect=str(data["expected_effect"]),
            confidence=str(data.get("confidence", "deterministic")),
        )
    return RecordedRecommendationEvent(
        event_id=str(payload["event_id"]),
        published_at=datetime.fromisoformat(str(payload["published_at"])),
        recommendation=recommendation,
    )


def _frame(event: RecordedObservationEvent) -> _Frame:
    values: dict[str, Any] = {}
    units: dict[str, str | None] = {}
    for observation in event.observations:
        observation_id = str(observation.get("observation_id", ""))
        if not observation_id:
            continue
        values[observation_id] = observation.get("value")
        raw_unit = observation.get("unit")
        units[observation_id] = None if raw_unit is None else str(raw_unit)
    return _Frame(event=event, values=values, units=units)


def _seed_index(frames: tuple[_Frame, ...], start: datetime) -> int | None:
    result: int | None = None
    for index, frame in enumerate(frames):
        if frame.event.recorded_at <= start:
            result = index
        else:
            break
    return result


def _mode(values: Mapping[str, Any], rpm: float | None) -> str:
    if rpm is None:
        return "UNKNOWN"
    if rpm < _MIN_RUNNING_RPM:
        return "STOPPED"
    if _boolean(values.get("spa.active")) is True:
        return "SPA"
    if _boolean(values.get("solar.active")) is True:
        return "SOLAR_ASSIST"
    if _boolean(values.get("heater.active")) is True:
        return "HEATING"
    if _boolean(values.get("pool.active")) is True:
        return "FILTERING"
    return "IDLE"


def _filtration_interruptions(
    frames: tuple[_Frame, ...],
    window_start: datetime,
    window_end: datetime,
    *,
    maximum_evidence_gap: timedelta,
) -> int:
    states: list[tuple[datetime, bool, bool | None]] = []
    predecessor: _Frame | None = None
    for frame in frames:
        if frame.event.recorded_at < window_start:
            predecessor = frame
            continue
        if frame.event.recorded_at >= window_end:
            break
        rpm = _number(frame.values.get("pump.rpm"))
        running = rpm is not None and rpm >= _MIN_RUNNING_RPM
        pool_active = _boolean(frame.values.get("pool.active"))
        states.append((frame.event.recorded_at, running, pool_active))
    interruptions = 0
    pending_stop = False
    previous_running: bool | None = None
    previous_pool: bool | None = None
    if (
        predecessor is not None
        and predecessor.event.recorded_at >= window_start - maximum_evidence_gap
    ):
        predecessor_rpm = _number(predecessor.values.get("pump.rpm"))
        previous_running = predecessor_rpm is not None and predecessor_rpm >= _MIN_RUNNING_RPM
        previous_pool = _boolean(predecessor.values.get("pool.active"))
    for _, running, pool_active in states:
        if previous_running is True and running is False and previous_pool is True and pool_active is True:
            pending_stop = True
        elif pending_stop and running is True and pool_active is True:
            interruptions += 1
            pending_stop = False
        elif pool_active is not True:
            pending_stop = False
        previous_running = running
        previous_pool = pool_active
    return interruptions


def _empty_actual(window_start: datetime, window_end: datetime) -> ActualOperationalMetrics:
    return ActualOperationalMetrics(
        window_start=window_start,
        window_end=window_end,
        evidence_coverage_seconds=0.0,
        healthy_coverage_seconds=0.0,
        coverage_ratio=0.0,
        pump_runtime_seconds=0.0,
        runtime_by_mode_seconds={},
        priming_count=0,
        inferred_priming_duration_seconds=0.0,
        spa_runtime_seconds=0.0,
        solar_runtime_seconds=0.0,
        heater_runtime_seconds=0.0,
        filtration_interruptions=0,
        average_running_rpm=None,
        pump_energy_kwh=None,
        temperatures={
            key: TemperatureSummary(None, None, None, 0.0)
            for key in (
                "pool.temperature",
                "spa.temperature",
                "solar.temperature",
                "air.temperature",
            )
        },
        source_event_ids=(),
    )


def _validate_window(start: datetime, end: datetime) -> None:
    if start.tzinfo is None or start.utcoffset() is None or end.tzinfo is None or end.utcoffset() is None:
        raise ValueError("retrospective window bounds must be timezone-aware")
    if end <= start:
        raise ValueError("retrospective window end must be after start")


def _boolean(value: Any) -> bool | None:
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        normalized = value.strip().lower()
        if normalized in {"on", "true", "yes", "1"}:
            return True
        if normalized in {"off", "false", "no", "0"}:
            return False
    return None


def _number(value: Any) -> float | None:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def _rounded(value: float | None, *, digits: int = 3) -> float | None:
    return None if value is None else round(value, digits)


def _canonical_json(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False)


__all__ = [
    "ActualOperationalMetrics",
    "CounterfactualDifference",
    "CounterfactualReport",
    "CounterfactualStatus",
    "DailySolarLearningSummary",
    "DailyOperationalRetrospective",
    "DailyOperationalRetrospectiveEngine",
    "ObservationIncident",
    "ObservationIncidentClassification",
    "ObservationIncidentState",
    "PersistentRecommendationRecorder",
    "RETROSPECTIVE_SCHEMA_VERSION",
    "RecordedRecommendationEvent",
    "SCHEMA_VERSION",
    "SoakQualityAssessment",
    "SoakQualityPolicy",
    "SoakQualityReason",
    "SoakQualityStatus",
    "SolarLearningQuality",
    "TemperatureSummary",
]
