"""Reusable scenario helpers for the PoolOS simulation engine."""

from __future__ import annotations

from datetime import datetime, timedelta

from .commands import Command, CommandAction
from .simulation import (
    SimulationEvent,
    SimulationEventKind,
    SimulationScenario,
    WeatherState,
)


def spa_heat_scenario(
    *,
    start_at: datetime,
    pump_id: str,
    heater_id: str,
    target_temperature: float = 100.0,
    duration: timedelta = timedelta(hours=3),
) -> SimulationScenario:
    """Return a sunny, deterministic spa-heating scenario."""

    return SimulationScenario(
        name="spa_heat",
        duration=duration,
        initial_weather=WeatherState(ambient_temperature=72.0, solar_intensity=0.4),
        events=(
            SimulationEvent(
                start_at,
                SimulationEventKind.COMMAND,
                pump_id,
                Command(pump_id, CommandAction.START, issued_at=start_at),
            ),
            SimulationEvent(
                start_at,
                SimulationEventKind.COMMAND,
                heater_id,
                Command(
                    heater_id,
                    CommandAction.START,
                    value=target_temperature,
                    issued_at=start_at,
                ),
            ),
        ),
    )


def power_outage_scenario(
    *,
    start_at: datetime,
    outage_after: timedelta = timedelta(minutes=30),
    outage_duration: timedelta = timedelta(hours=1),
    total_duration: timedelta = timedelta(hours=2),
) -> SimulationScenario:
    """Return a scenario that drops and restores grid power."""

    outage_at = start_at + outage_after
    restore_at = outage_at + outage_duration
    return SimulationScenario(
        name="power_outage",
        duration=total_duration,
        events=(
            SimulationEvent(outage_at, SimulationEventKind.GRID, value=False),
            SimulationEvent(restore_at, SimulationEventKind.GRID, value=True),
        ),
    )
