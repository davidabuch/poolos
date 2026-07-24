"""System-level read model for Buch IntelliCenter."""

from __future__ import annotations

from typing import TYPE_CHECKING

from homeassistant.const import UnitOfTemperature
from pyintellicenter import (
    BODY_TYPE,
    CHEM_TYPE,
    CIRCUIT_TYPE,
    EXTINSTR_TYPE,
    PMPCIRC_TYPE,
    PUMP_TYPE,
    SENSE_TYPE,
    SYSTEM_TYPE,
    CIRCUIT_ATTR,
    PARENT_ATTR,
)

from .body import build_body_state
from .chemistry import build_chemistry_state
from .circuit import build_circuit_state
from .cover import build_cover_state
from .models import (
    API_VERSION,
    BodyState,
    BodyType,
    ChemistryState,
    CoverState,
    CircuitState,
    IntelliCenterSnapshot,
    PumpCircuitState,
    PumpState,
    SystemState,
    TemperatureSensorState,
)
from .panel import build_system_state
from .pump import build_pump_circuit_state, build_pump_state
from .temperature import build_temperature_sensor_state

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
            temperature_sensors=(),
            bodies=(),
            circuits=(),
            pumps=(),
            chemistries=(),
            covers=(),
            system=None,
        )

    @property
    def snapshot(self) -> IntelliCenterSnapshot:
        """Return the latest completed system snapshot."""
        return self._snapshot

    @property
    def temperature_sensors(self) -> tuple[TemperatureSensorState, ...]:
        """Return all physical IntelliCenter temperature-probe snapshots."""
        return self._snapshot.temperature_sensors

    def temperature_sensor(
        self, sensor_id: str
    ) -> TemperatureSensorState | None:
        """Return a physical temperature probe by object name."""
        return next(
            (
                sensor
                for sensor in self._snapshot.temperature_sensors
                if sensor.id == sensor_id
            ),
            None,
        )

    @property
    def bodies(self) -> tuple[BodyState, ...]:
        """Return all Pool/Spa body snapshots."""
        return self._snapshot.bodies

    @property
    def circuits(self) -> tuple[CircuitState, ...]:
        """Return all circuit snapshots."""
        return self._snapshot.circuits

    @property
    def pumps(self) -> tuple[PumpState, ...]:
        """Return all pump snapshots."""
        return self._snapshot.pumps

    @property
    def chemistries(self) -> tuple[ChemistryState, ...]:
        """Return all chemistry-controller snapshots."""
        return self._snapshot.chemistries

    @property
    def covers(self) -> tuple[CoverState, ...]:
        """Return all external-cover snapshots."""
        return self._snapshot.covers

    @property
    def system(self) -> SystemState | None:
        """Return controller-wide state, when the SYSTEM object is available."""
        return self._snapshot.system

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
        return next((body for body in self._snapshot.bodies if body.id == body_id), None)

    def circuit(self, circuit_id: str) -> CircuitState | None:
        """Return a circuit by its IntelliCenter object name."""
        return next(
            (circuit for circuit in self._snapshot.circuits if circuit.id == circuit_id),
            None,
        )

    def pump(self, pump_id: str) -> PumpState | None:
        """Return a pump by its IntelliCenter object name."""
        return next((pump for pump in self._snapshot.pumps if pump.id == pump_id), None)

    def cover(self, cover_id: str) -> CoverState | None:
        """Return a cover by its IntelliCenter object name."""
        return next(
            (cover for cover in self._snapshot.covers if cover.id == cover_id), None
        )

    def chemistry(self, chemistry_id: str) -> ChemistryState | None:
        """Return a chemistry controller by its IntelliCenter object name."""
        return next(
            (
                chemistry
                for chemistry in self._snapshot.chemistries
                if chemistry.id == chemistry_id
            ),
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

        temperature_sensors = tuple(
            build_temperature_sensor_state(probe)
            for probe in self._coordinator.model.get_by_type(SENSE_TYPE)
        )

        bodies: list[BodyState] = []
        for body in self._coordinator.model.get_by_type(BODY_TYPE):
            heater_objnams = self._heater_objnams_for_body(body.objnam)
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
        circuit_names = {circuit.id: circuit.name for circuit in circuits}

        programs_by_pump: dict[str, list[PumpCircuitState]] = {}
        for pump_circuit in self._coordinator.model.get_by_type(PMPCIRC_TYPE):
            pump_id = str(pump_circuit[PARENT_ATTR] or "")
            if not pump_id:
                continue
            circuit_id = str(pump_circuit[CIRCUIT_ATTR] or "")
            program = build_pump_circuit_state(
                pump_circuit,
                circuit_names.get(circuit_id),
            )
            programs_by_pump.setdefault(pump_id, []).append(program)

        pumps = tuple(
            build_pump_state(pump, programs_by_pump.get(pump.objnam, ()))
            for pump in self._coordinator.model.get_by_type(PUMP_TYPE)
        )

        body_names = {
            body.objnam: str(body.sname or body.objnam)
            for body in self._coordinator.model.get_by_type(BODY_TYPE)
        }
        chemistries = tuple(
            build_chemistry_state(chemistry, body_names)
            for chemistry in self._coordinator.model.get_by_type(CHEM_TYPE)
        )

        covers = tuple(
            build_cover_state(cover)
            for cover in self._coordinator.model.get_by_type(EXTINSTR_TYPE)
            if str(cover.subtype or "").strip().upper() == "COVER"
        )

        system_objects = self._coordinator.model.get_by_type(SYSTEM_TYPE)
        system = build_system_state(system_objects[0]) if system_objects else None
        software_version = (
            system.firmware_version
            if system is not None and system.firmware_version is not None
            else system_info.sw_version if system_info else None
        )

        self._snapshot = IntelliCenterSnapshot(
            api_version=API_VERSION,
            connected=self._coordinator.connected,
            panel_name=system_info.prop_name if system_info else None,
            software_version=software_version,
            temperature_unit=temperature_unit,
            temperature_sensors=temperature_sensors,
            bodies=tuple(bodies),
            circuits=circuits,
            pumps=pumps,
            chemistries=chemistries,
            covers=covers,
            system=system,
        )
        return self._snapshot

    def _heater_objnams_for_body(self, body_objnam: str) -> tuple[str, ...]:
        """Return heater object names in the same order used by the integration."""
        # Import lazily to avoid an import cycle while __init__.py imports the
        # coordinator during integration startup.
        from .. import heaters_for_body

        return tuple(heaters_for_body(self._coordinator, body_objnam))
