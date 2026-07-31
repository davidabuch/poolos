"""Home Assistant projections for PoolOS decision intelligence."""

from __future__ import annotations

from dataclasses import dataclass, field
from types import MappingProxyType
from typing import Any, Mapping, Protocol

from poolos.decision_flight_recorder import DecisionFlightRecord
from poolos.decision_intelligence import DecisionOutcome


class HomeAssistantDecisionPublicationError(ValueError):
    """Raised when a decision entity projection is invalid."""


@dataclass(frozen=True, slots=True)
class HomeAssistantDecisionEntityIds:
    """Stable Home Assistant entity IDs used by decision intelligence."""

    decision: str = "sensor.poolos_last_decision"
    summary: str = "sensor.poolos_last_decision_summary"
    selected_alternative: str = "sensor.poolos_last_selected_alternative"
    confidence: str = "sensor.poolos_last_decision_confidence"
    next_change: str = "sensor.poolos_last_decision_next_change"
    blocked: str = "binary_sensor.poolos_last_decision_blocked"

    def __post_init__(self) -> None:
        values = (
            self.decision,
            self.summary,
            self.selected_alternative,
            self.confidence,
            self.next_change,
            self.blocked,
        )
        normalized = tuple(_decision_entity_id(value) for value in values)
        if len(normalized) != len(set(normalized)):
            raise HomeAssistantDecisionPublicationError(
                "decision entity IDs must be unique"
            )
        names = (
            "decision",
            "summary",
            "selected_alternative",
            "confidence",
            "next_change",
            "blocked",
        )
        for name, value in zip(names, normalized, strict=True):
            object.__setattr__(self, name, value)
        if not self.blocked.startswith("binary_sensor."):
            raise HomeAssistantDecisionPublicationError(
                "blocked entity must use the binary_sensor domain"
            )
        for value in normalized[:-1]:
            if not value.startswith("sensor."):
                raise HomeAssistantDecisionPublicationError(
                    "decision value entities must use the sensor domain"
                )


@dataclass(frozen=True, slots=True)
class HomeAssistantDecisionStatePublication:
    """One transport-neutral decision state update for Home Assistant."""

    entity_id: str
    state: str
    attributes: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        object.__setattr__(self, "entity_id", _decision_entity_id(self.entity_id))
        if not self.state.strip():
            raise HomeAssistantDecisionPublicationError(
                "published decision state must not be empty"
            )
        object.__setattr__(self, "attributes", MappingProxyType(dict(self.attributes)))


@dataclass(frozen=True, slots=True)
class HomeAssistantDecisionPublicationResult:
    """Acknowledgement returned by a decision-state publication adapter."""

    accepted: bool
    entity_id: str

    def __post_init__(self) -> None:
        object.__setattr__(self, "entity_id", _decision_entity_id(self.entity_id))


class HomeAssistantDecisionStateExecutor(Protocol):
    """Port implemented by a Home Assistant decision-state adapter."""

    def publish_state(
        self,
        publication: HomeAssistantDecisionStatePublication,
        *,
        timeout: float | None = None,
    ) -> HomeAssistantDecisionPublicationResult: ...


@dataclass(frozen=True, slots=True)
class HomeAssistantDecisionDashboard:
    """Compact dashboard-ready projection of the latest decision."""

    title: str
    status: str
    summary: str
    selected_alternative: str
    confidence_percent: int
    next_change: str
    blocked: bool
    decision_id: str
    evaluated_at: str
    human_text: str

    def as_dict(self) -> dict[str, Any]:
        """Return a deterministic dashboard payload."""

        return {
            "title": self.title,
            "status": self.status,
            "summary": self.summary,
            "selected_alternative": self.selected_alternative,
            "confidence_percent": self.confidence_percent,
            "next_change": self.next_change,
            "blocked": self.blocked,
            "decision_id": self.decision_id,
            "evaluated_at": self.evaluated_at,
            "human_text": self.human_text,
        }


@dataclass(frozen=True, slots=True)
class HomeAssistantDecisionProjection:
    """Complete Home Assistant projection for one Flight Recorder entry."""

    publications: tuple[HomeAssistantDecisionStatePublication, ...]
    dashboard: HomeAssistantDecisionDashboard


@dataclass(frozen=True, slots=True)
class HomeAssistantDecisionProjector:
    """Map a canonical decision record into stable Home Assistant entities."""

    entity_ids: HomeAssistantDecisionEntityIds = field(
        default_factory=HomeAssistantDecisionEntityIds
    )

    def project(self, record: DecisionFlightRecord) -> HomeAssistantDecisionProjection:
        """Build all entity states and the dashboard payload for one record."""

        decision = record.decision
        selected = decision.selected_alternative
        selected_label = selected.label if selected is not None else "none"
        next_change = decision.next_change or "none"
        confidence_percent = round(decision.confidence * 100)
        blocked = decision.outcome is DecisionOutcome.BLOCKED
        common = {
            "poolos_decision_id": decision.decision_id,
            "poolos_plan_id": record.plan_id,
            "poolos_objective_id": record.objective_id,
            "poolos_sequence": record.sequence,
            "poolos_evaluated_at": decision.evaluated_at.isoformat(),
            "poolos_recorded_at": record.recorded_at.isoformat(),
            "poolos_outcome": decision.outcome.value,
            "poolos_confidence": decision.confidence,
            "poolos_selected_alternative_id": decision.selected_alternative_id,
            "poolos_human_explanation": record.human_text,
            "poolos_technical_explanation": record.technical_text,
            "poolos_evidence_count": len(decision.evidence),
            "poolos_check_count": len(decision.checks),
            "poolos_alternative_count": len(decision.alternatives),
            "poolos_blocking_checks": tuple(
                check.label for check in decision.blocking_checks
            ),
            "poolos_ranked_alternatives": tuple(
                {
                    "id": alternative.alternative_id,
                    "label": alternative.label,
                    "rank": alternative.rank,
                    "status": alternative.status.value,
                    "score": alternative.score,
                }
                for alternative in decision.alternatives
            ),
        }
        publications = (
            self._publication(
                self.entity_ids.decision,
                decision.outcome.value,
                common,
                friendly_name="PoolOS Last Decision",
                icon="mdi:source-branch",
            ),
            self._publication(
                self.entity_ids.summary,
                decision.summary,
                common,
                friendly_name="PoolOS Last Decision Summary",
                icon="mdi:text-box-outline",
            ),
            self._publication(
                self.entity_ids.selected_alternative,
                selected_label,
                common,
                friendly_name="PoolOS Last Selected Alternative",
                icon="mdi:check-decagram-outline",
            ),
            self._publication(
                self.entity_ids.confidence,
                str(confidence_percent),
                common,
                friendly_name="PoolOS Last Decision Confidence",
                icon="mdi:gauge",
                extra={"unit_of_measurement": "%"},
            ),
            self._publication(
                self.entity_ids.next_change,
                next_change,
                common,
                friendly_name="PoolOS Last Decision Next Change",
                icon="mdi:update",
            ),
            self._publication(
                self.entity_ids.blocked,
                "on" if blocked else "off",
                common,
                friendly_name="PoolOS Last Decision Blocked",
                icon="mdi:shield-alert-outline" if blocked else "mdi:shield-check-outline",
            ),
        )
        dashboard = HomeAssistantDecisionDashboard(
            title="PoolOS Decision Intelligence",
            status=decision.outcome.value,
            summary=decision.summary,
            selected_alternative=selected_label,
            confidence_percent=confidence_percent,
            next_change=next_change,
            blocked=blocked,
            decision_id=decision.decision_id,
            evaluated_at=decision.evaluated_at.isoformat(),
            human_text=record.human_text,
        )
        return HomeAssistantDecisionProjection(publications, dashboard)

    @staticmethod
    def _publication(
        entity_id: str,
        state: str,
        common: Mapping[str, Any],
        *,
        friendly_name: str,
        icon: str,
        extra: Mapping[str, Any] | None = None,
    ) -> HomeAssistantDecisionStatePublication:
        attributes = dict(common)
        attributes.update({"friendly_name": friendly_name, "icon": icon})
        if extra is not None:
            attributes.update(extra)
        return HomeAssistantDecisionStatePublication(entity_id, state, attributes)


@dataclass(slots=True)
class HomeAssistantDecisionPublisher:
    """Idempotently publish a complete latest-decision projection."""

    executor: HomeAssistantDecisionStateExecutor
    projector: HomeAssistantDecisionProjector = field(
        default_factory=HomeAssistantDecisionProjector
    )
    _last_publications: dict[str, HomeAssistantDecisionStatePublication] = field(
        default_factory=dict,
        init=False,
        repr=False,
    )

    def publish(
        self,
        record: DecisionFlightRecord,
        *,
        timeout: float | None = None,
    ) -> tuple[HomeAssistantDecisionPublicationResult, ...]:
        """Publish changed entity states and retain accepted states for deduplication."""

        projection = self.projector.project(record)
        results: list[HomeAssistantDecisionPublicationResult] = []
        for publication in projection.publications:
            if self._last_publications.get(publication.entity_id) == publication:
                continue
            result = self.executor.publish_state(publication, timeout=timeout)
            results.append(result)
            if result.accepted:
                self._last_publications[publication.entity_id] = publication
        return tuple(results)


def _decision_entity_id(value: str) -> str:
    entity_id = value.strip().lower()
    if "." not in entity_id:
        raise HomeAssistantDecisionPublicationError(
            "entity_id must be a Home Assistant entity ID"
        )
    domain, object_id = entity_id.split(".", 1)
    if domain not in {"sensor", "binary_sensor"}:
        raise HomeAssistantDecisionPublicationError(
            "decision publication entities must use sensor or binary_sensor"
        )
    if not object_id.startswith("poolos_") or object_id.startswith("poolos_sim_"):
        raise HomeAssistantDecisionPublicationError(
            "decision publication entity IDs must use the live poolos_ namespace"
        )
    if not object_id or any(character.isspace() for character in entity_id):
        raise HomeAssistantDecisionPublicationError("entity_id is invalid")
    return entity_id
