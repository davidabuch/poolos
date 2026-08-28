from __future__ import annotations

from datetime import UTC, datetime
import json
from types import SimpleNamespace

from poolos.daily_retrospective import (
    DailySolarLearningSummary,
    SolarLearningQuality,
)
from poolos.solar_recorder_diagnostics import (
    solar_learning_quality_state,
    solar_learning_recorder_attributes,
    solar_transitions_recorder_attributes,
    solar_transitions_state,
)


NOW = datetime(2026, 8, 27, 20, 0, tzinfo=UTC)
RECORDER_ATTRIBUTE_BUDGET = 8192


class DetailedEpisode:
    def __init__(self, index: int) -> None:
        self.index = index

    def to_dict(self) -> dict[str, object]:
        return {
            "episode_id": f"solar-episode-{self.index:05d}",
            "source_event_ids": [
                f"solar-source-{self.index:05d}-{part:03d}" for part in range(20)
            ],
            "nested_transition_evidence": "e" * 512,
        }


def _report(*, evidence_count: int) -> SimpleNamespace:
    values = tuple(float(index % 180) for index in range(evidence_count))
    solar = DailySolarLearningSummary(
        activation_count=evidence_count,
        deactivation_count=evidence_count - 1,
        complete_episode_count=evidence_count - 1,
        open_episode_count=1,
        total_observed_runtime_seconds=28800.125,
        first_activation_time=NOW,
        last_deactivation_time=NOW,
        activation_roof_temperatures_f=values,
        activation_roof_to_pool_differentials_f=values,
        deactivation_roof_to_pool_differentials_f=values[:-1],
        median_activation_roof_temperature_f=120.0,
        median_activation_differential_f=12.0,
        median_deactivation_differential_f=4.0,
        provisional_hysteresis_differential_f=8.0,
        learning_quality=SolarLearningQuality.INCLUDED,
        usable_for_learning=True,
        assessment="Solar evidence supports the current empirical learning summary."
        + "a" * 5000,
        limitations=tuple("limitation-" + str(index) + "-" + "x" * 500 for index in range(100)),
        episodes=tuple(DetailedEpisode(index) for index in range(evidence_count)),  # type: ignore[arg-type]
        source_evidence_ids=tuple(
            f"source-evidence-{index:06d}" for index in range(evidence_count * 20)
        ),
    )
    return SimpleNamespace(
        report_id="daily-retrospective-2026-08-27",
        report_date="2026-08-27",
        solar_learning=solar,
    )


def _size(value: dict[str, object]) -> int:
    return len(json.dumps(value, sort_keys=True, separators=(",", ":")).encode())


def test_representative_solar_sensor_attributes_are_recorder_safe() -> None:
    report = _report(evidence_count=12)

    assert _size(solar_transitions_recorder_attributes(report)) < RECORDER_ATTRIBUTE_BUDGET
    assert _size(solar_learning_recorder_attributes(report)) < RECORDER_ATTRIBUTE_BUDGET


def test_worst_case_history_cannot_grow_recorder_attributes_without_bound() -> None:
    report = _report(evidence_count=2000)
    detailed = report.solar_learning.to_dict()
    transitions = solar_transitions_recorder_attributes(report)
    learning = solar_learning_recorder_attributes(report)

    assert len(json.dumps(detailed, default=str).encode()) > 1_000_000
    assert _size(transitions) < RECORDER_ATTRIBUTE_BUDGET
    assert _size(learning) < RECORDER_ATTRIBUTE_BUDGET
    assert transitions["transition_count"] == 3999
    assert learning["transition_count"] == 3999
    assert transitions["sampled_activation_count"] == 2000
    assert transitions["sampled_deactivation_count"] == 1999
    assert learning["limitations_truncated"] is True


def test_recorder_projection_omits_complete_historical_arrays() -> None:
    report = _report(evidence_count=50)
    attributes = {
        **solar_transitions_recorder_attributes(report),
        **solar_learning_recorder_attributes(report),
    }

    for prohibited in (
        "activation_roof_temperatures_f",
        "activation_roof_to_pool_differentials_f",
        "deactivation_roof_to_pool_differentials_f",
        "episodes",
        "source_evidence_ids",
    ):
        assert prohibited not in attributes
    assert attributes["detailed_history_in_recorder_attributes"] is False
    assert attributes["detailed_history_available_elsewhere"] is True


def test_detailed_core_evidence_remains_intact_outside_recorder_projection() -> None:
    report = _report(evidence_count=100)

    assert len(report.solar_learning.episodes) == 100
    assert len(report.solar_learning.source_evidence_ids) == 2000
    assert len(report.solar_learning.activation_roof_temperatures_f) == 100
    assert len(report.solar_learning.to_dict()["episodes"]) == 100


def test_existing_sensor_state_semantics_are_unchanged() -> None:
    report = _report(evidence_count=25)

    assert solar_transitions_state(report) == 49
    assert solar_learning_quality_state(report) == "INCLUDED"
    assert solar_transitions_state(None) is None
    assert solar_learning_quality_state(None) == "NOT_AVAILABLE"
