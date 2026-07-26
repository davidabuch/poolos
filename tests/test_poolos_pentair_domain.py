from __future__ import annotations

import pytest

from poolos.capabilities import Capability
from poolos.vendors.pentair import (
    PentairBody,
    PentairBodyKind,
    PentairCircuit,
    PentairCircuitFunction,
    PentairCircuitKind,
    PentairControllerFamily,
    PentairHeatMode,
    PentairHeatSelection,
    PentairHeatSource,
    PentairHeater,
    PentairObjectAddress,
    PentairObjectKind,
    PentairPump,
    PentairPumpControlMode,
    PentairPumpProgram,
    PentairPumpSetpointKind,
    PentairSharedEquipment,
    PentairSystem,
    PentairTemperatureUnit,
    PentairValve,
    PentairValveRole,
)


def address(object_id: str, kind: PentairObjectKind) -> PentairObjectAddress:
    return PentairObjectAddress(object_id=object_id, kind=kind)


def test_variable_speed_pump_advertises_rpm_capabilities() -> None:
    pump = PentairPump(
        address("pump.main", PentairObjectKind.PUMP),
        "Main Pump",
        PentairPumpControlMode.VARIABLE_SPEED,
        minimum_rpm=450,
        maximum_rpm=3450,
    )
    assert Capability.RPM_CONTROL in pump.capabilities
    assert Capability.RPM_SENSING in pump.capabilities
    assert Capability.FLOW_CONTROL not in pump.capabilities


def test_programmed_rpm_is_configuration_not_observed_state() -> None:
    program = PentairPumpProgram(
        circuit_id="circuit.pool",
        setpoint_kind=PentairPumpSetpointKind.RPM,
        setpoint=1800,
    )
    assert program.setpoint == 1800
    assert not hasattr(program, "actual_rpm")


def test_circuit_group_requires_members() -> None:
    with pytest.raises(ValueError, match="at least one member"):
        PentairCircuit(
            address("group.lights", PentairObjectKind.CIRCUIT_GROUP),
            "All Lights",
            PentairCircuitKind.GROUP,
        )


def test_off_heat_selection_rejects_source() -> None:
    with pytest.raises(ValueError, match="cannot specify"):
        PentairHeatSelection(PentairHeatMode.OFF, PentairHeatSource.GAS)


def test_shared_pool_spa_system_validates_cross_references() -> None:
    pool_circuit = PentairCircuit(
        address("circuit.pool", PentairObjectKind.CIRCUIT),
        "Pool",
        PentairCircuitKind.BODY,
        PentairCircuitFunction.POOL,
    )
    spa_circuit = PentairCircuit(
        address("circuit.spa", PentairObjectKind.CIRCUIT),
        "Spa",
        PentairCircuitKind.BODY,
        PentairCircuitFunction.SPA,
    )
    heater = PentairHeater(
        address("heater.gas", PentairObjectKind.HEATER),
        "Gas Heater",
        PentairHeatSource.GAS,
        frozenset({"body.pool", "body.spa"}),
    )
    pool = PentairBody(
        address("body.pool", PentairObjectKind.BODY),
        "Pool",
        PentairBodyKind.POOL,
        "circuit.pool",
        PentairTemperatureUnit.FAHRENHEIT,
        40,
        104,
        ("heater.gas",),
    )
    spa = PentairBody(
        address("body.spa", PentairObjectKind.BODY),
        "Spa",
        PentairBodyKind.SPA,
        "circuit.spa",
        PentairTemperatureUnit.FAHRENHEIT,
        40,
        104,
        ("heater.gas",),
        PentairHeatSelection(PentairHeatMode.HEATER, PentairHeatSource.GAS, "heater.gas"),
    )
    pump = PentairPump(
        address("pump.main", PentairObjectKind.PUMP),
        "Main VS Pump",
        PentairPumpControlMode.VARIABLE_SPEED,
        programs=(
            PentairPumpProgram("circuit.pool", PentairPumpSetpointKind.RPM, 1800),
            PentairPumpProgram("circuit.spa", PentairPumpSetpointKind.RPM, 3000),
        ),
    )
    intake = PentairValve(
        address("valve.intake", PentairObjectKind.VALVE),
        "Intake",
        PentairValveRole.INTAKE,
    )
    returns = PentairValve(
        address("valve.return", PentairObjectKind.VALVE),
        "Return",
        PentairValveRole.RETURN,
    )
    shared = PentairSharedEquipment(
        "shared.main",
        frozenset({"body.pool", "body.spa"}),
        frozenset({"pump.main"}),
        frozenset({"heater.gas"}),
        "valve.intake",
        "valve.return",
    )
    system = PentairSystem(
        PentairControllerFamily.INTELLICENTER,
        "panel.main",
        "Backyard IntelliCenter",
        bodies=(pool, spa),
        circuits=(pool_circuit, spa_circuit),
        pumps=(pump,),
        heaters=(heater,),
        valves=(intake, returns),
        shared_equipment=(shared,),
    )
    assert system.object_by_id("pump.main") is pump
    assert system.shared_equipment[0].body_ids == frozenset({"body.pool", "body.spa"})


def test_unknown_cross_reference_is_rejected() -> None:
    body = PentairBody(
        address("body.pool", PentairObjectKind.BODY),
        "Pool",
        PentairBodyKind.POOL,
        "circuit.missing",
        PentairTemperatureUnit.FAHRENHEIT,
        40,
        104,
    )
    with pytest.raises(ValueError, match="unknown circuit"):
        PentairSystem(
            PentairControllerFamily.INTELLICENTER,
            "panel.main",
            "Panel",
            bodies=(body,),
        )
