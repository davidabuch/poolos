"""System-level read model for Buch IntelliCenter."""

from __future__ import annotations

from typing import TYPE_CHECKING

from homeassistant.const import UnitOfTemperature
from pyintellicenter import BODY_TYPE, CIRCUIT_TYPE

from .body import build_body_state
from .circuit import build_circuit_state
from .models import (
    API_VERSION,
    BodyState,
    BodyType,
    CircuitState,
    IntelliCenterSnapshot,
)

if TYPE_CHECKING:
    from ..coordinator import IntelliCenterCoordinator


class IntelliCenterAPI:
    """Read-only, immutable view of IntelliCenter state."""

    def __init__(self, coordinator: IntelliCenterCoordinator) -> None:
        self._coordinator = coordinator
        self._snapshot = IntelliCenterSnapshot(
            api_version=API_VERSION,
            connected=False,
            panel_name=None,
            software_version=None,
            temperature_unit=UnitOfTemperature.FAHRENHEIT,
            bodies=(),
            circuits=(),
        )

    @property
    def snapshot(self) -> IntelliCenterSnapshot:
        """Return the latest completed system snapshot."""
        return self._snapshot

    @property
    def bodies(self) -> tuple[BodyState, ...]:
        """Return all Pool/Spa body snapshots."""
        return self._snapshot.bodies

    @property
    def circuits(self) -> tuple[CircuitState, ...]:
        """Return all circuit snapshots."""
        return self._snapshot.circuits

    @property
    def pool(self) -> BodyState | None:
        """Return the first normalized pool body, when available."""
        return next(
            (body for body in self._snapshot.bodies if body.body_type is BodyType.POOL),
            None,
        )

    @property
    def spa(self) -> BodyState | None:
        """Return the first normalized spa body, when available."""
        return next(
            (body for body in self._snapshot.bodies if body.body_type is BodyType.SPA),
            None,
        )

    def body(self, body_id: str) -> BodyState | None:
        """Return a body by its IntelliCenter object name."""
        return next(
            (body for body in self._snapshot.bodies if body.id == body_id),
            None,
        )

    def circuit(self, circuit_id: str) -> CircuitState | None:
        """Return a circuit by its IntelliCenter object name."""
        return next(
            (circuit for circuit in self._snapshot.circuits if circuit.id == circuit_id),
            None,
        )

    def refresh(self) -> IntelliCenterSnapshot:
        """Atomically rebuild the read model from the coordinator's live model."""
        system_info = self._coordinator.system_info
        uses_metric = bool(system_info is not None and system_info.uses_metric)
        temperature_unit = (
            UnitOfTemperature.CELSIUS
            if uses_metric
            else UnitOfTemperature.FAHRENHEIT
        )
        minimum_temperature, maximum_temperature = (
            (5.0, 40.0) if uses_metric else (40.0, 104.0)
        )

        bodies: list[BodyState] = []
        for body in self._coordinator.model.get_by_type(BODY_TYPE):
            heater_objnams = self._heater_objnams_for_body(body.objnam)
            if not heater_objnams:
                continue
            bodies.append(
                build_body_state(
                    self._coordinator,
                    body,
                    heater_objnams,
                    minimum_temperature,
                    maximum_temperature,
                    temperature_unit,
                )
            )

        circuits = tuple(
            build_circuit_state(self._coordinator, circuit)
            for circuit in self._coordinator.model.get_by_type(CIRCUIT_TYPE)
        )

        self._snapshot = IntelliCenterSnapshot(
            api_version=API_VERSION,
            connected=self._coordinator.connected,
            panel_name=system_info.prop_name if system_info else None,
            software_version=system_info.sw_version if system_info else None,
            temperature_unit=temperature_unit,
            bodies=tuple(bodies),
            circuits=circuits,
        )
        return self._snapshot

    def _heater_objnams_for_body(self, body_objnam: str) -> tuple[str, ...]:
        """Return heater object names in the same order used by the integration."""
        # Import lazily to avoid an import cycle while __init__.py imports the
        # coordinator during integration startup.
        from .. import heaters_for_body

        return tuple(heaters_for_body(self._coordinator, body_objnam))
