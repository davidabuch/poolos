"""Read-only commissioning coordinator for PoolOS."""

from __future__ import annotations

import asyncio
from collections.abc import Callable
from datetime import UTC, datetime, time, timedelta
from functools import partial
import logging
from pathlib import Path
from zoneinfo import ZoneInfo

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import Event, HomeAssistant
from homeassistant.helpers.event import async_track_state_change_event
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator

from poolos.behavioral_inference import BehavioralInferenceEngine, BehavioralInferenceReport
from poolos.daily_retrospective import (
    DailyOperationalRetrospective,
    DailyOperationalRetrospectiveEngine,
    PersistentRecommendationRecorder,
)
from poolos.homeassistant.observations import HomeAssistantState
from poolos.operator_recommendation import OperatorRecommendation
from poolos.observations import PersistentObservationRecorder, PoolObservation

from .const import DOMAIN, INTEGRATION_VERSION, OBSERVATION_UPDATE_INTERVAL
from poolos.evidence_export import DailyEvidenceExporter
from .observation import (
    ObservationSnapshot,
    build_snapshot,
    configured_entity_ids,
    configured_entity_mapping,
)
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
        self.operator_recommendation_published_at: datetime | None = None
        self.behavioral_inference_engine = BehavioralInferenceEngine()
        self.behavioral_inference_report: BehavioralInferenceReport | None = None
        self.daily_retrospective_engine = DailyOperationalRetrospectiveEngine()
        self.current_daily_retrospective: DailyOperationalRetrospective | None = None
        self.latest_completed_daily_retrospective: DailyOperationalRetrospective | None = None
        self.local_timezone = ZoneInfo(hass.config.time_zone)
        storage_root = Path(hass.config.path(".storage", DOMAIN, entry.entry_id))
        self.observation_recorder = PersistentObservationRecorder(storage_root / "observations")
        self.recommendation_recorder = PersistentRecommendationRecorder(storage_root / "recommendations")
        self.evidence_exporter = DailyEvidenceExporter(Path(hass.config.path("poolos_logs")), self.local_timezone)
        self._observation_lock = asyncio.Lock()
        self._remove_state_listener: Callable[[], None] | None = None
        self._event_refresh_count = 0
        self._reconciliation_refresh_count = 0
        self._last_observation_trigger = "not_started"

    async def _async_update_data(self) -> ObservationSnapshot:
        """Run the periodic reconciliation/backstop observation refresh."""

        async with self._observation_lock:
            self._reconciliation_refresh_count += 1
            return await self._async_observe(
                observed_at=datetime.now(UTC),
                trigger="periodic_reconciliation",
            )

    def async_start_event_observation(self) -> None:
        """Subscribe to mapped HA state changes for immediate observation."""

        if self._remove_state_listener is not None:
            return
        configured = {**dict(self.config_entry.data), **dict(self.config_entry.options)}
        entity_ids = configured_entity_ids(configured)
        if not entity_ids:
            return
        self._remove_state_listener = async_track_state_change_event(
            self.hass,
            entity_ids,
            self._async_mapped_state_changed,
        )

    def async_stop_event_observation(self) -> None:
        """Remove the mapped-state subscription if it is active."""

        if self._remove_state_listener is None:
            return
        self._remove_state_listener()
        self._remove_state_listener = None

    async def _async_mapped_state_changed(self, event: Event) -> None:
        """Capture a mapped HA state/attribute change without waiting for polling."""

        async with self._observation_lock:
            self._event_refresh_count += 1
            timestamp = event.time_fired.astimezone(UTC)
            snapshot = await self._async_observe(
                observed_at=timestamp,
                trigger="state_change_event",
            )
            self.async_set_updated_data(snapshot)

    async def _async_observe(
        self,
        *,
        observed_at: datetime,
        trigger: str,
    ) -> ObservationSnapshot:
        """Build, evaluate, and durably record one read-only HA observation."""

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
                last_reported=getattr(state, "last_reported", state.last_updated),
                attributes=state.attributes,
            )
        snapshot = build_snapshot(
            options=configured,
            states=states,
            now=observed_at,
        )
        self._last_observation_trigger = trigger
        self.shadow_runtime.evaluate(snapshot)
        health = {
            "healthy": snapshot.healthy,
            "missing_required": list(snapshot.missing_required),
            "unavailable_entities": list(snapshot.unavailable_entities),
            "stale_entities": list(snapshot.stale_entities),
        }
        try:
            result = await self.hass.async_add_executor_job(
                partial(
                    self._record_infer_and_retro,
                    recorded_at=snapshot.generated_at,
                    observations=snapshot.observations,
                    health=health,
                    recommendation=self.operator_recommendation,
                    recommendation_published_at=self.operator_recommendation_published_at,
                )
            )
            if result is not None:
                inference, current_retro, completed_retro = result
                self.behavioral_inference_report = inference
                self.current_daily_retrospective = current_retro
                self.latest_completed_daily_retrospective = completed_retro
        except (OSError, TypeError, ValueError):
            LOGGER.exception("PoolOS persistent observation/inference/retrospective update failed")
        return snapshot

    def _record_infer_and_retro(
        self,
        *,
        recorded_at: datetime,
        observations: tuple[PoolObservation, ...],
        health: dict[str, object],
        recommendation: OperatorRecommendation | None,
        recommendation_published_at: datetime | None,
    ) -> tuple[
        BehavioralInferenceReport,
        DailyOperationalRetrospective,
        DailyOperationalRetrospective,
    ] | None:
        """Persist evidence and refresh inference/retrospective only on durable writes."""

        wrote = self.observation_recorder.record_snapshot(
            recorded_at=recorded_at,
            observations=observations,
            health=health,
        )
        if not wrote:
            return None

        try:
            self.evidence_exporter.export_day(self.observation_recorder, recorded_at)
        except (OSError, TypeError, ValueError):
            self.evidence_exporter.last_error = "daily evidence export failed"
            LOGGER.exception("PoolOS daily evidence export failed")

        if recommendation_published_at is not None:
            try:
                self.recommendation_recorder.record(
                    recommendation,
                    published_at=recommendation_published_at,
                )
            except OSError:
                LOGGER.exception("PoolOS recommendation evidence persistence failed")

        inference_start = recorded_at - timedelta(days=7)
        inference_records = self.observation_recorder.query(
            start=inference_start,
            end=recorded_at + timedelta(microseconds=1),
        )
        inference = self.behavioral_inference_engine.infer(inference_records)

        local_now = recorded_at.astimezone(self.local_timezone)
        current_start_local = datetime.combine(local_now.date(), time.min, tzinfo=self.local_timezone)
        current_start = current_start_local.astimezone(UTC)
        next_start_local = current_start_local + timedelta(days=1)
        next_start = next_start_local.astimezone(UTC)
        current_end = min(recorded_at + timedelta(microseconds=1), next_start)
        current_query_start = current_start - self.daily_retrospective_engine.maximum_evidence_gap
        current_records = self.observation_recorder.query(start=current_query_start, end=current_end)
        current_advisories = self.recommendation_recorder.query(start=current_start, end=current_end)
        current_recommendation = _recommendation_for_window(
            recommendation,
            recommendation_published_at,
            start=current_start,
            end=current_end,
        )
        current_retro = self.daily_retrospective_engine.generate(
            current_records,
            window_start=current_start,
            window_end=current_end,
            report_date=local_now.date().isoformat(),
            advisories=current_advisories,
            recommendation=current_recommendation,
            complete_day=False,
        )

        previous_start_local = current_start_local - timedelta(days=1)
        previous_start = previous_start_local.astimezone(UTC)
        previous_end = current_start
        previous_query_start = previous_start - self.daily_retrospective_engine.maximum_evidence_gap
        previous_records = self.observation_recorder.query(start=previous_query_start, end=previous_end)
        previous_advisories = self.recommendation_recorder.query(start=previous_start, end=previous_end)
        previous_recommendation = _recommendation_for_window(
            recommendation,
            recommendation_published_at,
            start=previous_start,
            end=previous_end,
        )
        completed_retro = self.daily_retrospective_engine.generate(
            previous_records,
            window_start=previous_start,
            window_end=previous_end,
            report_date=previous_start_local.date().isoformat(),
            advisories=previous_advisories,
            recommendation=previous_recommendation,
            complete_day=True,
        )
        return inference, current_retro, completed_retro

    def publish_operator_recommendation(
        self,
        recommendation: OperatorRecommendation | None,
        *,
        published_at: datetime | None = None,
    ) -> None:
        """Publish read-only recommendation evidence for diagnostic presentation."""
        if published_at is not None and (published_at.tzinfo is None or published_at.utcoffset() is None):
            raise ValueError("published_at must be timezone-aware")
        self.operator_recommendation = recommendation
        self.operator_recommendation_published_at = (published_at or datetime.now(UTC)).astimezone(UTC)

    def lifecycle_diagnostics(self) -> dict[str, object]:
        """Return stable integration lifecycle data for diagnostics and health."""

        snapshot = self.data
        return {
            "integration_version": INTEGRATION_VERSION,
            "lifecycle": "loaded",
            "observation_enabled": True,
            "event_driven_observation_enabled": self._remove_state_listener is not None,
            "periodic_reconciliation_enabled": True,
            "event_refresh_count": self._event_refresh_count,
            "reconciliation_refresh_count": self._reconciliation_refresh_count,
            "last_observation_trigger": self._last_observation_trigger,
            "command_delivery_enabled": False,
            "observation_healthy": None if snapshot is None else snapshot.healthy,
            "refreshed_at": None if snapshot is None else snapshot.generated_at.isoformat(),
            "shadow_runtime_enabled": True,
            "persistent_observation_recorder": self.observation_recorder.diagnostics(),
            "persistent_recommendation_recorder": self.recommendation_recorder.diagnostics(),
            "daily_evidence_export": self.evidence_exporter.diagnostics(),
            "behavioral_inference": (
                None if self.behavioral_inference_report is None else self.behavioral_inference_report.to_dict()
            ),
            "current_daily_retrospective": (
                None if self.current_daily_retrospective is None else self.current_daily_retrospective.to_dict()
            ),
            "latest_completed_daily_retrospective": (
                None
                if self.latest_completed_daily_retrospective is None
                else self.latest_completed_daily_retrospective.to_dict()
            ),
            "shadow_runtime": self.shadow_runtime.diagnostics(),
            "operator_recommendation": (
                None if self.operator_recommendation is None else self.operator_recommendation.to_dict()
            ),
            "operator_recommendation_published_at": (
                None
                if self.operator_recommendation_published_at is None
                else self.operator_recommendation_published_at.isoformat()
            ),
        }


def _recommendation_for_window(
    recommendation: OperatorRecommendation | None,
    published_at: datetime | None,
    *,
    start: datetime,
    end: datetime,
) -> OperatorRecommendation | None:
    """Return advisory evidence only when its publication is inside the report window."""

    if recommendation is None or published_at is None:
        return None
    if start <= published_at < end:
        return recommendation
    return None
