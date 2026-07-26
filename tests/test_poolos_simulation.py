from datetime import datetime, timedelta, timezone

import pytest

from poolos.bodies import Body
from poolos.capabilities import Capability
from poolos.commands import Command, CommandAction
from poolos.enums import BodyType, EquipmentType
from poolos.equipment import Equipment
from poolos.kernel import PoolKernel
from poolos.models import BodyState, TemperatureState
from poolos.scenarios import power_outage_scenario, spa_heat_scenario
from poolos.simulation import (
    BodyThermalModel,
    Simulation,
    SimulationClock,
    SimulationEvent,
    SimulationEventKind,
    SimulationScenario,
    WeatherState,
)

START = datetime(2026, 1, 1, 12, 0, tzinfo=timezone.utc)


def build_spa_simulation() -> Simulation:
    kernel = PoolKernel()
    kernel.bodies.register(Body("spa", "Spa", BodyType.SPA))
    kernel.equipment.register(
        Equipment(
            "pump",
            "Spa Pump",
            EquipmentType.PUMP,
            frozenset({Capability.CIRCULATION}),
            body=BodyType.SPA,
        )
    )
    kernel.equipment.register(
        Equipment(
            "heater",
            "Spa Heater",
            EquipmentType.HEATER,
            frozenset({Capability.HEATING}),
            body=BodyType.SPA,
        )
    )
    kernel.update_body_state(
        "spa",
        BodyState(
            BodyType.SPA,
            TemperatureState(current=90.0, target=100.0, heating=False),
            circulation_running=False,
            sanitizer_enabled=False,
        ),
    )
    simulation = Simulation.create(kernel, start_at=START)
    simulation.add_thermal_model(
        BodyThermalModel(
            "spa",
            heater_gain_per_hour=10.0,
            solar_gain_per_hour=0.0,
            ambient_exchange_per_hour=0.0,
        )
    )
    return simulation


def test_simulation_clock_rejects_reverse_time():
    clock = SimulationClock(START)
    with pytest.raises(ValueError):
        clock.advance(timedelta(seconds=-1))


def test_commands_drive_equipment_and_heat_body_deterministically():
    simulation = build_spa_simulation()
    simulation.submit(Command("pump", CommandAction.START, issued_at=START))
    simulation.submit(
        Command("heater", CommandAction.START, value=100.0, issued_at=START)
    )

    result = simulation.advance(timedelta(hours=1), step=timedelta(minutes=10))

    final = result.final
    assert final.bodies["spa"].temperature.current == 100.0
    assert final.bodies["spa"].circulation_running is True
    assert final.equipment["pump"].active is True
    assert len(result.snapshots) == 7


def test_heater_requires_circulation_for_temperature_gain():
    simulation = build_spa_simulation()
    simulation.submit(
        Command("heater", CommandAction.START, value=100.0, issued_at=START)
    )

    result = simulation.advance(timedelta(hours=1))

    assert result.final.bodies["spa"].temperature.current == 90.0
    assert result.final.bodies["spa"].temperature.heating is False


def test_weather_event_changes_thermal_behavior_at_exact_time():
    simulation = build_spa_simulation()
    simulation.thermal_models["spa"] = BodyThermalModel(
        "spa",
        heater_gain_per_hour=0.0,
        solar_gain_per_hour=2.0,
        ambient_exchange_per_hour=0.0,
    )
    simulation.submit(Command("pump", CommandAction.START, issued_at=START))
    simulation.schedule(
        SimulationEvent(
            START + timedelta(minutes=30),
            SimulationEventKind.WEATHER,
            value=WeatherState(ambient_temperature=90.0, solar_intensity=1.0),
        )
    )

    result = simulation.advance(timedelta(hours=1), step=timedelta(hours=1))

    assert result.final.bodies["spa"].temperature.current == 91.0
    assert result.applied_events[0].occurs_at == START + timedelta(minutes=30)


def test_power_outage_stops_equipment_and_restores_availability():
    simulation = build_spa_simulation()
    simulation.submit(Command("pump", CommandAction.START, issued_at=START))
    scenario = power_outage_scenario(
        start_at=START,
        outage_after=timedelta(minutes=15),
        outage_duration=timedelta(minutes=30),
        total_duration=timedelta(hours=1),
    )

    result = simulation.run_scenario(scenario)

    outage_snapshot = next(
        snapshot
        for snapshot in result.snapshots
        if snapshot.recorded_at == START + timedelta(minutes=15)
    )
    assert outage_snapshot.grid_available is False
    assert outage_snapshot.equipment["pump"].active is False
    assert result.final.grid_available is True
    assert result.final.equipment["pump"].available is True
    assert result.final.equipment["pump"].active is False


def test_builtin_spa_scenario_is_replayable():
    first = build_spa_simulation()
    second = build_spa_simulation()
    scenario = spa_heat_scenario(
        start_at=START,
        pump_id="pump",
        heater_id="heater",
        duration=timedelta(hours=1),
    )

    first_result = first.run_scenario(scenario)
    second_result = second.run_scenario(scenario)

    assert first_result.final.bodies == second_result.final.bodies
    assert first_result.final.equipment == second_result.final.equipment


def test_scenario_validates_positive_step():
    with pytest.raises(ValueError):
        SimulationScenario("bad", timedelta(hours=1), step=timedelta(0))
