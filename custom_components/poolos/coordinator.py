"""Read-only commissioning coordinator for PoolOS."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from functools import partial
import logging
from pathlib import Path

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator

from poolos.behavioral_inference import BehavioralInferenceEngine, BehavioralInferenceReport
from poolos.homeassistant.observations import HomeAssistantState
from poolos.operator_recommendation import OperatorRecommendation
from poolos.observations import PersistentObservationRecorder, PoolObservation

from .const import DOMAIN, INTEGRATION_VERSION, OBSERVATION_UPDATE_INTERVAL
from .observation import ObservationSnapshot, build_snapshot, configured_entity_mapping
from .shadow import HomeAssistantShadowRuntime

LOGGER = logging.getLogger(__name__)


class PoolOSCoordinator(DataUpdateCoordinator[ObservationSnapshot]):
    """Read configured Home Assistant entities without invoking services."""

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry) -> None:
        """Initialize the read-only commissioning coordinator."""
        super().__init__(
            hass,
            logger=LOGGER,
            name=f"{DOMAIN}_{entry.entry_id}",
            update_interval=OBSERVATION_UPDATE_INTERVAL,
        )
        self.config_entry = entry
        self.shadow_runtime = HomeAssistantShadowRuntime.create()
        self.operator_recommendation: OperatorRecommendation | None = None
        self.behavioral_inference_engine = BehavioralInferenceEngine()
        self.behavioral_inference_report: BehavioralInferenceReport | None = None
        history_root = Path(hass.config.path(".storage", DOMAIN, entry.entry_id, "observations"))
        self.observation_recorder = PersistentObservationRecorder(history_root)

    async def _async_update_data(self) -> ObservationSnapshot:
        """Build a canonical snapshot from the current Home Assistant state machine."""

        configured = {**dict(self.config_entry.data), **dict(self.config_entry.options)}
        states: dict[str, HomeAssistantState] = {}
        for entity_id in configured_entity_mapping(configured).values():
            state = self.hass.states.get(entity_id)
            if state is None:
                continue
            states[entity_id] = HomeAssistantState(
                entity_id=entity_id,
                state=state.state,
                last_changed=state.last_changed,
                last_updated=state.last_updated,
                attributes=state.attributes,
            )
        snapshot = build_snapshot(
            options=configured,
            states=states,
            now=datetime.now(UTC),
        )
        self.shadow_runtime.evaluate(snapshot)
        health = {
            "healthy": snapshot.healthy,
            "missing_required": list(snapshot.missing_required),
            "unavailable_entities": list(snapshot.unavailable_entities),
            "stale_entities": list(snapshot.stale_entities),
        }
        try:
            report = await self.hass.async_add_executor_job(
                partial(
                    self._record_and_infer,
                    recorded_at=snapshot.generated_at,
                    observations=snapshot.observations,
                    health=health,
                )
            )
            if report is not None:
                self.behavioral_inference_report = report
        except (OSError, TypeError, ValueError):
            LOGGER.exception("PoolOS persistent observation/inference update failed")
        return snapshot

    def _record_and_infer(
        self,
        *,
        recorded_at: datetime,
        observations: tuple[PoolObservation, ...],
        health: dict[str, object],
    ) -> BehavioralInferenceReport | None:
        """Persist evidence and refresh inference only when durable history changes."""

        wrote = self.observation_recorder.record_snapshot(
            recorded_at=recorded_at,
            observations=observations,
            health=health,
        )
        if not wrote:
            return None
        start = recorded_at - timedelta(days=7)
        records = self.observation_recorder.query(start=start, end=recorded_at + timedelta(microseconds=1))
        return self.behavioral_inference_engine.infer(records)

    def publish_operator_recommendation(self, recommendation: OperatorRecommendation | None) -> None:
        """Publish read-only recommendation evidence for diagnostic presentation."""
        self.operator_recommendation = recommendation

    def lifecycle_diagnostics(self) -> dict[str, object]:
        """Return stable integration lifecycle data for diagnostics and health."""

        snapshot = self.data
        return {
            "integration_version": INTEGRATION_VERSION,
            "lifecycle": "loaded",
            "observation_enabled": True,
            "command_delivery_enabled": False,
            "observation_healthy": None if snapshot is None else snapshot.healthy,
            "refreshed_at": None if snapshot is None else snapshot.generated_at.isoformat(),
            "shadow_runtime_enabled": True,
            "persistent_observation_recorder": self.observation_recorder.diagnostics(),
            "behavioral_inference": (
                None if self.behavioral_inference_report is None else self.behavioral_inference_report.to_dict()
            ),
            "shadow_runtime": self.shadow_runtime.diagnostics(),
            "operator_recommendation": (
                None if self.operator_recommendation is None else self.operator_recommendation.to_dict()
            ),
        }
