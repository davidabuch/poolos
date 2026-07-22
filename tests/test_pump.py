from dataclasses import FrozenInstanceError

import pytest


def test_builds_vsf_pump_with_telemetry_limits_and_program(
    api_modules,
    pump_object_factory,
    pump_circuit_object_factory,
    circuit_object_factory,
    coordinator_factory,
):
    circuit = circuit_object_factory("C0001", name="Pool")
    pump = pump_object_factory()
    program = pump_circuit_object_factory()
    coordinator = coordinator_factory([circuit, pump, program])

    api = api_modules.system.IntelliCenterAPI(coordinator)
    snapshot = api.refresh()

    assert len(snapshot.pumps) == 1
    state = snapshot.pumps[0]
    assert state is api.pump("P0001")
    assert state.name == "Main Pump"
    assert state.pump_type is api_modules.models.PumpType.VARIABLE_SPEED_FLOW
    assert state.is_running is True
    assert state.power_watts == 1450.0
    assert state.rpm == 2400.0
    assert state.flow_gpm == 48.0
    assert state.minimum_rpm == 450.0
    assert state.maximum_rpm == 3450.0
    assert state.minimum_flow_gpm == 15.0
    assert state.maximum_flow_gpm == 130.0

    assert len(state.circuits) == 1
    pump_circuit = state.circuits[0]
    assert pump_circuit.id == "PC0001"
    assert pump_circuit.pump_id == "P0001"
    assert pump_circuit.circuit_id == "C0001"
    assert pump_circuit.circuit_name == "Pool"
    assert pump_circuit.mode is api_modules.models.PumpMode.RPM
    assert pump_circuit.rpm_setpoint == 2200.0
    assert pump_circuit.flow_setpoint_gpm == 45.0


def test_normalizes_speed_only_and_flow_only_pumps(
    api_modules,
    pump_object_factory,
    coordinator_factory,
):
    speed = pump_object_factory(
        "P0001",
        subtype="SPEED",
        minimum_flow=0,
        maximum_flow=0,
        gpm=None,
    )
    flow = pump_object_factory(
        "P0002",
        subtype="FLOW",
        minimum_rpm=0,
        maximum_rpm=0,
        rpm=None,
    )

    snapshot = api_modules.system.IntelliCenterAPI(
        coordinator_factory([speed, flow])
    ).refresh()

    assert snapshot.pumps[0].pump_type is api_modules.models.PumpType.VARIABLE_SPEED
    assert snapshot.pumps[0].minimum_flow_gpm is None
    assert snapshot.pumps[0].maximum_flow_gpm is None
    assert snapshot.pumps[1].pump_type is api_modules.models.PumpType.VARIABLE_FLOW
    assert snapshot.pumps[1].minimum_rpm is None
    assert snapshot.pumps[1].maximum_rpm is None


def test_invalid_values_do_not_escape_and_unknown_modes_are_preserved(
    api_modules,
    pump_object_factory,
    pump_circuit_object_factory,
    coordinator_factory,
):
    pump = pump_object_factory(
        subtype="mystery",
        status="OFF",
        power="bad",
        rpm="",
        gpm=None,
        minimum_rpm="bad",
        maximum_rpm=0,
        minimum_flow=-1,
        maximum_flow=None,
    )
    program = pump_circuit_object_factory(
        mode="AUTO",
        rpm_setpoint="bad",
        flow_setpoint=None,
    )

    state = api_modules.system.IntelliCenterAPI(
        coordinator_factory([pump, program])
    ).refresh().pumps[0]

    assert state.pump_type is api_modules.models.PumpType.UNKNOWN
    assert state.is_running is False
    assert state.power_watts is None
    assert state.rpm is None
    assert state.flow_gpm is None
    assert state.minimum_rpm is None
    assert state.maximum_rpm is None
    assert state.minimum_flow_gpm is None
    assert state.maximum_flow_gpm is None
    assert state.circuits[0].mode is api_modules.models.PumpMode.UNKNOWN
    assert state.circuits[0].rpm_setpoint is None
    assert state.circuits[0].flow_setpoint_gpm is None


def test_orphan_programs_are_not_attached_and_snapshot_is_immutable(
    api_modules,
    pump_object_factory,
    pump_circuit_object_factory,
    coordinator_factory,
):
    pump = pump_object_factory()
    orphan = pump_circuit_object_factory(pump_id="P9999")

    snapshot = api_modules.system.IntelliCenterAPI(
        coordinator_factory([pump, orphan])
    ).refresh()

    assert snapshot.pumps[0].circuits == ()
    assert api_modules.system.IntelliCenterAPI(
        coordinator_factory([orphan])
    ).refresh().pumps == ()
    with pytest.raises(FrozenInstanceError):
        snapshot.pumps[0].is_running = False
