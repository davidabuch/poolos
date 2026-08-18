"""Persistent privacy-safe sustained native parity commissioning evidence."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from enum import Enum
import json
import math
import os
from pathlib import Path
from types import MappingProxyType
from typing import Any, Mapping

from .observation_parity import (
    ObservationParityDetail,
    ObservationParityReport,
    ObservationParityStatus,
)
from .intellicenter_readonly import INTELLICENTER_PARITY_ELIGIBLE_CONCEPTS

COMMISSIONING_TARGET_DURATION = timedelta(hours=72)
COMMISSIONING_RETENTION = timedelta(days=7)
COMMISSIONING_MAX_RECORDS = 30_000
COMMISSIONING_MAX_CONTINUOUS_GAP = timedelta(minutes=5)
COMMISSIONING_RETENTION_SWEEP_INTERVAL = timedelta(hours=1)
PERSISTENT_MISMATCH_CYCLE_COUNT = 3
PARITY_HISTORY_FILENAME = "native_parity_history.jsonl"
PARITY_SUMMARY_FILENAME = "native_parity_commissioning.json"
PARITY_HISTORY_SCHEMA_VERSION = 1
PARITY_SUMMARY_SCHEMA_VERSION = 1


class NativeParityCommissioningStatus(str, Enum):
    """Neutral manual-review readiness states; none grants authority."""

    COLLECTING = "COLLECTING"
    INSUFFICIENT_DURATION = "INSUFFICIENT_DURATION"
    DEGRADED = "DEGRADED"
    READY_FOR_REVIEW = "READY_FOR_REVIEW"


@dataclass(frozen=True, slots=True)
class NativeParityEvidenceDetail:
    concept: str
    status: ObservationParityStatus
    ha_value: str | int | float | bool | None
    native_value: str | int | float | bool | None
    tolerance: float | None
    absolute_delta: float | None
    ha_observed_at: datetime | None
    ha_sampled_at: datetime | None
    native_observed_at: datetime | None

    def __post_init__(self) -> None:
        if not self.concept.strip():
            raise ValueError("parity evidence concept must not be blank")
        for timestamp in (
            self.ha_observed_at,
            self.ha_sampled_at,
            self.native_observed_at,
        ):
            if timestamp is not None:
                _aware(timestamp, "parity detail timestamp")
        for value in (self.tolerance, self.absolute_delta):
            if value is not None and (value < 0 or not math.isfinite(value)):
                raise ValueError("parity numeric evidence must be finite and non-negative")

    @classmethod
    def from_parity(cls, detail: ObservationParityDetail) -> NativeParityEvidenceDetail:
        return cls(
            concept=detail.concept,
            status=detail.status,
            ha_value=_safe_value(detail.ha_value),
            native_value=_safe_value(detail.native_value),
            tolerance=detail.tolerance,
            absolute_delta=_numeric_delta(detail.ha_value, detail.native_value),
            ha_observed_at=detail.ha_observed_at,
            ha_sampled_at=detail.ha_sampled_at,
            native_observed_at=detail.native_observed_at,
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "concept": self.concept,
            "status": self.status.value,
            "ha_value": self.ha_value,
            "native_value": self.native_value,
            "tolerance": self.tolerance,
            "absolute_delta": self.absolute_delta,
            "ha_observed_at": _iso(self.ha_observed_at),
            "ha_sampled_at": _iso(self.ha_sampled_at),
            "native_observed_at": _iso(self.native_observed_at),
        }


@dataclass(frozen=True, slots=True)
class NativeParityEvidenceRecord:
    report_id: str
    generated_at: datetime
    parity_ratio: float
    compared_concept_count: int
    match_count: int
    mismatch_count: int
    value_mismatch_count: int
    type_mismatch_count: int
    missing_native_count: int
    missing_ha_count: int
    stale_native_count: int
    stale_ha_count: int
    native_transport_state: str
    native_transport_available: bool
    reconnect_count: int
    discovery_generation: int
    details: tuple[NativeParityEvidenceDetail, ...]

    def __post_init__(self) -> None:
        _aware(self.generated_at, "record generated_at")
        if not self.report_id.strip() or not self.native_transport_state.strip():
            raise ValueError("parity record identities must not be blank")
        details = tuple(sorted(self.details, key=lambda x: x.concept))
        if len({item.concept for item in details}) != len(details):
            raise ValueError("parity record concepts must be unique")
        counts = {
            status: sum(item.status is status for item in details)
            for status in ObservationParityStatus
        }
        expected = (
            len(details),
            counts[ObservationParityStatus.MATCH],
            len(details) - counts[ObservationParityStatus.MATCH],
            counts[ObservationParityStatus.VALUE_MISMATCH],
            counts[ObservationParityStatus.TYPE_MISMATCH],
            counts[ObservationParityStatus.MISSING_NATIVE],
            counts[ObservationParityStatus.MISSING_HA],
            counts[ObservationParityStatus.STALE_NATIVE],
            counts[ObservationParityStatus.STALE_HA],
        )
        actual = (
            self.compared_concept_count,
            self.match_count,
            self.mismatch_count,
            self.value_mismatch_count,
            self.type_mismatch_count,
            self.missing_native_count,
            self.missing_ha_count,
            self.stale_native_count,
            self.stale_ha_count,
        )
        if actual != expected:
            raise ValueError("parity record aggregate counts are inconsistent")
        expected_ratio = 0.0 if not details else round(self.match_count / len(details), 6)
        if self.parity_ratio != expected_ratio:
            raise ValueError("parity record ratio is inconsistent")
        if self.reconnect_count < 0 or self.discovery_generation < 0:
            raise ValueError("parity transport counters must not be negative")
        object.__setattr__(self, "details", details)

    @classmethod
    def from_report(
        cls,
        report: ObservationParityReport,
        *,
        transport_state: str,
        reconnect_count: int,
        discovery_generation: int,
    ) -> NativeParityEvidenceRecord:
        details = tuple(
            NativeParityEvidenceDetail.from_parity(item)
            for item in report.details
            if item.concept in INTELLICENTER_PARITY_ELIGIBLE_CONCEPTS
        )
        status_counts = {
            status: sum(item.status is status for item in details)
            for status in ObservationParityStatus
        }
        compared = len(details)
        matches = status_counts[ObservationParityStatus.MATCH]
        return cls(
            report_id=report.report_id,
            generated_at=report.generated_at,
            parity_ratio=0.0 if compared == 0 else round(matches / compared, 6),
            compared_concept_count=compared,
            match_count=matches,
            mismatch_count=compared - matches,
            value_mismatch_count=status_counts[ObservationParityStatus.VALUE_MISMATCH],
            type_mismatch_count=status_counts[ObservationParityStatus.TYPE_MISMATCH],
            missing_native_count=status_counts[ObservationParityStatus.MISSING_NATIVE],
            missing_ha_count=status_counts[ObservationParityStatus.MISSING_HA],
            stale_native_count=status_counts[ObservationParityStatus.STALE_NATIVE],
            stale_ha_count=status_counts[ObservationParityStatus.STALE_HA],
            native_transport_state=transport_state.strip().upper()[:32],
            native_transport_available=report.native_source_available,
            reconnect_count=max(0, int(reconnect_count)),
            discovery_generation=max(0, int(discovery_generation)),
            details=details,
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": PARITY_HISTORY_SCHEMA_VERSION,
            "report_id": self.report_id,
            "generated_at": self.generated_at.isoformat(),
            "parity_ratio": self.parity_ratio,
            "compared_concept_count": self.compared_concept_count,
            "match_count": self.match_count,
            "mismatch_count": self.mismatch_count,
            "value_mismatch_count": self.value_mismatch_count,
            "type_mismatch_count": self.type_mismatch_count,
            "missing_native_count": self.missing_native_count,
            "missing_ha_count": self.missing_ha_count,
            "stale_native_count": self.stale_native_count,
            "stale_ha_count": self.stale_ha_count,
            "native_transport_state": self.native_transport_state,
            "native_transport_available": self.native_transport_available,
            "reconnect_count": self.reconnect_count,
            "discovery_generation": self.discovery_generation,
            "details": [item.to_dict() for item in self.details],
            "authority": "none",
            "command_delivery_enabled": False,
        }


@dataclass(frozen=True, slots=True)
class NativeParityConceptStatistics:
    concept: str
    observation_count: int
    match_count: int
    value_mismatch_count: int
    type_mismatch_count: int
    missing_native_count: int
    missing_ha_count: int
    stale_native_count: int
    stale_ha_count: int
    match_ratio: float
    current_status: ObservationParityStatus
    current_consecutive_mismatch_count: int
    longest_consecutive_mismatch_count: int
    current_mismatch_duration_seconds: float | None
    longest_mismatch_duration_seconds: float | None
    seconds_since_last_match: float | None
    current_absolute_delta: float | None
    maximum_absolute_delta: float | None
    average_absolute_delta: float | None

    def to_dict(self) -> dict[str, Any]:
        return {
            field: getattr(self, field)
            for field in self.__dataclass_fields__
        } | {"current_status": self.current_status.value}


@dataclass(frozen=True, slots=True)
class NativeParityCommissioningSummary:
    status: NativeParityCommissioningStatus
    commissioning_start: datetime | None
    latest_evidence_at: datetime | None
    elapsed_seconds: float
    continuous_evidence_seconds: float
    target_duration_seconds: float
    progress_percent: float
    minimum_duration_reached: bool
    total_comparison_cycles: int
    total_concept_comparisons: int
    total_matches: int
    total_mismatches: int
    overall_match_ratio: float
    status_totals: Mapping[str, int]
    reconnect_events_observed: int
    discovery_generation_changes: int
    transport_unavailable_cycles: int
    maximum_evidence_gap_seconds: float
    concepts_with_any_mismatch: tuple[str, ...]
    persistent_mismatch_concepts: tuple[str, ...]
    worst_numeric_mismatch_concepts: tuple[str, ...]
    concept_statistics: tuple[NativeParityConceptStatistics, ...]

    def __post_init__(self) -> None:
        object.__setattr__(self, "status_totals", MappingProxyType(dict(sorted(self.status_totals.items()))))
        object.__setattr__(self, "concepts_with_any_mismatch", tuple(sorted(self.concepts_with_any_mismatch)))
        object.__setattr__(self, "persistent_mismatch_concepts", tuple(sorted(self.persistent_mismatch_concepts)))
        object.__setattr__(self, "worst_numeric_mismatch_concepts", tuple(self.worst_numeric_mismatch_concepts))
        object.__setattr__(self, "concept_statistics", tuple(sorted(self.concept_statistics, key=lambda x: x.concept)))

    def to_dict(self, *, include_concepts: bool = True) -> dict[str, Any]:
        result: dict[str, Any] = {
            "schema_version": PARITY_SUMMARY_SCHEMA_VERSION,
            "status": self.status.value,
            "commissioning_start": _iso(self.commissioning_start),
            "latest_evidence_at": _iso(self.latest_evidence_at),
            "elapsed_seconds": self.elapsed_seconds,
            "continuous_evidence_seconds": self.continuous_evidence_seconds,
            "target_duration_seconds": self.target_duration_seconds,
            "progress_percent": self.progress_percent,
            "minimum_duration_reached": self.minimum_duration_reached,
            "total_comparison_cycles": self.total_comparison_cycles,
            "total_concept_comparisons": self.total_concept_comparisons,
            "total_matches": self.total_matches,
            "total_mismatches": self.total_mismatches,
            "overall_match_ratio": self.overall_match_ratio,
            "status_totals": dict(self.status_totals),
            "reconnect_events_observed": self.reconnect_events_observed,
            "discovery_generation_changes": self.discovery_generation_changes,
            "transport_unavailable_cycles": self.transport_unavailable_cycles,
            "maximum_evidence_gap_seconds": self.maximum_evidence_gap_seconds,
            "concepts_with_any_mismatch": list(self.concepts_with_any_mismatch),
            "persistent_mismatch_concepts": list(self.persistent_mismatch_concepts),
            "worst_numeric_mismatch_concepts": list(self.worst_numeric_mismatch_concepts),
            "authority": "none",
            "authoritative_source": "home_assistant",
            "command_delivery_enabled": False,
            "physical_delivery_enabled": False,
            "read_only_safety_mode": True,
            "review_readiness_only": True,
        }
        if include_concepts:
            result["concept_statistics"] = [item.to_dict() for item in self.concept_statistics]
        return result

    def diagnostic_attributes(self, *, history_path: str, last_error: str | None) -> dict[str, Any]:
        return {
            "elapsed_hours": round(self.elapsed_seconds / 3600, 2),
            "continuous_evidence_hours": round(self.continuous_evidence_seconds / 3600, 2),
            "target_hours": round(self.target_duration_seconds / 3600, 2),
            "progress_percent": self.progress_percent,
            "cycle_count": self.total_comparison_cycles,
            "overall_match_ratio": self.overall_match_ratio,
            "mismatch_concept_count": len(self.concepts_with_any_mismatch),
            "persistent_mismatch_concept_count": len(self.persistent_mismatch_concepts),
            "persistent_mismatch_concepts": list(self.persistent_mismatch_concepts[:12]),
            "reconnect_events_observed": self.reconnect_events_observed,
            "discovery_generation_changes": self.discovery_generation_changes,
            "transport_unavailable_cycles": self.transport_unavailable_cycles,
            "latest_evidence_at": _iso(self.latest_evidence_at),
            "history_path": history_path,
            "persistence_error": last_error,
            "authority": "none",
            "command_delivery_enabled": False,
            "physical_delivery_enabled": False,
            "read_only_safety_mode": True,
            "review_readiness_only": True,
        }


class NativeParityCommissioningStore:
    """Append privacy-safe cycles and recover a bounded commissioning window."""

    def __init__(
        self,
        root: Path | str,
        *,
        target_duration: timedelta = COMMISSIONING_TARGET_DURATION,
        retention: timedelta = COMMISSIONING_RETENTION,
        maximum_records: int = COMMISSIONING_MAX_RECORDS,
        maximum_continuous_gap: timedelta = COMMISSIONING_MAX_CONTINUOUS_GAP,
        load_history: bool = True,
    ) -> None:
        if target_duration <= timedelta(0) or retention < target_duration:
            raise ValueError("commissioning retention must cover the positive target")
        if maximum_records < 2 or maximum_continuous_gap <= timedelta(0):
            raise ValueError("commissioning bounds must be positive")
        self.root = Path(root)
        self.target_duration = target_duration
        self.retention = retention
        self.maximum_records = maximum_records
        self.maximum_continuous_gap = maximum_continuous_gap
        self.last_error: str | None = None
        self.persistence_available = True
        self._records: tuple[NativeParityEvidenceRecord, ...] = ()
        self._last_retention_sweep_at: datetime | None = None
        self._history_needs_rewrite = False
        self._loaded = False
        if load_history:
            self.load()

    @property
    def history_path(self) -> Path:
        return self.root / PARITY_HISTORY_FILENAME

    @property
    def summary_path(self) -> Path:
        return self.root / PARITY_SUMMARY_FILENAME

    @property
    def records(self) -> tuple[NativeParityEvidenceRecord, ...]:
        return self._records

    @property
    def loaded(self) -> bool:
        return self._loaded

    def load(self) -> None:
        """Load retained history once; callers choose the execution context."""

        if self._loaded:
            return
        self._load()
        self._loaded = True

    def record(
        self,
        report: ObservationParityReport,
        *,
        transport_state: str,
        reconnect_count: int,
        discovery_generation: int,
    ) -> NativeParityCommissioningSummary:
        if not self._loaded:
            raise RuntimeError(
                "native parity commissioning history must be loaded before recording"
            )
        evidence = NativeParityEvidenceRecord.from_report(
            report,
            transport_state=transport_state,
            reconnect_count=reconnect_count,
            discovery_generation=discovery_generation,
        )
        if any(evidence.report_id == item.report_id for item in self._records):
            return self.summary()
        out_of_order = bool(
            self._records and evidence.generated_at < self._records[-1].generated_at
        )
        candidates = tuple(
            sorted(
                (*self._records, evidence),
                key=lambda item: (item.generated_at, item.report_id),
            )
        )
        latest_candidate_at = candidates[-1].generated_at
        sweep_due = (
            self._last_retention_sweep_at is None
            or latest_candidate_at - self._last_retention_sweep_at
            >= COMMISSIONING_RETENTION_SWEEP_INTERVAL
            or len(candidates) > self.maximum_records
        )
        retained = (
            _retain(
                candidates,
                latest=latest_candidate_at,
                retention=self.retention,
                maximum_records=self.maximum_records,
            )
            if sweep_due
            else candidates
        )
        if sweep_due:
            self._last_retention_sweep_at = latest_candidate_at
        pruned = len(retained) != len(candidates)
        self._records = retained
        summary = self.summary()
        if self.persistence_available:
            try:
                self.root.mkdir(parents=True, exist_ok=True)
                if pruned or out_of_order or self._history_needs_rewrite:
                    self._rewrite_history()
                else:
                    self._append_history(evidence)
                self._write_summary(summary)
                self.last_error = None
                self._history_needs_rewrite = False
            except (OSError, TypeError, ValueError):
                self.last_error = "native parity commissioning persistence failed"
                self._history_needs_rewrite = True
        return summary

    def summary(self) -> NativeParityCommissioningSummary:
        return summarize_native_parity(
            self._records,
            target_duration=self.target_duration,
            maximum_continuous_gap=self.maximum_continuous_gap,
        )

    def diagnostics(
        self, *, summary: NativeParityCommissioningSummary | None = None
    ) -> dict[str, Any]:
        summary = self.summary() if summary is None else summary
        return {
            **summary.diagnostic_attributes(
                history_path=str(self.history_path),
                last_error=self.last_error,
            ),
            "summary_path": str(self.summary_path),
            "retention_days": self.retention.total_seconds() / 86400,
            "maximum_records": self.maximum_records,
            "retained_record_count": len(self._records),
            "persistence_available": self.persistence_available,
            "history_loaded": self._loaded,
        }

    def _load(self) -> None:
        if not self.history_path.exists():
            return
        try:
            lines = self.history_path.read_text(encoding="utf-8").splitlines()
            parsed: list[NativeParityEvidenceRecord] = []
            trailing_partial = False
            nonempty_indexes = [index for index, line in enumerate(lines) if line.strip()]
            final_nonempty_index = nonempty_indexes[-1] if nonempty_indexes else None
            for index, line in enumerate(lines):
                if not line.strip():
                    continue
                try:
                    payload = json.loads(line)
                except json.JSONDecodeError:
                    if index == final_nonempty_index and parsed:
                        trailing_partial = True
                        break
                    raise
                parsed.append(_record_from_dict(payload))
            records = tuple(parsed)
            if len({item.report_id for item in records}) != len(records):
                raise ValueError("duplicate parity report identity")
            ordered = tuple(
                sorted(records, key=lambda item: (item.generated_at, item.report_id))
            )
            if records != ordered:
                self._history_needs_rewrite = True
            if ordered:
                ordered = _retain(
                    ordered,
                    latest=ordered[-1].generated_at,
                    retention=self.retention,
                    maximum_records=self.maximum_records,
                )
            self._records = ordered
            self._last_retention_sweep_at = (
                None if not ordered else ordered[-1].generated_at
            )
            if trailing_partial:
                self.last_error = (
                    "native parity commissioning history had incomplete trailing record"
                )
                self._history_needs_rewrite = True
        except (OSError, TypeError, ValueError, KeyError, json.JSONDecodeError):
            # Fail closed with respect to corrupt historical evidence, but allow
            # the next valid commissioning cycle to replace the damaged history
            # atomically with a new clean evidence window.
            self.last_error = "native parity commissioning history is corrupt"
            self.persistence_available = True
            self._history_needs_rewrite = True
            self._records = ()

    def _append_history(self, record: NativeParityEvidenceRecord) -> None:
        with self.history_path.open("a", encoding="utf-8") as handle:
            handle.write(_canonical_json(record.to_dict()) + "\n")
            handle.flush()
            os.fsync(handle.fileno())

    def _rewrite_history(self) -> None:
        temporary = self.history_path.with_suffix(".jsonl.tmp")
        try:
            temporary.write_text(
                "".join(_canonical_json(item.to_dict()) + "\n" for item in self._records),
                encoding="utf-8",
            )
            temporary.replace(self.history_path)
        finally:
            temporary.unlink(missing_ok=True)

    def _write_summary(self, summary: NativeParityCommissioningSummary) -> None:
        temporary = self.summary_path.with_suffix(".json.tmp")
        try:
            temporary.write_text(
                json.dumps(summary.to_dict(), sort_keys=True, indent=2, allow_nan=False) + "\n",
                encoding="utf-8",
            )
            temporary.replace(self.summary_path)
        finally:
            temporary.unlink(missing_ok=True)


def summarize_native_parity(
    records: tuple[NativeParityEvidenceRecord, ...],
    *,
    target_duration: timedelta = COMMISSIONING_TARGET_DURATION,
    maximum_continuous_gap: timedelta = COMMISSIONING_MAX_CONTINUOUS_GAP,
) -> NativeParityCommissioningSummary:
    ordered = tuple(sorted(records, key=lambda item: item.generated_at))
    start = ordered[0].generated_at if ordered else None
    latest = ordered[-1].generated_at if ordered else None
    elapsed = 0.0 if start is None or latest is None else (latest - start).total_seconds()
    continuous_start, maximum_gap = _continuous_start(ordered, maximum_continuous_gap)
    continuous = (
        0.0
        if continuous_start is None or latest is None
        else (latest - continuous_start).total_seconds()
    )
    by_concept: dict[str, list[tuple[datetime, NativeParityEvidenceDetail]]] = {}
    status_totals = {status.value: 0 for status in ObservationParityStatus}
    for record in ordered:
        for detail in record.details:
            status_totals[detail.status.value] += 1
            by_concept.setdefault(detail.concept, []).append((record.generated_at, detail))
    concept_stats = tuple(
        _concept_statistics(concept, tuple(values), latest)
        for concept, values in sorted(by_concept.items())
    )
    total_comparisons = sum(status_totals.values())
    matches = status_totals[ObservationParityStatus.MATCH.value]
    persistent = tuple(
        item.concept
        for item in concept_stats
        if item.current_consecutive_mismatch_count >= PERSISTENT_MISMATCH_CYCLE_COUNT
    )
    any_mismatch = tuple(
        item.concept for item in concept_stats if item.match_count < item.observation_count
    )
    numeric = sorted(
        (
            (item.maximum_absolute_delta, item.concept)
            for item in concept_stats
            if item.maximum_absolute_delta is not None
        ),
        key=lambda item: (-float(item[0]), item[1]),
    )
    unavailable = sum(not item.native_transport_available for item in ordered)
    reached = continuous >= target_duration.total_seconds()
    if len(ordered) < 2:
        status = NativeParityCommissioningStatus.COLLECTING
    elif not reached:
        status = NativeParityCommissioningStatus.INSUFFICIENT_DURATION
    elif persistent:
        status = NativeParityCommissioningStatus.DEGRADED
    else:
        status = NativeParityCommissioningStatus.READY_FOR_REVIEW
    return NativeParityCommissioningSummary(
        status=status,
        commissioning_start=start,
        latest_evidence_at=latest,
        elapsed_seconds=elapsed,
        continuous_evidence_seconds=continuous,
        target_duration_seconds=target_duration.total_seconds(),
        progress_percent=round(min(100.0, continuous / target_duration.total_seconds() * 100), 2),
        minimum_duration_reached=reached,
        total_comparison_cycles=len(ordered),
        total_concept_comparisons=total_comparisons,
        total_matches=matches,
        total_mismatches=total_comparisons - matches,
        overall_match_ratio=0.0 if total_comparisons == 0 else round(matches / total_comparisons, 6),
        status_totals=status_totals,
        reconnect_events_observed=_reconnect_events(ordered),
        discovery_generation_changes=_generation_changes(ordered),
        transport_unavailable_cycles=unavailable,
        maximum_evidence_gap_seconds=maximum_gap,
        concepts_with_any_mismatch=any_mismatch,
        persistent_mismatch_concepts=persistent,
        worst_numeric_mismatch_concepts=tuple(item[1] for item in numeric[:10]),
        concept_statistics=concept_stats,
    )


def _concept_statistics(
    concept: str,
    evidence: tuple[tuple[datetime, NativeParityEvidenceDetail], ...],
    latest: datetime | None,
) -> NativeParityConceptStatistics:
    statuses = tuple(item.status for _, item in evidence)
    adverse = tuple(status is not ObservationParityStatus.MATCH for status in statuses)
    runs: list[tuple[int, float]] = []
    run_start: datetime | None = None
    run_count = 0
    for index, ((at, detail), is_adverse) in enumerate(
        zip(evidence, adverse, strict=True)
    ):
        del detail
        if is_adverse:
            run_start = at if run_start is None else run_start
            run_count += 1
        elif run_start is not None:
            previous_at = evidence[index - 1][0]
            runs.append((run_count, (previous_at - run_start).total_seconds()))
            run_start = None
            run_count = 0
    current_duration: float | None = None
    if run_start is not None:
        current_duration = (evidence[-1][0] - run_start).total_seconds()
        runs.append((run_count, current_duration))
    deltas = tuple(
        item.absolute_delta
        for _, item in evidence
        if item.status is ObservationParityStatus.VALUE_MISMATCH
        and item.absolute_delta is not None
    )
    last_match = next(
        (at for at, item in reversed(evidence) if item.status is ObservationParityStatus.MATCH),
        None,
    )
    return NativeParityConceptStatistics(
        concept=concept,
        observation_count=len(evidence),
        match_count=statuses.count(ObservationParityStatus.MATCH),
        value_mismatch_count=statuses.count(ObservationParityStatus.VALUE_MISMATCH),
        type_mismatch_count=statuses.count(ObservationParityStatus.TYPE_MISMATCH),
        missing_native_count=statuses.count(ObservationParityStatus.MISSING_NATIVE),
        missing_ha_count=statuses.count(ObservationParityStatus.MISSING_HA),
        stale_native_count=statuses.count(ObservationParityStatus.STALE_NATIVE),
        stale_ha_count=statuses.count(ObservationParityStatus.STALE_HA),
        match_ratio=round(statuses.count(ObservationParityStatus.MATCH) / len(evidence), 6),
        current_status=statuses[-1],
        current_consecutive_mismatch_count=run_count if adverse[-1] else 0,
        longest_consecutive_mismatch_count=max((item[0] for item in runs), default=0),
        current_mismatch_duration_seconds=current_duration,
        longest_mismatch_duration_seconds=max((item[1] for item in runs), default=None),
        seconds_since_last_match=(
            None if last_match is None or latest is None else (latest - last_match).total_seconds()
        ),
        current_absolute_delta=evidence[-1][1].absolute_delta,
        maximum_absolute_delta=max(deltas, default=None),
        average_absolute_delta=(None if not deltas else round(sum(deltas) / len(deltas), 6)),
    )


def _continuous_start(
    records: tuple[NativeParityEvidenceRecord, ...], maximum_gap: timedelta
) -> tuple[datetime | None, float]:
    start: datetime | None = None
    previous_record: datetime | None = None
    previous_complete: datetime | None = None
    largest = 0.0
    maximum_gap_seconds = maximum_gap.total_seconds()

    for record in records:
        record_gap = (
            0.0
            if previous_record is None
            else (record.generated_at - previous_record).total_seconds()
        )
        largest = max(largest, record_gap)
        previous_record = record.generated_at

        if not _record_has_complete_comparison_evidence(record):
            continue

        if (
            start is None
            or previous_complete is None
            or (record.generated_at - previous_complete).total_seconds()
            > maximum_gap_seconds
        ):
            start = record.generated_at
        previous_complete = record.generated_at

    if not records or previous_complete is None:
        return None, largest

    latest = records[-1].generated_at
    if (latest - previous_complete).total_seconds() > maximum_gap_seconds:
        return None, largest

    return start, largest


def _record_has_complete_comparison_evidence(
    record: NativeParityEvidenceRecord,
) -> bool:
    return bool(
        record.native_transport_available
        and record.missing_native_count == 0
        and record.missing_ha_count == 0
        and record.stale_native_count == 0
        and record.stale_ha_count == 0
    )


def _reconnect_events(records: tuple[NativeParityEvidenceRecord, ...]) -> int:
    return (0 if not records else records[0].reconnect_count) + sum(
        max(0, current.reconnect_count - previous.reconnect_count)
        for previous, current in zip(records, records[1:], strict=False)
    )


def _generation_changes(records: tuple[NativeParityEvidenceRecord, ...]) -> int:
    return sum(
        current.discovery_generation != previous.discovery_generation
        for previous, current in zip(records, records[1:], strict=False)
    )


def _retain(
    records: tuple[NativeParityEvidenceRecord, ...],
    *,
    latest: datetime,
    retention: timedelta,
    maximum_records: int,
) -> tuple[NativeParityEvidenceRecord, ...]:
    cutoff = latest - retention
    retained = tuple(item for item in records if item.generated_at >= cutoff)
    return retained[-maximum_records:]


def _record_from_dict(value: Mapping[str, Any]) -> NativeParityEvidenceRecord:
    if value.get("schema_version") != PARITY_HISTORY_SCHEMA_VERSION:
        raise ValueError("unsupported native parity history schema")
    details = tuple(
        NativeParityEvidenceDetail(
            concept=str(item["concept"]),
            status=ObservationParityStatus(str(item["status"])),
            ha_value=_safe_value(item.get("ha_value")),
            native_value=_safe_value(item.get("native_value")),
            tolerance=_optional_float(item.get("tolerance")),
            absolute_delta=_optional_float(item.get("absolute_delta")),
            ha_observed_at=_optional_datetime(item.get("ha_observed_at")),
            ha_sampled_at=_optional_datetime(item.get("ha_sampled_at")),
            native_observed_at=_optional_datetime(item.get("native_observed_at")),
        )
        for item in value["details"]
    )
    return NativeParityEvidenceRecord(
        report_id=str(value["report_id"]),
        generated_at=_datetime(value["generated_at"]),
        parity_ratio=float(value["parity_ratio"]),
        compared_concept_count=int(value["compared_concept_count"]),
        match_count=int(value["match_count"]),
        mismatch_count=int(value["mismatch_count"]),
        value_mismatch_count=int(value["value_mismatch_count"]),
        type_mismatch_count=int(value["type_mismatch_count"]),
        missing_native_count=int(value["missing_native_count"]),
        missing_ha_count=int(value["missing_ha_count"]),
        stale_native_count=int(value["stale_native_count"]),
        stale_ha_count=int(value["stale_ha_count"]),
        native_transport_state=str(value["native_transport_state"]),
        native_transport_available=bool(value["native_transport_available"]),
        reconnect_count=int(value["reconnect_count"]),
        discovery_generation=int(value["discovery_generation"]),
        details=details,
    )


def _numeric_delta(left: Any, right: Any) -> float | None:
    if isinstance(left, bool) or isinstance(right, bool):
        return None
    if not isinstance(left, (int, float)) or not isinstance(right, (int, float)):
        return None
    delta = abs(float(left) - float(right))
    return round(delta, 6) if math.isfinite(delta) else None


def _safe_value(value: Any) -> str | int | float | bool | None:
    if isinstance(value, str):
        return value[:64]
    if isinstance(value, bool) or value is None:
        return value
    if isinstance(value, int):
        return value
    if isinstance(value, float) and math.isfinite(value):
        return value
    return None


def _optional_float(value: Any) -> float | None:
    return None if value is None else float(value)


def _datetime(value: Any) -> datetime:
    result = datetime.fromisoformat(str(value))
    _aware(result, "parity history timestamp")
    return result


def _optional_datetime(value: Any) -> datetime | None:
    return None if value is None else _datetime(value)


def _aware(value: datetime, label: str) -> None:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{label} must be timezone-aware")


def _iso(value: datetime | None) -> str | None:
    return None if value is None else value.isoformat()


def _canonical_json(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False)


__all__ = [
    "COMMISSIONING_MAX_RECORDS",
    "COMMISSIONING_RETENTION",
    "COMMISSIONING_TARGET_DURATION",
    "NativeParityCommissioningStatus",
    "NativeParityCommissioningStore",
    "NativeParityCommissioningSummary",
    "NativeParityConceptStatistics",
    "NativeParityEvidenceDetail",
    "NativeParityEvidenceRecord",
    "summarize_native_parity",
]
