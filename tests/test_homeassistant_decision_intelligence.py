from __future__ import annotations

from datetime import datetime, timezone

import pytest

from poolos.decision_flight_recorder import DecisionFlightRecord
from poolos.decision_intelligence import (
    AlternativeStatus,
    CheckStatus,
    DecisionAlternative,
    DecisionCheck,
    DecisionEvidence,
    DecisionExplanation,
    DecisionOutcome,
    EvidenceKind,
)
from poolos.homeassistant.decision_intelligence import (
    HomeAssistantDecisionEntityIds,
    HomeAssistantDecisionProjector,
    HomeAssistantDecisionPublicationError,
    HomeAssistantDecisionPublicationResult,
    HomeAssistantDecisionPublisher,
    HomeAssistantDecisionStatePublication,
)

NOW = datetime(2026, 7, 30, 20, 0, tzinfo=timezone.utc)


def record(*, outcome: DecisionOutcome = DecisionOutcome.SELECTED) -> DecisionFlightRecord:
    blocking = outcome is DecisionOutcome.BLOCKED
    selected_id = "solar_heater" if outcome is DecisionOutcome.SELECTED else None
    alternatives = (
        DecisionAlternative(
            "solar_heater",
            "Solar plus heater",
            AlternativeStatus.SELECTED if selected_id else AlternativeStatus.FEASIBLE,
            1,
            score=0.94,
            reasons=("Meets target before deadline",),
        ),
        DecisionAlternative(
            "heater_only",
            "Heater only",
            AlternativeStatus.REJECTED,
            2,
            score=0.72,
            reasons=("Higher operating cost",),
        ),
    )
    decision = DecisionExplanation(
        decision_id="plan-42",
        evaluated_at=NOW,
        goal="heat:pool",
        outcome=outcome,
        selected_alternative_id=selected_id,
        confidence=0.94 if selected_id else 0.0,
        evidence=(
            DecisionEvidence(
                "solar_forecast",
                "strong",
                EvidenceKind.FORECAST,
                "forecast-service",
                observed_at=NOW,
            ),
        ),
        checks=(
            DecisionCheck(
                "ownership",
                "Control ownership",
                CheckStatus.FAILED if blocking else CheckStatus.PASSED,
                "Manual control active" if blocking else "PoolOS owns control",
                blocking=blocking,
                evidence_keys=("solar_forecast",),
            ),
        ),
        alternatives=alternatives,
        summary=(
            "Planning decision is blocked"
            if blocking
            else "Selected Solar plus heater for execution"
        ),
        next_change="Reevaluate when ownership returns",
    )
    return DecisionFlightRecord(
        sequence=7,
        recorded_at=NOW,
        plan_id="plan-42",
        objective_id="objective-9",
        decision=decision,
        human_text="Pool heating plan selected.\nSolar plus heater will run.",
        technical_text="decision_id=plan-42\noutcome=selected",
    )


def test_projector_builds_six_stable_entities_and_dashboard() -> None:
    projection = HomeAssistantDecisionProjector().project(record())

    assert len(projection.publications) == 6
    assert projection.publications[0].entity_id == "sensor.poolos_last_decision"
    assert projection.publications[0].state == "selected"
    assert projection.dashboard.selected_alternative == "Solar plus heater"
    assert projection.dashboard.confidence_percent == 94
    assert projection.dashboard.as_dict()["decision_id"] == "plan-42"


def test_projection_includes_traceability_and_ranked_alternatives() -> None:
    publication = HomeAssistantDecisionProjector().project(record()).publications[0]

    assert publication.attributes["poolos_plan_id"] == "plan-42"
    assert publication.attributes["poolos_objective_id"] == "objective-9"
    assert publication.attributes["poolos_sequence"] == 7
    assert publication.attributes["poolos_evidence_count"] == 1
    ranked = publication.attributes["poolos_ranked_alternatives"]
    assert ranked[0]["id"] == "solar_heater"
    assert ranked[0]["rank"] == 1


def test_blocked_decision_sets_binary_sensor_and_blocking_checks() -> None:
    projection = HomeAssistantDecisionProjector().project(
        record(outcome=DecisionOutcome.BLOCKED)
    )
    blocked = projection.publications[-1]

    assert blocked.entity_id == "binary_sensor.poolos_last_decision_blocked"
    assert blocked.state == "on"
    assert blocked.attributes["poolos_blocking_checks"] == ("Control ownership",)
    assert projection.dashboard.blocked is True
    assert projection.dashboard.selected_alternative == "none"


def test_decision_namespace_is_separate_from_simulation_namespace() -> None:
    with pytest.raises(HomeAssistantDecisionPublicationError, match="live poolos"):
        HomeAssistantDecisionStatePublication(
            "sensor.poolos_sim_last_decision", "selected"
        )


def test_entity_configuration_rejects_wrong_domains() -> None:
    with pytest.raises(HomeAssistantDecisionPublicationError, match="sensor domain"):
        HomeAssistantDecisionEntityIds(decision="binary_sensor.poolos_last_decision")


class RecordingExecutor:
    def __init__(self, *, accepted: bool = True) -> None:
        self.accepted = accepted
        self.publications: list[HomeAssistantDecisionStatePublication] = []

    def publish_state(
        self,
        publication: HomeAssistantDecisionStatePublication,
        *,
        timeout: float | None = None,
    ) -> HomeAssistantDecisionPublicationResult:
        self.publications.append(publication)
        return HomeAssistantDecisionPublicationResult(
            self.accepted, publication.entity_id
        )


def test_publisher_publishes_all_entities_once_and_then_deduplicates() -> None:
    executor = RecordingExecutor()
    publisher = HomeAssistantDecisionPublisher(executor)

    first = publisher.publish(record(), timeout=2.0)
    second = publisher.publish(record(), timeout=2.0)

    assert len(first) == 6
    assert second == ()
    assert len(executor.publications) == 6


def test_rejected_publications_are_retried() -> None:
    executor = RecordingExecutor(accepted=False)
    publisher = HomeAssistantDecisionPublisher(executor)

    assert len(publisher.publish(record())) == 6
    assert len(publisher.publish(record())) == 6
    assert len(executor.publications) == 12


def test_publication_attributes_are_immutable() -> None:
    publication = HomeAssistantDecisionProjector().project(record()).publications[0]

    with pytest.raises(TypeError):
        publication.attributes["new"] = "value"  # type: ignore[index]
