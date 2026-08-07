"""Deterministic daily operational retrospective and counterfactual reporting.

This module summarizes durable observed PoolOS evidence and compares supported
facts with canonical 11.2 operator-recommendation evidence. It is advisory only:
it creates no commands, execution plans, Home Assistant service calls, vendor
requests, or physical actuation.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from enum import Enum
from hashlib import sha256
import json
import math
import os
from pathlib import Path
from types import MappingProxyType
from typing import Any, Iterable, Mapping

from .behavioral_inference import BehavioralInferenceEngine, InferredBehaviorEvent
from .operator_recommendation import OperatorRecommendation, OperatorRecommendationStatus
from .observations import RecordedObservationEvent

SCHEMA_VERSION = "1.0.0"
_MIN_RUNNING_RPM = 100.0


class CounterfactualStatus(str, Enum):
    """How completely the available 11.2 advisory evidence supports comparison."""

    NOT_AVAILABLE = "NOT_AVAILABLE"
    NO_CHANGE_RECOMMENDED = "NO_CHANGE_RECOMMENDED"
    CHANGE_RECOMMENDED = "CHANGE_RECOMMENDED"
    ADVISORY_LIMITED = "ADVISORY_LIMITED"


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

    def to_dict(self) -> dict[str, Any]:
        return {
            "report_id": self.report_id,
            "schema_version": self.schema_version,
            "report_date": self.report_date,
            "generated_at": self.generated_at.isoformat(),
            "complete_day": self.complete_day,
            "actual": self.actual.to_dict(),
            "counterfactual": self.counterfactual.to_dict(),
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

    def __init__(self, *, maximum_evidence_gap: timedelta = timedelta(minutes=15)) -> None:
        if maximum_evidence_gap <= timedelta(0):
            raise ValueError("maximum_evidence_gap must be positive")
        self.maximum_evidence_gap = maximum_evidence_gap
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
        complete_day: bool,
    ) -> DailyOperationalRetrospective:
        """Generate one deterministic retrospective for the explicit reporting window."""

        _validate_window(window_start, window_end)
        ordered = tuple(sorted(records, key=lambda item: (item.recorded_at, item.event_id)))
        actual = self._actual_metrics(ordered, window_start=window_start, window_end=window_end)
        ordered_advisories = tuple(
            sorted(
                (item for item in advisories if window_start <= item.published_at < window_end),
                key=lambda item: (item.published_at, item.event_id),
            )
        )
        counterfactual = _counterfactual(actual, ordered_advisories, recommendation)
        generated_at = window_end
        identity_payload = {
            "schema_version": SCHEMA_VERSION,
            "report_date": report_date,
            "generated_at": generated_at.isoformat(),
            "complete_day": complete_day,
            "actual": actual.to_dict(),
            "counterfactual": counterfactual.to_dict(),
        }
        report_id = "daily-retrospective-" + sha256(_canonical_json(identity_payload).encode("utf-8")).hexdigest()[:24]
        return DailyOperationalRetrospective(
            report_id=report_id,
            schema_version=SCHEMA_VERSION,
            report_date=report_date,
            generated_at=generated_at,
            complete_day=complete_day,
            actual=actual,
            counterfactual=counterfactual,
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
    "DailyOperationalRetrospective",
    "DailyOperationalRetrospectiveEngine",
    "PersistentRecommendationRecorder",
    "RecordedRecommendationEvent",
    "SCHEMA_VERSION",
    "TemperatureSummary",
]
