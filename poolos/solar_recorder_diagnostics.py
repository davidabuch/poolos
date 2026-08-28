"""Bounded current Solar summaries for Home Assistant Recorder surfaces.

The immutable daily retrospective remains the detailed evidence model.  These
projections deliberately omit its growing samples, episodes, and source IDs.
"""

from __future__ import annotations

from typing import Any

from .daily_retrospective import DailyOperationalRetrospective

_ASSESSMENT_TEXT_LIMIT = 512
_LIMITATION_COUNT_LIMIT = 8
_LIMITATION_TEXT_LIMIT = 256
_DETAIL_SOURCES = (
    "daily_retrospective_model",
    "persistent_observation_store",
    "daily_evidence_export",
)


def solar_transitions_state(
    report: DailyOperationalRetrospective | None,
) -> int | None:
    """Preserve the existing Solar-transitions sensor state."""

    if report is None:
        return None
    solar = report.solar_learning
    return solar.activation_count + solar.deactivation_count


def solar_learning_quality_state(
    report: DailyOperationalRetrospective | None,
) -> str:
    """Preserve the existing Solar-learning-quality sensor state."""

    if report is None:
        return "NOT_AVAILABLE"
    return report.solar_learning.learning_quality.value


def solar_transitions_recorder_attributes(
    report: DailyOperationalRetrospective | None,
) -> dict[str, Any]:
    """Return bounded transition counts and current-day boundary timestamps."""

    if report is None:
        return _unavailable()
    solar = report.solar_learning
    return {
        "available": True,
        "report_id": report.report_id,
        "report_date": report.report_date,
        "transition_count": solar.activation_count + solar.deactivation_count,
        "activation_count": solar.activation_count,
        "deactivation_count": solar.deactivation_count,
        "sampled_activation_count": len(
            solar.activation_roof_to_pool_differentials_f
        ),
        "sampled_deactivation_count": len(
            solar.deactivation_roof_to_pool_differentials_f
        ),
        "complete_episode_count": solar.complete_episode_count,
        "open_episode_count": solar.open_episode_count,
        "first_activation_at": _iso(solar.first_activation_time),
        "last_deactivation_at": _iso(solar.last_deactivation_time),
        "total_observed_runtime_seconds": round(
            solar.total_observed_runtime_seconds, 3
        ),
        "learning_state": solar.learning_quality.value,
        "usable_for_learning": solar.usable_for_learning,
        **_detail_location(),
        "authority": "none",
        "command_delivery_enabled": False,
    }


def solar_learning_recorder_attributes(
    report: DailyOperationalRetrospective | None,
) -> dict[str, Any]:
    """Return bounded current learning quality without historical arrays."""

    if report is None:
        return _unavailable()
    solar = report.solar_learning
    limitations = tuple(str(item) for item in solar.limitations)
    return {
        "available": True,
        "report_id": report.report_id,
        "report_date": report.report_date,
        "learning_state": solar.learning_quality.value,
        "usable_for_learning": solar.usable_for_learning,
        "transition_count": solar.activation_count + solar.deactivation_count,
        "activation_count": solar.activation_count,
        "deactivation_count": solar.deactivation_count,
        "complete_episode_count": solar.complete_episode_count,
        "open_episode_count": solar.open_episode_count,
        "total_observed_runtime_seconds": round(
            solar.total_observed_runtime_seconds, 3
        ),
        "first_activation_at": _iso(solar.first_activation_time),
        "last_deactivation_at": _iso(solar.last_deactivation_time),
        "median_activation_roof_temperature_f": (
            solar.median_activation_roof_temperature_f
        ),
        "median_activation_differential_f": (
            solar.median_activation_differential_f
        ),
        "median_deactivation_differential_f": (
            solar.median_deactivation_differential_f
        ),
        "provisional_hysteresis_differential_f": (
            solar.provisional_hysteresis_differential_f
        ),
        "assessment": str(solar.assessment)[:_ASSESSMENT_TEXT_LIMIT],
        "limitation_count": len(limitations),
        "limitations": [
            item[:_LIMITATION_TEXT_LIMIT]
            for item in limitations[:_LIMITATION_COUNT_LIMIT]
        ],
        "limitations_truncated": len(limitations) > _LIMITATION_COUNT_LIMIT
        or any(len(item) > _LIMITATION_TEXT_LIMIT for item in limitations),
        "empirical_evidence_only": True,
        "poolos_control_rule": False,
        **_detail_location(),
        "authority": "none",
        "command_delivery_enabled": False,
    }


def _detail_location() -> dict[str, Any]:
    return {
        "detailed_history_in_recorder_attributes": False,
        "detailed_history_available_elsewhere": True,
        "detailed_history_sources": list(_DETAIL_SOURCES),
    }


def _unavailable() -> dict[str, Any]:
    return {
        "available": False,
        **_detail_location(),
        "authority": "none",
        "command_delivery_enabled": False,
    }


def _iso(value: Any) -> str | None:
    return None if value is None else value.isoformat()


__all__ = [
    "solar_learning_quality_state",
    "solar_learning_recorder_attributes",
    "solar_transitions_recorder_attributes",
    "solar_transitions_state",
]
