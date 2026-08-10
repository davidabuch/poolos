"""Deterministic multi-day commissioning intelligence from canonical daily reports.

This module is observation-only. It summarizes immutable daily retrospective
evidence and cannot create policy, commands, authority, or physical actuation.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timedelta
from enum import Enum
from hashlib import sha256
import json
import statistics
from typing import Any, Iterable

from .daily_retrospective import (
    DailyOperationalRetrospective,
    ObservationIncidentState,
    SoakQualityStatus,
)

SCHEMA_VERSION = "1.0.0"


class CommissioningEvidenceStatus(str, Enum):
    """Human-review readiness of an empirical commissioning evidence window."""

    ACCUMULATING = "ACCUMULATING"
    REVIEW_REQUIRED = "REVIEW_REQUIRED"
    SUFFICIENT_FOR_POLICY_REVIEW = "SUFFICIENT_FOR_POLICY_REVIEW"


class CommissioningEvidenceReason(str, Enum):
    """Stable machine-readable reasons supporting the evidence status."""

    MISSING_DAILY_REPORTS = "MISSING_DAILY_REPORTS"
    INSUFFICIENT_GOOD_DAYS = "INSUFFICIENT_GOOD_DAYS"
    INSUFFICIENT_CONSECUTIVE_GOOD_DAYS = "INSUFFICIENT_CONSECUTIVE_GOOD_DAYS"
    INSUFFICIENT_USABLE_SOLAR_DAYS = "INSUFFICIENT_USABLE_SOLAR_DAYS"
    INSUFFICIENT_COMPLETE_SOLAR_EPISODES = "INSUFFICIENT_COMPLETE_SOLAR_EPISODES"
    RECENT_OBSERVATION_INCIDENT = "RECENT_OBSERVATION_INCIDENT"
    OPEN_OBSERVATION_INCIDENT = "OPEN_OBSERVATION_INCIDENT"
    QUALITY_CONCERNS_DOMINATE = "QUALITY_CONCERNS_DOMINATE"
    READY_FOR_HUMAN_POLICY_REVIEW = "READY_FOR_HUMAN_POLICY_REVIEW"


@dataclass(frozen=True, slots=True)
class CommissioningEvidencePolicy:
    """Conservative commissioning defaults; not scientifically validated rules."""

    minimum_good_days: int = 5
    minimum_consecutive_good_days: int = 3
    minimum_usable_solar_days: int = 3
    minimum_complete_solar_episodes: int = 5
    recent_incident_days: int = 2
    minimum_statistical_samples: int = 2

    def __post_init__(self) -> None:
        for name, value in (
            ("minimum_good_days", self.minimum_good_days),
            ("minimum_consecutive_good_days", self.minimum_consecutive_good_days),
            ("minimum_usable_solar_days", self.minimum_usable_solar_days),
            ("minimum_complete_solar_episodes", self.minimum_complete_solar_episodes),
            ("recent_incident_days", self.recent_incident_days),
            ("minimum_statistical_samples", self.minimum_statistical_samples),
        ):
            if value < 1:
                raise ValueError(f"{name} must be at least 1")

    def to_dict(self) -> dict[str, int]:
        return {
            "minimum_good_days": self.minimum_good_days,
            "minimum_consecutive_good_days": self.minimum_consecutive_good_days,
            "minimum_usable_solar_days": self.minimum_usable_solar_days,
            "minimum_complete_solar_episodes": self.minimum_complete_solar_episodes,
            "recent_incident_days": self.recent_incident_days,
            "minimum_statistical_samples": self.minimum_statistical_samples,
        }


@dataclass(frozen=True, slots=True)
class SampleStatistics:
    """Deterministic empirical samples and supported descriptive statistics."""

    samples: tuple[float, ...]
    median: float | None
    minimum: float | None
    maximum: float | None
    range: float | None

    @property
    def sample_count(self) -> int:
        return len(self.samples)

    def to_dict(self) -> dict[str, Any]:
        return {
            "sample_count": self.sample_count,
            "samples": list(self.samples),
            "median": self.median,
            "minimum": self.minimum,
            "maximum": self.maximum,
            "range": self.range,
        }


@dataclass(frozen=True, slots=True)
class DailySolarEvidenceContribution:
    """Clean solar evidence contributed by one canonical GOOD daily report."""

    report_date: date
    report_id: str
    activation_differentials_f: tuple[float, ...]
    deactivation_differentials_f: tuple[float, ...]
    activation_roof_temperatures_f: tuple[float, ...]
    complete_episode_count: int
    open_episode_count: int

    def to_dict(self) -> dict[str, Any]:
        return {
            "report_date": self.report_date.isoformat(),
            "report_id": self.report_id,
            "activation_differentials_f": list(self.activation_differentials_f),
            "deactivation_differentials_f": list(self.deactivation_differentials_f),
            "activation_roof_temperatures_f": list(
                self.activation_roof_temperatures_f
            ),
            "complete_episode_count": self.complete_episode_count,
            "open_episode_count": self.open_episode_count,
        }


@dataclass(frozen=True, slots=True)
class MultiDayCommissioningReport:
    """Immutable cross-day evidence summary with no operational authority."""

    report_id: str
    schema_version: str
    criteria: CommissioningEvidencePolicy
    start_date: date
    end_date: date
    total_days: int
    expected_days: int
    missing_dates: tuple[date, ...]
    good_days: int
    degraded_days: int
    excluded_days: int
    consecutive_good_days: int
    consecutive_good_incident_free_days: int
    included_report_ids: tuple[str, ...]
    degraded_report_ids: tuple[str, ...]
    excluded_report_ids: tuple[str, ...]
    total_incident_count: int
    incident_days: int
    incident_dates: tuple[date, ...]
    total_supported_incident_duration_seconds: float
    recovered_incident_count: int
    open_incident_count: int
    most_recent_incident_date: date | None
    most_recent_incident_at: datetime | None
    usable_solar_learning_days: int
    complete_solar_episode_count: int
    open_solar_episode_count: int
    distinct_good_solar_sample_days: int
    solar_contributions: tuple[DailySolarEvidenceContribution, ...]
    activation_differentials: SampleStatistics
    deactivation_differentials: SampleStatistics
    activation_roof_temperatures: SampleStatistics
    provisional_cross_day_hysteresis_f: float | None
    evidence_status: CommissioningEvidenceStatus
    reason_codes: tuple[CommissioningEvidenceReason, ...]
    limitations: tuple[str, ...]
    assessment: str
    source_report_ids: tuple[str, ...]

    @property
    def activation_sample_count(self) -> int:
        return self.activation_differentials.sample_count

    @property
    def deactivation_sample_count(self) -> int:
        return self.deactivation_differentials.sample_count

    def to_dict(self) -> dict[str, Any]:
        return {
            "report_id": self.report_id,
            "schema_version": self.schema_version,
            "criteria": self.criteria.to_dict(),
            "start_date": self.start_date.isoformat(),
            "end_date": self.end_date.isoformat(),
            "total_days": self.total_days,
            "expected_days": self.expected_days,
            "missing_dates": [item.isoformat() for item in self.missing_dates],
            "good_days": self.good_days,
            "degraded_days": self.degraded_days,
            "excluded_days": self.excluded_days,
            "consecutive_good_days": self.consecutive_good_days,
            "consecutive_good_incident_free_days": self.consecutive_good_incident_free_days,
            "included_report_ids": list(self.included_report_ids),
            "degraded_report_ids": list(self.degraded_report_ids),
            "excluded_report_ids": list(self.excluded_report_ids),
            "total_incident_count": self.total_incident_count,
            "incident_days": self.incident_days,
            "incident_dates": [item.isoformat() for item in self.incident_dates],
            "total_supported_incident_duration_seconds": round(
                self.total_supported_incident_duration_seconds, 3
            ),
            "recovered_incident_count": self.recovered_incident_count,
            "open_incident_count": self.open_incident_count,
            "most_recent_incident_date": (
                None
                if self.most_recent_incident_date is None
                else self.most_recent_incident_date.isoformat()
            ),
            "most_recent_incident_at": (
                None
                if self.most_recent_incident_at is None
                else self.most_recent_incident_at.isoformat()
            ),
            "usable_solar_learning_days": self.usable_solar_learning_days,
            "complete_solar_episode_count": self.complete_solar_episode_count,
            "open_solar_episode_count": self.open_solar_episode_count,
            "distinct_good_solar_sample_days": self.distinct_good_solar_sample_days,
            "solar_contributions": [item.to_dict() for item in self.solar_contributions],
            "activation_sample_count": self.activation_sample_count,
            "deactivation_sample_count": self.deactivation_sample_count,
            "activation_differentials": self.activation_differentials.to_dict(),
            "deactivation_differentials": self.deactivation_differentials.to_dict(),
            "activation_roof_temperatures": self.activation_roof_temperatures.to_dict(),
            "provisional_cross_day_hysteresis_f": self.provisional_cross_day_hysteresis_f,
            "evidence_status": self.evidence_status.value,
            "reason_codes": [item.value for item in self.reason_codes],
            "limitations": list(self.limitations),
            "assessment": self.assessment,
            "source_report_ids": list(self.source_report_ids),
            "authority": "none",
            "policy_created": False,
            "command_delivery_enabled": False,
        }


class MultiDayCommissioningIntelligence:
    """Aggregate completed canonical daily reports without reinterpreting them."""

    def __init__(self, policy: CommissioningEvidencePolicy | None = None) -> None:
        self.policy = policy or CommissioningEvidencePolicy()

    def generate(
        self,
        reports: Iterable[DailyOperationalRetrospective],
        *,
        start_date: date,
        end_date: date,
    ) -> MultiDayCommissioningReport:
        """Build a deterministic report for the caller-supplied inclusive range."""

        if end_date < start_date:
            raise ValueError("end_date must not precede start_date")
        provided = tuple(reports)
        for report in provided:
            if not report.complete_day:
                raise ValueError("multi-day commissioning requires completed daily reports")
            if report.generated_at.tzinfo is None or report.generated_at.utcoffset() is None:
                raise ValueError("daily report timestamps must be timezone-aware")
            for incident in report.incidents:
                if (
                    incident.started_at.tzinfo is None
                    or incident.started_at.utcoffset() is None
                    or (
                        incident.ended_at is not None
                        and (
                            incident.ended_at.tzinfo is None
                            or incident.ended_at.utcoffset() is None
                        )
                    )
                ):
                    raise ValueError("incident timestamps must be timezone-aware")
        ordered = tuple(
            sorted(provided, key=lambda item: (_report_date(item), item.report_id))
        )
        report_dates = tuple(_report_date(item) for item in ordered)
        if len(set(report_dates)) != len(report_dates):
            raise ValueError("daily report dates must be unique")
        if len({item.report_id for item in ordered}) != len(ordered):
            raise ValueError("daily report identities must be unique")
        if any(item < start_date or item > end_date for item in report_dates):
            raise ValueError("daily report date falls outside the reporting range")

        expected_dates = tuple(
            start_date + timedelta(days=offset)
            for offset in range((end_date - start_date).days + 1)
        )
        missing_dates = tuple(item for item in expected_dates if item not in report_dates)
        good = tuple(
            item for item in ordered if item.soak_quality.status is SoakQualityStatus.GOOD
        )
        degraded = tuple(
            item
            for item in ordered
            if item.soak_quality.status is SoakQualityStatus.DEGRADED
        )
        excluded = tuple(
            item
            for item in ordered
            if item.soak_quality.status is SoakQualityStatus.EXCLUDED
        )
        incidents = tuple(
            (item, incident)
            for item in ordered
            for incident in item.incidents
        )
        incident_reports = {item.report_id for item, _ in incidents}
        incident_dates = tuple(
            sorted({_report_date(item) for item, _ in incidents})
        )
        consecutive_good = _consecutive_reports(ordered, require_incident_free=False)
        consecutive_incident_free = _consecutive_reports(
            ordered, require_incident_free=True
        )
        contributions = tuple(
            _solar_contribution(item)
            for item in good
            if item.solar_learning.usable_for_learning
        )
        activation_differences = tuple(
            value
            for item in contributions
            for value in item.activation_differentials_f
        )
        deactivation_differences = tuple(
            value
            for item in contributions
            for value in item.deactivation_differentials_f
        )
        activation_roofs = tuple(
            value
            for item in contributions
            for value in item.activation_roof_temperatures_f
        )
        activation_stats = _statistics(
            activation_differences, self.policy.minimum_statistical_samples
        )
        deactivation_stats = _statistics(
            deactivation_differences, self.policy.minimum_statistical_samples
        )
        roof_stats = _statistics(
            activation_roofs, self.policy.minimum_statistical_samples
        )
        hysteresis = (
            None
            if activation_stats.median is None or deactivation_stats.median is None
            else round(activation_stats.median - deactivation_stats.median, 3)
        )
        most_recent = max(
            incidents,
            key=lambda item: (item[1].started_at, item[1].incident_id),
            default=None,
        )
        recent_cutoff = end_date - timedelta(days=self.policy.recent_incident_days - 1)
        recent_incident = any(_report_date(item) >= recent_cutoff for item, _ in incidents)
        open_incidents = sum(
            incident.state is ObservationIncidentState.OPEN for _, incident in incidents
        )

        reasons: list[CommissioningEvidenceReason] = []
        if missing_dates:
            reasons.append(CommissioningEvidenceReason.MISSING_DAILY_REPORTS)
        if len(good) < self.policy.minimum_good_days:
            reasons.append(CommissioningEvidenceReason.INSUFFICIENT_GOOD_DAYS)
        if consecutive_good < self.policy.minimum_consecutive_good_days:
            reasons.append(
                CommissioningEvidenceReason.INSUFFICIENT_CONSECUTIVE_GOOD_DAYS
            )
        if len(contributions) < self.policy.minimum_usable_solar_days:
            reasons.append(
                CommissioningEvidenceReason.INSUFFICIENT_USABLE_SOLAR_DAYS
            )
        complete_episodes = sum(item.complete_episode_count for item in contributions)
        if complete_episodes < self.policy.minimum_complete_solar_episodes:
            reasons.append(
                CommissioningEvidenceReason.INSUFFICIENT_COMPLETE_SOLAR_EPISODES
            )
        if recent_incident:
            reasons.append(CommissioningEvidenceReason.RECENT_OBSERVATION_INCIDENT)
        if open_incidents:
            reasons.append(CommissioningEvidenceReason.OPEN_OBSERVATION_INCIDENT)
        quality_dominates = len(degraded) + len(excluded) > len(good)
        if quality_dominates:
            reasons.append(CommissioningEvidenceReason.QUALITY_CONCERNS_DOMINATE)

        review_reasons = {
            CommissioningEvidenceReason.MISSING_DAILY_REPORTS,
            CommissioningEvidenceReason.RECENT_OBSERVATION_INCIDENT,
            CommissioningEvidenceReason.OPEN_OBSERVATION_INCIDENT,
            CommissioningEvidenceReason.QUALITY_CONCERNS_DOMINATE,
        }
        if any(item in review_reasons for item in reasons):
            status = CommissioningEvidenceStatus.REVIEW_REQUIRED
        elif reasons:
            status = CommissioningEvidenceStatus.ACCUMULATING
        else:
            status = CommissioningEvidenceStatus.SUFFICIENT_FOR_POLICY_REVIEW
            reasons.append(CommissioningEvidenceReason.READY_FOR_HUMAN_POLICY_REVIEW)

        limitations = _limitations(reasons, degraded=len(degraded), excluded=len(excluded))
        assessment = (
            f"Commissioning evidence {status.value}: {len(good)}/{len(ordered)} days GOOD, "
            f"{len(contributions)} usable solar-learning days, {complete_episodes} complete "
            "solar episodes. Human review only; no policy or authority change is made."
        )
        payload = {
            "schema_version": SCHEMA_VERSION,
            "criteria": self.policy.to_dict(),
            "start_date": start_date.isoformat(),
            "end_date": end_date.isoformat(),
            "source_report_ids": [item.report_id for item in ordered],
            "status": status.value,
            "reason_codes": [item.value for item in reasons],
            "solar_contributions": [item.to_dict() for item in contributions],
            "incident_ids": [incident.incident_id for _, incident in incidents],
        }
        report_id = "multi-day-commissioning-" + sha256(
            _canonical_json(payload).encode("utf-8")
        ).hexdigest()[:24]
        return MultiDayCommissioningReport(
            report_id=report_id,
            schema_version=SCHEMA_VERSION,
            criteria=self.policy,
            start_date=start_date,
            end_date=end_date,
            total_days=len(ordered),
            expected_days=len(expected_dates),
            missing_dates=missing_dates,
            good_days=len(good),
            degraded_days=len(degraded),
            excluded_days=len(excluded),
            consecutive_good_days=consecutive_good,
            consecutive_good_incident_free_days=consecutive_incident_free,
            included_report_ids=tuple(item.report_id for item in good),
            degraded_report_ids=tuple(item.report_id for item in degraded),
            excluded_report_ids=tuple(item.report_id for item in excluded),
            total_incident_count=len(incidents),
            incident_days=len(incident_reports),
            incident_dates=incident_dates,
            total_supported_incident_duration_seconds=sum(
                incident.duration_seconds for _, incident in incidents
            ),
            recovered_incident_count=len(incidents) - open_incidents,
            open_incident_count=open_incidents,
            most_recent_incident_date=(
                None if most_recent is None else _report_date(most_recent[0])
            ),
            most_recent_incident_at=(
                None if most_recent is None else most_recent[1].started_at
            ),
            usable_solar_learning_days=len(contributions),
            complete_solar_episode_count=complete_episodes,
            open_solar_episode_count=sum(
                item.open_episode_count for item in contributions
            ),
            distinct_good_solar_sample_days=sum(
                bool(
                    item.activation_differentials_f
                    or item.deactivation_differentials_f
                    or item.activation_roof_temperatures_f
                )
                for item in contributions
            ),
            solar_contributions=contributions,
            activation_differentials=activation_stats,
            deactivation_differentials=deactivation_stats,
            activation_roof_temperatures=roof_stats,
            provisional_cross_day_hysteresis_f=hysteresis,
            evidence_status=status,
            reason_codes=tuple(reasons),
            limitations=limitations,
            assessment=assessment,
            source_report_ids=tuple(item.report_id for item in ordered),
        )


def _report_date(report: DailyOperationalRetrospective) -> date:
    try:
        return date.fromisoformat(report.report_date)
    except ValueError as exc:
        raise ValueError("daily report_date must be an ISO calendar date") from exc


def _consecutive_reports(
    reports: tuple[DailyOperationalRetrospective, ...],
    *,
    require_incident_free: bool,
) -> int:
    count = 0
    expected: date | None = None
    for report in reversed(reports):
        report_date = _report_date(report)
        if expected is not None and report_date != expected:
            break
        if report.soak_quality.status is not SoakQualityStatus.GOOD:
            break
        if require_incident_free and report.incidents:
            break
        count += 1
        expected = report_date - timedelta(days=1)
    return count


def _solar_contribution(
    report: DailyOperationalRetrospective,
) -> DailySolarEvidenceContribution:
    solar = report.solar_learning
    return DailySolarEvidenceContribution(
        report_date=_report_date(report),
        report_id=report.report_id,
        activation_differentials_f=tuple(
            solar.activation_roof_to_pool_differentials_f
        ),
        deactivation_differentials_f=tuple(
            solar.deactivation_roof_to_pool_differentials_f
        ),
        activation_roof_temperatures_f=tuple(solar.activation_roof_temperatures_f),
        complete_episode_count=solar.complete_episode_count,
        open_episode_count=solar.open_episode_count,
    )


def _statistics(samples: tuple[float, ...], minimum_samples: int) -> SampleStatistics:
    if len(samples) < minimum_samples:
        return SampleStatistics(samples, None, None, None, None)
    minimum = min(samples)
    maximum = max(samples)
    return SampleStatistics(
        samples=samples,
        median=round(float(statistics.median(samples)), 3),
        minimum=round(minimum, 3),
        maximum=round(maximum, 3),
        range=round(maximum - minimum, 3),
    )


def _limitations(
    reasons: list[CommissioningEvidenceReason],
    *,
    degraded: int,
    excluded: int,
) -> tuple[str, ...]:
    messages = {
        CommissioningEvidenceReason.MISSING_DAILY_REPORTS: "One or more dates lack a completed canonical daily retrospective.",
        CommissioningEvidenceReason.INSUFFICIENT_GOOD_DAYS: "More GOOD observation days are required by the commissioning default.",
        CommissioningEvidenceReason.INSUFFICIENT_CONSECUTIVE_GOOD_DAYS: "A longer consecutive run of GOOD days is required.",
        CommissioningEvidenceReason.INSUFFICIENT_USABLE_SOLAR_DAYS: "More GOOD days with usable daily solar evidence are required.",
        CommissioningEvidenceReason.INSUFFICIENT_COMPLETE_SOLAR_EPISODES: "More complete solar episodes are required before human policy review.",
        CommissioningEvidenceReason.RECENT_OBSERVATION_INCIDENT: "A recent neutral observation incident requires engineering review.",
        CommissioningEvidenceReason.OPEN_OBSERVATION_INCIDENT: "At least one observation incident remains open.",
        CommissioningEvidenceReason.QUALITY_CONCERNS_DOMINATE: "DEGRADED and EXCLUDED days outnumber GOOD days.",
    }
    result = [messages[item] for item in reasons if item in messages]
    if degraded or excluded:
        result.append(
            f"The window retains {degraded} DEGRADED and {excluded} EXCLUDED days as provenance; neither contributes clean solar samples."
        )
    result.append(
        "Observed Pentair behavior is empirical evidence and is not necessarily optimal."
    )
    result.append(
        "SUFFICIENT_FOR_POLICY_REVIEW permits human review only and creates no policy, threshold, command, or authority."
    )
    return tuple(result)


def _canonical_json(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False)


__all__ = [
    "CommissioningEvidencePolicy",
    "CommissioningEvidenceReason",
    "CommissioningEvidenceStatus",
    "DailySolarEvidenceContribution",
    "MultiDayCommissioningIntelligence",
    "MultiDayCommissioningReport",
    "SCHEMA_VERSION",
    "SampleStatistics",
]
