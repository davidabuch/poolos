"""Authoritative command-free filtration accounting for Home Assistant."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime, time, timedelta
from functools import partial
from typing import TYPE_CHECKING, Any, Mapping

from poolos.filtration_policy import (
    FiltrationAccountingSnapshot,
    FiltrationAccountingTracker,
    FiltrationObservation,
)
from poolos.observations import ObservationQuality, RecordedObservationEvent
from poolos.time_of_use_policy import LADWP_INITIAL_PROFILE

from .observation import ObservationSnapshot

if TYPE_CHECKING:
    from .coordinator import PoolOSCoordinator


@dataclass(slots=True)
class PoolOSFiltrationRuntime:
    """Own one derived ledger replayed from authoritative observation history."""

    coordinator: PoolOSCoordinator
    tracker: FiltrationAccountingTracker = field(
        default_factory=lambda: FiltrationAccountingTracker(
            tou_profile=LADWP_INITIAL_PROFILE
        )
    )
    assessment: FiltrationAccountingSnapshot | None = None
    restore_error: str | None = None

    async def async_restore(self, *, restored_at: datetime) -> None:
        """Replay the retained two-day evidence window off the event loop."""

        if restored_at.tzinfo is None or restored_at.utcoffset() is None:
            raise ValueError("restored_at must be timezone-aware")
        local = restored_at.astimezone(self.coordinator.local_timezone)
        start_local = datetime.combine(
            local.date() - timedelta(days=1),
            time.min,
            tzinfo=self.coordinator.local_timezone,
        )
        try:
            events = await self.coordinator.hass.async_add_executor_job(
                partial(
                    self.coordinator.observation_recorder.query,
                    start=start_local.astimezone(UTC),
                    end=restored_at.astimezone(UTC) + timedelta(microseconds=1),
                )
            )
            observations = tuple(
                item
                for item in (_observation_from_event(event) for event in events)
                if item is not None
            )
            self.assessment = self.tracker.restore(observations)
        except (OSError, TypeError, ValueError):
            self.assessment = None
            self.restore_error = "filtration_history_restore_failed"
        else:
            self.restore_error = None

    def refresh(self, snapshot: ObservationSnapshot) -> None:
        """Apply one immutable authoritative snapshot without any command path."""

        observation = _observation_from_snapshot(snapshot)
        values = {item.observation_id: item.value for item in snapshot.observations}
        self.assessment = self.tracker.observe(
            observation,
            safely_deferrable=True,
            higher_priority_requirement=any(
                values.get(concept) is True
                for concept in ("spa.active", "solar.active", "heater.active")
            ),
        )

    def diagnostics(self) -> dict[str, Any]:
        """Return bounded presentation evidence, never a second ledger."""

        if self.assessment is None:
            return {
                "state": "UNAVAILABLE",
                "reason_code": self.restore_error
                or "filtration_accounting_not_initialized",
                "persistence_source": "authoritative_observation_history",
                "authority": "none",
                "command_delivery_enabled": False,
            }
        return {
            **dict(self.assessment.diagnostics()),
            "persistence_source": "authoritative_observation_history",
        }


def _observation_from_snapshot(snapshot: ObservationSnapshot) -> FiltrationObservation:
    by_id = {item.observation_id: item for item in snapshot.observations}
    stale_sources = set(snapshot.stale_entities)
    return _filtration_observation(
        observed_at=snapshot.generated_at,
        by_id=by_id,
        stale_sources=stale_sources,
        snapshot_healthy=snapshot.healthy,
    )


def _observation_from_event(
    event: RecordedObservationEvent,
) -> FiltrationObservation | None:
    by_id = {
        str(item.get("observation_id")): item
        for item in event.observations
        if item.get("observation_id") is not None
    }
    health = event.health
    stale_sources = {
        str(item) for item in health.get("stale_entities", ()) if item is not None
    }
    return _filtration_observation(
        observed_at=event.recorded_at,
        by_id=by_id,
        stale_sources=stale_sources,
        snapshot_healthy=bool(health.get("healthy", False)),
    )


def _filtration_observation(
    *,
    observed_at: datetime,
    by_id: Mapping[str, Any],
    stale_sources: set[str],
    snapshot_healthy: bool,
) -> FiltrationObservation:
    circulation_concepts = ("pool.active", "spa.active", "pump.rpm")
    circulation_usable = snapshot_healthy and all(
        _usable(by_id.get(concept), stale_sources) for concept in circulation_concepts
    )
    temperature_usable = snapshot_healthy and _usable(
        by_id.get("pool.temperature"), stale_sources
    )
    return FiltrationObservation(
        observed_at=observed_at,
        pool_active=_boolean(_value(by_id.get("pool.active"))),
        spa_active=_boolean(_value(by_id.get("spa.active"))),
        pump_rpm=_integer(_value(by_id.get("pump.rpm"))),
        water_temperature_f=_number(_value(by_id.get("pool.temperature"))),
        circulation_evidence_usable=circulation_usable,
        temperature_evidence_usable=temperature_usable,
        confirmed_grid_outage=(
            _value(by_id.get("grid.outage_active")) is True
        ),
    )


def _value(item: Any) -> Any:
    if isinstance(item, Mapping):
        return item.get("value")
    return getattr(item, "value", None)


def _usable(item: Any, stale_sources: set[str]) -> bool:
    if item is None:
        return False
    if isinstance(item, Mapping):
        quality = item.get("quality")
        source_id = item.get("source_id")
    else:
        quality = getattr(item, "quality", None)
        source_id = getattr(item, "source_id", None)
    quality_value = getattr(quality, "value", quality)
    return quality_value == ObservationQuality.GOOD.value and source_id not in stale_sources


def _boolean(value: Any) -> bool | None:
    return value if isinstance(value, bool) else None


def _integer(value: Any) -> int | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    return round(value)


def _number(value: Any) -> float | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    return float(value)


__all__ = ["PoolOSFiltrationRuntime"]
