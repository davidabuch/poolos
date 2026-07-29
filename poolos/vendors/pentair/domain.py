"""Transport-independent Pentair domain model.

The objects in this module describe what Pentair configuration and state mean to
PoolOS. They deliberately contain no Home Assistant entity IDs, sockets, serial
ports, protocol bytes, or command I/O.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import FrozenSet, Mapping, Optional

from ...capabilities import Capability
from ..base import VendorIdentity
from .constants import (
    PentairBodyKind,
    PentairCircuitFunction,
    PentairCircuitKind,
    PentairControllerFamily,
    PentairFreezeProtection,
    PentairHeatMode,
    PentairHeatSource,
    PentairObjectKind,
    PentairPumpControlMode,
    PentairPumpSetpointKind,
    PentairTemperatureUnit,
    PentairValveRole,
)

PENTAIR = VendorIdentity(vendor_id="pentair", name="Pentair")


def _required(value: str, label: str) -> None:
    if not value.strip():
        raise ValueError(f"{label} must not be empty")


@dataclass(frozen=True, slots=True)
class PentairObjectAddress:
    """Logical identity of a Pentair object independent of transport addressing."""

    object_id: str
    kind: PentairObjectKind
    numeric_id: Optional[int] = None
    panel_name: Optional[str] = None

    def __post_init__(self) -> None:
        _required(self.object_id, "object_id")
        if self.numeric_id is not None and self.numeric_id < 0:
            raise ValueError("numeric_id must not be negative")


@dataclass(frozen=True, slots=True)
class PentairCircuit:
    address: PentairObjectAddress
    name: str
    circuit_kind: PentairCircuitKind
    function: PentairCircuitFunction = PentairCircuitFunction.GENERIC
    freeze_protection: PentairFreezeProtection = PentairFreezeProtection.UNKNOWN
    body_id: Optional[str] = None
    member_circuit_ids: tuple[str, ...] = ()
    attributes: Mapping[str, object] = field(default_factory=dict)

    def __post_init__(self) -> None:
        _required(self.name, "circuit name")
        if self.address.kind not in {
            PentairObjectKind.CIRCUIT,
            PentairObjectKind.CIRCUIT_GROUP,
            PentairObjectKind.FEATURE,
            PentairObjectKind.LIGHT,
        }:
            raise ValueError("circuit address has incompatible object kind")
        if self.circuit_kind is PentairCircuitKind.GROUP and not self.member_circuit_ids:
            raise ValueError("circuit groups must contain at least one member")
        if self.circuit_kind is not PentairCircuitKind.GROUP and self.member_circuit_ids:
            raise ValueError("only circuit groups may declare member circuits")
        if len(self.member_circuit_ids) != len(set(self.member_circuit_ids)):
            raise ValueError("member circuit ids must be unique")
        object.__setattr__(self, "attributes", dict(self.attributes))


@dataclass(frozen=True, slots=True)
class PentairHeatSelection:
    mode: PentairHeatMode
    source: Optional[PentairHeatSource] = None
    heater_id: Optional[str] = None

    def __post_init__(self) -> None:
        if self.mode is PentairHeatMode.OFF and (self.source or self.heater_id):
            raise ValueError("off heat selection cannot specify a source or heater")


@dataclass(frozen=True, slots=True)
class PentairBody:
    address: PentairObjectAddress
    name: str
    body_kind: PentairBodyKind
    circuit_id: str
    temperature_unit: PentairTemperatureUnit
    minimum_temperature: float
    maximum_temperature: float
    available_heater_ids: tuple[str, ...] = ()
    heat_selection: PentairHeatSelection = field(
        default_factory=lambda: PentairHeatSelection(PentairHeatMode.OFF)
    )
    shared_equipment_group: Optional[str] = None

    def __post_init__(self) -> None:
        _required(self.name, "body name")
        _required(self.circuit_id, "body circuit_id")
        if self.address.kind is not PentairObjectKind.BODY:
            raise ValueError("body address must have BODY object kind")
        if self.minimum_temperature >= self.maximum_temperature:
            raise ValueError("minimum temperature must be below maximum temperature")
        if len(self.available_heater_ids) != len(set(self.available_heater_ids)):
            raise ValueError("available heater ids must be unique")
        selected = self.heat_selection.heater_id
        if selected is not None and selected not in self.available_heater_ids:
            raise ValueError("selected heater must be available to the body")


@dataclass(frozen=True, slots=True)
class PentairPumpProgram:
    """A Pentair circuit-to-pump setpoint association.

    Programs are configuration facts. PoolOS must still use observed actual RPM as
    ground truth rather than treating a configured program as measured pump state.
    """

    circuit_id: str
    setpoint_kind: PentairPumpSetpointKind
    setpoint: float

    def __post_init__(self) -> None:
        _required(self.circuit_id, "pump program circuit_id")
        if self.setpoint <= 0:
            raise ValueError("pump program setpoint must be positive")
        if self.setpoint_kind is PentairPumpSetpointKind.RPM and not float(self.setpoint).is_integer():
            raise ValueError("RPM setpoints must be whole numbers")


@dataclass(frozen=True, slots=True)
class PentairPump:
    address: PentairObjectAddress
    name: str
    control_mode: PentairPumpControlMode
    minimum_rpm: Optional[int] = None
    maximum_rpm: Optional[int] = None
    minimum_gpm: Optional[float] = None
    maximum_gpm: Optional[float] = None
    programs: tuple[PentairPumpProgram, ...] = ()

    def __post_init__(self) -> None:
        _required(self.name, "pump name")
        if self.address.kind is not PentairObjectKind.PUMP:
            raise ValueError("pump address must have PUMP object kind")
        for low, high, label in (
            (self.minimum_rpm, self.maximum_rpm, "RPM"),
            (self.minimum_gpm, self.maximum_gpm, "GPM"),
        ):
            if low is not None and low < 0:
                raise ValueError(f"minimum {label} must not be negative")
            if high is not None and high < 0:
                raise ValueError(f"maximum {label} must not be negative")
            if low is not None and high is not None and low > high:
                raise ValueError(f"minimum {label} must not exceed maximum {label}")
        circuits = [program.circuit_id for program in self.programs]
        if len(circuits) != len(set(circuits)):
            raise ValueError("a pump may have only one program per circuit")

    @property
    def capabilities(self) -> FrozenSet[Capability]:
        capabilities = {
            Capability.CIRCULATION,
            Capability.START_STOP,
            Capability.FAULT_REPORTING,
        }
        if self.control_mode in {
            PentairPumpControlMode.VARIABLE_SPEED,
            PentairPumpControlMode.VARIABLE_SPEED_FLOW,
        }:
            capabilities.update(
                {Capability.VARIABLE_SPEED, Capability.RPM_CONTROL, Capability.RPM_SENSING}
            )
        if self.control_mode in {
            PentairPumpControlMode.VARIABLE_FLOW,
            PentairPumpControlMode.VARIABLE_SPEED_FLOW,
        }:
            capabilities.update({Capability.FLOW_CONTROL, Capability.FLOW_SENSING})
        return frozenset(capabilities)


@dataclass(frozen=True, slots=True)
class PentairHeater:
    address: PentairObjectAddress
    name: str
    source: PentairHeatSource
    body_ids: FrozenSet[str] = field(default_factory=frozenset)
    supports_cooling: bool = False

    def __post_init__(self) -> None:
        _required(self.name, "heater name")
        if self.address.kind is not PentairObjectKind.HEATER:
            raise ValueError("heater address must have HEATER object kind")

    @property
    def capabilities(self) -> FrozenSet[Capability]:
        values = {
            Capability.HEATING,
            Capability.TARGET_TEMPERATURE_CONTROL,
            Capability.FAULT_REPORTING,
        }
        if self.supports_cooling:
            values.add(Capability.COOLING)
        return frozenset(values)


@dataclass(frozen=True, slots=True)
class PentairValve:
    address: PentairObjectAddress
    name: str
    role: PentairValveRole
    assigned_circuit_id: Optional[str] = None
    position_feedback_available: bool = False

    def __post_init__(self) -> None:
        _required(self.name, "valve name")
        if self.address.kind is not PentairObjectKind.VALVE:
            raise ValueError("valve address must have VALVE object kind")

    @property
    def capabilities(self) -> FrozenSet[Capability]:
        # Standard IntelliCenter actuator assignments usually expose logical A/B
        # routing rather than continuous position feedback.
        return frozenset({Capability.VALVE_POSITIONING, Capability.FAULT_REPORTING})


@dataclass(frozen=True, slots=True)
class PentairSharedEquipment:
    """Declares bodies that share circulation and heating equipment."""

    group_id: str
    body_ids: FrozenSet[str]
    pump_ids: FrozenSet[str]
    heater_ids: FrozenSet[str] = field(default_factory=frozenset)
    intake_valve_id: Optional[str] = None
    return_valve_id: Optional[str] = None

    def __post_init__(self) -> None:
        _required(self.group_id, "shared equipment group_id")
        if len(self.body_ids) < 2:
            raise ValueError("shared equipment requires at least two bodies")
        if not self.pump_ids:
            raise ValueError("shared equipment requires at least one pump")


@dataclass(frozen=True, slots=True)
class PentairSystem:
    controller_family: PentairControllerFamily
    panel_id: str
    panel_name: str
    bodies: tuple[PentairBody, ...] = ()
    circuits: tuple[PentairCircuit, ...] = ()
    pumps: tuple[PentairPump, ...] = ()
    heaters: tuple[PentairHeater, ...] = ()
    valves: tuple[PentairValve, ...] = ()
    shared_equipment: tuple[PentairSharedEquipment, ...] = ()
    software_version: Optional[str] = None

    def __post_init__(self) -> None:
        _required(self.panel_id, "panel_id")
        _required(self.panel_name, "panel_name")
        collections = {
            "body": [item.address.object_id for item in self.bodies],
            "circuit": [item.address.object_id for item in self.circuits],
            "pump": [item.address.object_id for item in self.pumps],
            "heater": [item.address.object_id for item in self.heaters],
            "valve": [item.address.object_id for item in self.valves],
        }
        all_ids: set[str] = set()
        for label, ids in collections.items():
            if len(ids) != len(set(ids)):
                raise ValueError(f"{label} object ids must be unique")
            overlap = all_ids.intersection(ids)
            if overlap:
                raise ValueError(f"Pentair object ids must be globally unique: {sorted(overlap)}")
            all_ids.update(ids)
        circuit_ids = {item.address.object_id for item in self.circuits}
        body_ids = {item.address.object_id for item in self.bodies}
        pump_ids = {item.address.object_id for item in self.pumps}
        heater_ids = {item.address.object_id for item in self.heaters}
        valve_ids = {item.address.object_id for item in self.valves}
        for body in self.bodies:
            if body.circuit_id not in circuit_ids:
                raise ValueError(f"body {body.name} references unknown circuit {body.circuit_id}")
            unknown = set(body.available_heater_ids) - heater_ids
            if unknown:
                raise ValueError(f"body {body.name} references unknown heaters {sorted(unknown)}")
        for pump in self.pumps:
            unknown = {p.circuit_id for p in pump.programs} - circuit_ids
            if unknown:
                raise ValueError(f"pump {pump.name} references unknown circuits {sorted(unknown)}")
        for group in self.shared_equipment:
            if not group.body_ids <= body_ids:
                raise ValueError("shared equipment references unknown bodies")
            if not group.pump_ids <= pump_ids:
                raise ValueError("shared equipment references unknown pumps")
            if not group.heater_ids <= heater_ids:
                raise ValueError("shared equipment references unknown heaters")
            if group.intake_valve_id and group.intake_valve_id not in valve_ids:
                raise ValueError("shared equipment references unknown intake valve")
            if group.return_valve_id and group.return_valve_id not in valve_ids:
                raise ValueError("shared equipment references unknown return valve")

    def object_by_id(self, object_id: str) -> object:
        for collection in (self.bodies, self.circuits, self.pumps, self.heaters, self.valves):
            for item in collection:
                if item.address.object_id == object_id:
                    return item
        raise KeyError(object_id)
