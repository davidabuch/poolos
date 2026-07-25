"""Behavior tests for the completed PoolOS kernel subsystem."""

from datetime import datetime, timezone

import pytest

from poolos import (
    Body,
    BodyState,
    BodyType,
    Capability,
    DuplicateRegistrationError,
    Equipment,
    EquipmentState,
    EquipmentType,
    FixedClock,
    PoolKernel,
    TemperatureState,
    UnknownBodyError,
    UnknownEquipmentError,
)


def test_registry_queries_and_duplicate_protection() -> None:
    kernel = PoolKernel()
    pump = Equipment(
        id="filter-pump",
        name="Filter Pump",
        equipment_type=EquipmentType.PUMP,
        body=BodyType.POOL,
        capabilities=frozenset({Capability.CIRCULATION, Capability.VARIABLE_SPEED}),
    )
    kernel.equipment.register(pump)

    assert kernel.equipment.get("filter-pump") is pump
    assert kernel.equipment.find_by_type(EquipmentType.PUMP) == (pump,)
    assert kernel.equipment.find_by_capability(Capability.CIRCULATION) == (pump,)
    assert kernel.equipment.find_for_body(BodyType.POOL) == (pump,)
    assert kernel.equipment.primary_for(Capability.CIRCULATION) is pump

    with pytest.raises(DuplicateRegistrationError):
        kernel.equipment.register(pump)
    with pytest.raises(UnknownEquipmentError):
        kernel.equipment.get("missing")


def test_body_registry() -> None:
    kernel = PoolKernel()
    spa = Body(id="spa", name="Backyard Spa", body_type=BodyType.SPA)
    kernel.bodies.register(spa)

    assert kernel.bodies.get("spa") is spa
    assert kernel.bodies.find_by_type(BodyType.SPA) == (spa,)

    with pytest.raises(UnknownBodyError):
        kernel.bodies.get("missing")


def test_kernel_owns_state_and_publishes_changes() -> None:
    now = datetime(2026, 7, 25, 20, 0, tzinfo=timezone.utc)
    kernel = PoolKernel(clock=FixedClock(now))
    kernel.bodies.register(Body(id="pool", name="Pool", body_type=BodyType.POOL))
    events = []
    kernel.events.subscribe("state.body.changed", events.append)

    current = BodyState(
        body=BodyType.POOL,
        temperature=TemperatureState(current=86.0, target=90.0, heating=True),
        circulation_running=True,
        sanitizer_enabled=True,
    )

    assert kernel.update_body_state("pool", current) is True
    assert kernel.update_body_state("pool", current) is False
    assert kernel.state.get_body("pool") == current
    assert len(events) == 1
    assert events[0].occurred_at == now
    assert events[0].source == "pool"


def test_equipment_state_snapshot_is_read_only() -> None:
    kernel = PoolKernel()
    kernel.equipment.register(
        Equipment(
            id="heater",
            name="Gas Heater",
            equipment_type=EquipmentType.HEATER,
            capabilities=frozenset({Capability.HEATING.value}),
        )
    )
    state = EquipmentState(active=True, attributes={"output_percent": 100})

    assert kernel.update_equipment_state("heater", state) is True
    assert kernel.state.get_equipment("heater") == state
    assert state.attributes["output_percent"] == 100

    snapshot = kernel.state.equipment_snapshot()
    with pytest.raises(TypeError):
        snapshot["other"] = state
