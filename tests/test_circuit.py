from dataclasses import FrozenInstanceError

import pytest


def test_circuit_state_normalizes_panel_attributes(
    api_modules,
    circuit_object_factory,
    coordinator_factory,
):
    raw = circuit_object_factory(
        objnam="C0042",
        name="Pool Waterfall",
        subtype="FEATURE",
        status="ON",
        use="FEATURE",
        feature="1",
        freeze="ON",
        egg_timer="45",
    )
    coordinator = coordinator_factory([raw])

    circuit = api_modules.circuit.build_circuit_state(coordinator, raw)

    assert circuit.id == "C0042"
    assert circuit.name == "Pool Waterfall"
    assert circuit.is_on is True
    assert circuit.subtype == "FEATURE"
    assert circuit.use == "FEATURE"
    assert circuit.feature is True
    assert circuit.freeze_protected is True
    assert circuit.egg_timer_minutes == 45


def test_circuit_state_handles_off_and_malformed_optional_values(
    api_modules,
    circuit_object_factory,
    coordinator_factory,
):
    raw = circuit_object_factory(
        status="OFF",
        use="",
        feature="0",
        freeze=None,
        egg_timer="not-a-number",
    )
    coordinator = coordinator_factory([raw])

    circuit = api_modules.circuit.build_circuit_state(coordinator, raw)

    assert circuit.is_on is False
    assert circuit.use is None
    assert circuit.feature is False
    assert circuit.freeze_protected is False
    assert circuit.egg_timer_minutes is None


def test_circuit_snapshot_lookup_and_immutability(
    api_modules,
    circuit_object_factory,
    coordinator_factory,
):
    first = circuit_object_factory("C0001", name="Waterfall")
    second = circuit_object_factory("C0002", name="Bubbler", status="OFF")
    coordinator = coordinator_factory([first, second])

    api = api_modules.system.IntelliCenterAPI(coordinator)
    snapshot = api.refresh()

    assert len(api.circuits) == 2
    assert api.circuit("C0002") is api.circuits[1]
    assert api.circuit("missing") is None
    assert snapshot.circuits == api.circuits

    with pytest.raises(FrozenInstanceError):
        api.circuits[0].is_on = False
