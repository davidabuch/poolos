"""Home Assistant projections for PoolOS orchestration runtime diagnostics."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Mapping

from poolos.homeassistant.decision_intelligence import (
    HomeAssistantDecisionPublicationResult,
    HomeAssistantDecisionStateExecutor,
    HomeAssistantDecisionStatePublication,
)
from poolos.runtime_diagnostics import SupervisoryRuntimeSnapshot


@dataclass(frozen=True, slots=True)
class HomeAssistantRuntimeDiagnosticEntityIds:
    """Stable entity IDs for supervisory runtime health."""

    health: str = "sensor.poolos_runtime_health"
    last_trigger: str = "sensor.poolos_runtime_last_trigger"
    last_status: str = "sensor.poolos_runtime_last_status"
    evaluation_count: str = "sensor.poolos_runtime_evaluation_count"
    active_decision: str = "sensor.poolos_runtime_active_decision"
    decision_changed: str = "binary_sensor.poolos_runtime_decision_changed"
    context_valid: str = "binary_sensor.poolos_runtime_context_valid"
    restart_recovery: str = "sensor.poolos_runtime_restart_recovery"


@dataclass(frozen=True, slots=True)
class HomeAssistantRuntimeDiagnosticProjection:
    """Complete transport-neutral runtime diagnostics projection."""

    publications: tuple[HomeAssistantDecisionStatePublication, ...]


@dataclass(frozen=True, slots=True)
class HomeAssistantRuntimeDiagnosticProjector:
    """Project one runtime snapshot into stable Home Assistant states."""

    entity_ids: HomeAssistantRuntimeDiagnosticEntityIds = field(
        default_factory=HomeAssistantRuntimeDiagnosticEntityIds
    )

    def project(
        self,
        snapshot: SupervisoryRuntimeSnapshot,
    ) -> HomeAssistantRuntimeDiagnosticProjection:
        common: Mapping[str, Any] = {
            "poolos_context_id": snapshot.context_id,
            "poolos_last_evaluated_at": snapshot.last_evaluated_at.isoformat(),
            "poolos_runtime_mode": snapshot.runtime_mode,
            "poolos_previous_decision_id": snapshot.previous_decision_id,
            "poolos_active_decision_id": snapshot.active_decision_id,
            "poolos_stability_disposition": snapshot.stability_disposition,
            "poolos_restart_recovery_status": snapshot.restart_recovery_status,
            "poolos_replay_status": snapshot.replay_status,
            "poolos_next_reevaluation": (
                snapshot.next_reevaluation.isoformat()
                if snapshot.next_reevaluation is not None
                else None
            ),
            "poolos_blockers": snapshot.blockers,
            "poolos_diagnostics": dict(snapshot.diagnostics),
        }
        publications = (
            self._publication(self.entity_ids.health, snapshot.health.value, common),
            self._publication(self.entity_ids.last_trigger, snapshot.last_trigger, common),
            self._publication(self.entity_ids.last_status, snapshot.last_status, common),
            self._publication(
                self.entity_ids.evaluation_count,
                str(snapshot.evaluation_count),
                common,
            ),
            self._publication(
                self.entity_ids.active_decision,
                snapshot.active_decision_id or "none",
                common,
            ),
            self._publication(
                self.entity_ids.decision_changed,
                "on" if snapshot.decision_changed else "off",
                common,
            ),
            self._publication(
                self.entity_ids.context_valid,
                "on" if snapshot.context_valid else "off",
                common,
            ),
            self._publication(
                self.entity_ids.restart_recovery,
                snapshot.restart_recovery_status or "not_run",
                common,
            ),
        )
        return HomeAssistantRuntimeDiagnosticProjection(publications)

    @staticmethod
    def _publication(
        entity_id: str,
        state: str,
        attributes: Mapping[str, Any],
    ) -> HomeAssistantDecisionStatePublication:
        return HomeAssistantDecisionStatePublication(entity_id, state, attributes)


@dataclass(slots=True)
class HomeAssistantRuntimeDiagnosticPublisher:
    """Idempotently publish changed runtime diagnostic states."""

    executor: HomeAssistantDecisionStateExecutor
    projector: HomeAssistantRuntimeDiagnosticProjector = field(
        default_factory=HomeAssistantRuntimeDiagnosticProjector
    )
    _last: dict[str, HomeAssistantDecisionStatePublication] = field(
        default_factory=dict,
        init=False,
        repr=False,
    )

    def publish(
        self,
        snapshot: SupervisoryRuntimeSnapshot,
        *,
        timeout: float | None = None,
    ) -> tuple[HomeAssistantDecisionPublicationResult, ...]:
        results: list[HomeAssistantDecisionPublicationResult] = []
        for publication in self.projector.project(snapshot).publications:
            if self._last.get(publication.entity_id) == publication:
                continue
            result = self.executor.publish_state(publication, timeout=timeout)
            results.append(result)
            if result.accepted:
                self._last[publication.entity_id] = publication
        return tuple(results)
