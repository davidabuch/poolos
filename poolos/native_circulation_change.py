"""Authoritative native circulation change tracking for execution wake-ups."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable

from .observations import PoolObservation

NATIVE_CIRCULATION_EXECUTION_CONCEPTS = (
    "pool.active",
    "spa.active",
    "pump.rpm",
    "pool.pump_circuit_configured_speed",
    "solar.active",
    "heater.active",
    "waterfall.active",
    "jets.active",
    "slide.active",
)


def native_circulation_fingerprint(
    observations: Iterable[PoolObservation],
) -> tuple[tuple[str, str], ...]:
    """Return one deterministic fingerprint of circulation-relevant native truth."""

    by_id = {item.observation_id: item.value for item in observations}
    return tuple(
        (
            concept,
            "<missing>" if concept not in by_id else repr(by_id[concept]),
        )
        for concept in NATIVE_CIRCULATION_EXECUTION_CONCEPTS
    )


@dataclass(slots=True)
class NativeCirculationChangeTracker:
    """Detect meaningful native circulation changes without diagnostic events."""

    _previous: tuple[tuple[str, str], ...] | None = None

    def observe(self, observations: Iterable[PoolObservation]) -> bool:
        """Return True only after baseline when circulation truth changes."""

        current = native_circulation_fingerprint(observations)
        if self._previous is None:
            self._previous = current
            return False
        changed = current != self._previous
        self._previous = current
        return changed


__all__ = [
    "NATIVE_CIRCULATION_EXECUTION_CONCEPTS",
    "NativeCirculationChangeTracker",
    "native_circulation_fingerprint",
]
