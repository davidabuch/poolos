"""Catalog-driven dashboard comparisons for live and simulated PoolOS state."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from types import MappingProxyType
from typing import Any, Mapping

from poolos.observations import ObservationSourceKind, ObservationStore, PoolObservation

from .catalog import HomeAssistantEntityCatalog


class DashboardComparisonStatus(str, Enum):
    """Comparison outcome for one catalog observation."""

    MATCH = "match"
    DRIFT = "drift"
    LIVE_ONLY = "live_only"
    SIMULATED_ONLY = "simulated_only"
    UNAVAILABLE = "unavailable"
    NOT_COMPARABLE = "not_comparable"


@dataclass(frozen=True, slots=True)
class DashboardDriftPolicy:
    """Per-observation numeric tolerances used by dashboard comparisons."""

    default_numeric_tolerance: float = 0.0
    tolerances: Mapping[str, float] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if self.default_numeric_tolerance < 0:
            raise ValueError("default_numeric_tolerance must not be negative")
        normalized = dict(self.tolerances)
        for observation_id, tolerance in normalized.items():
            if not observation_id.strip():
                raise ValueError("drift-policy observation IDs must not be empty")
            if tolerance < 0:
                raise ValueError("drift tolerances must not be negative")
        object.__setattr__(self, "tolerances", MappingProxyType(normalized))

    def tolerance_for(self, observation_id: str) -> float:
        return self.tolerances.get(observation_id, self.default_numeric_tolerance)


@dataclass(frozen=True, slots=True)
class DashboardComparison:
    """Side-by-side live and simulated state for one canonical observation."""

    observation_id: str
    live_entity_id: str | None
    simulated_entity_id: str | None
    live: PoolObservation | None
    simulated: PoolObservation | None
    status: DashboardComparisonStatus
    delta: float | None = None
    tolerance: float | None = None


@dataclass(frozen=True, slots=True)
class HomeAssistantSimulationDashboard:
    """Build stable live-versus-simulated dashboard rows from a catalog and store."""

    catalog: HomeAssistantEntityCatalog
    drift_policy: DashboardDriftPolicy = DashboardDriftPolicy()

    def comparisons(self, store: ObservationStore) -> tuple[DashboardComparison, ...]:
        rows: list[DashboardComparison] = []
        for definition in self.catalog.definitions:
            if not definition.observation_enabled or not definition.publication_enabled:
                continue
            live = store.get(
                definition.observation_id,
                source_kind=ObservationSourceKind.LIVE,
            )
            simulated = store.get(
                definition.observation_id,
                source_kind=ObservationSourceKind.SIMULATED,
            )
            status, delta, tolerance = self._compare(
                definition.observation_id,
                live,
                simulated,
            )
            rows.append(
                DashboardComparison(
                    observation_id=definition.observation_id,
                    live_entity_id=definition.observed_entity_id,
                    simulated_entity_id=definition.simulated_entity_id,
                    live=live,
                    simulated=simulated,
                    status=status,
                    delta=delta,
                    tolerance=tolerance,
                )
            )
        return tuple(rows)

    def summary(self, store: ObservationStore) -> Mapping[str, int]:
        counts = {status.value: 0 for status in DashboardComparisonStatus}
        for comparison in self.comparisons(store):
            counts[comparison.status.value] += 1
        return MappingProxyType(counts)

    def _compare(
        self,
        observation_id: str,
        live: PoolObservation | None,
        simulated: PoolObservation | None,
    ) -> tuple[DashboardComparisonStatus, float | None, float | None]:
        if live is None and simulated is None:
            return DashboardComparisonStatus.UNAVAILABLE, None, None
        if live is None:
            return DashboardComparisonStatus.SIMULATED_ONLY, None, None
        if simulated is None:
            return DashboardComparisonStatus.LIVE_ONLY, None, None

        numeric = _numeric_pair(live.value, simulated.value)
        if numeric is not None:
            live_value, simulated_value = numeric
            delta = simulated_value - live_value
            tolerance = self.drift_policy.tolerance_for(observation_id)
            status = (
                DashboardComparisonStatus.MATCH
                if abs(delta) <= tolerance
                else DashboardComparisonStatus.DRIFT
            )
            return status, delta, tolerance
        if type(live.value) is type(simulated.value):
            status = (
                DashboardComparisonStatus.MATCH
                if live.value == simulated.value
                else DashboardComparisonStatus.DRIFT
            )
            return status, None, None
        return DashboardComparisonStatus.NOT_COMPARABLE, None, None


def _numeric_pair(live: Any, simulated: Any) -> tuple[float, float] | None:
    if isinstance(live, bool) or isinstance(simulated, bool):
        return None
    if isinstance(live, (int, float)) and isinstance(simulated, (int, float)):
        return float(live), float(simulated)
    return None


__all__ = [
    "DashboardComparison",
    "DashboardComparisonStatus",
    "DashboardDriftPolicy",
    "HomeAssistantSimulationDashboard",
]
