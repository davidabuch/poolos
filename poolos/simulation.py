"""Deterministic, hardware-independent PoolOS simulation runtime."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta
from enum import Enum
from types import MappingProxyType
from typing import Any, Mapping, Optional

from .capabilities import Capability
from .clock import FixedClock
from .commands import Command, CommandAction
from .equipment import Equipment
from .execution import ExecutionEngine
from .kernel import PoolKernel
from .models import BodyState, TemperatureState
from .state import EquipmentState


@dataclass(slots=True)
class SimulationClock(FixedClock):
    """A deterministic clock that can move only forward."""

    def advance(self, duration: timedelta) -> datetime:
        if duration.total_seconds() < 0:
            raise ValueError("simulation duration must not be negative")
        self.current += duration
        return self.current


@dataclass(frozen=True, slots=True)
class WeatherState:
    """Level-one weather inputs used by the thermal model."""

    ambient_temperature: float = 70.0
    solar_intensity: float = 0.0
    wind_factor: float = 1.0

    def __post_init__(self) -> None:
        if not 0.0 <= self.solar_intensity <= 1.0:
            raise ValueError("solar_intensity must be between 0 and 1")
        if self.wind_factor < 0:
            raise ValueError("wind_factor must not be negative")


@dataclass(frozen=True, slots=True)
class BodyThermalModel:
    """Simple deterministic temperature model for one body of water."""

    body_id: str
    heater_gain_per_hour: float = 8.0
    solar_gain_per_hour: float = 1.5
    ambient_exchange_per_hour: float = 0.02
    minimum_temperature: float = 32.0
    maximum_temperature: float = 110.0

    def __post_init__(self) -> None:
        if not self.body_id.strip():
            raise ValueError("body_id must not be empty")
        if self.heater_gain_per_hour < 0 or self.solar_gain_per_hour < 0:
            raise ValueError("thermal gains must not be negative")
        if self.ambient_exchange_per_hour < 0:
            raise ValueError("ambient exchange must not be negative")
        if self.minimum_temperature >= self.maximum_temperature:
            raise ValueError("minimum temperature must be below maximum temperature")


class SimulationEventKind(str, Enum):
    WEATHER = "weather"
    GRID = "grid"
    EQUIPMENT_AVAILABILITY = "equipment_availability"
    COMMAND = "command"


@dataclass(frozen=True, slots=True)
class SimulationEvent:
    """A serializable external event injected into the simulated world."""

    occurs_at: datetime
    kind: SimulationEventKind
    target: Optional[str] = None
    value: Any = None

    def __post_init__(self) -> None:
        if self.occurs_at.tzinfo is None:
            raise ValueError("simulation event time must be timezone-aware")
        if self.kind in {
            SimulationEventKind.EQUIPMENT_AVAILABILITY,
            SimulationEventKind.COMMAND,
        } and not self.target:
            raise ValueError(f"{self.kind.value} events require a target")


@dataclass(frozen=True, slots=True)
class SimulationSnapshot:
    """Immutable point-in-time view used for replay and assertions."""

    recorded_at: datetime
    grid_available: bool
    weather: WeatherState
    bodies: Mapping[str, BodyState]
    equipment: Mapping[str, EquipmentState]

    def __post_init__(self) -> None:
        object.__setattr__(self, "bodies", MappingProxyType(dict(self.bodies)))
        object.__setattr__(self, "equipment", MappingProxyType(dict(self.equipment)))


@dataclass(frozen=True, slots=True)
class SimulationResult:
    started_at: datetime
    ended_at: datetime
    snapshots: tuple[SimulationSnapshot, ...]
    applied_events: tuple[SimulationEvent, ...]

    @property
    def final(self) -> SimulationSnapshot:
        return self.snapshots[-1]


@dataclass(frozen=True, slots=True)
class SimulationScenario:
    """Reusable deterministic scenario definition."""

    name: str
    duration: timedelta
    step: timedelta = timedelta(minutes=1)
    initial_weather: WeatherState = field(default_factory=WeatherState)
    events: tuple[SimulationEvent, ...] = ()

    def __post_init__(self) -> None:
        if not self.name.strip():
            raise ValueError("scenario name must not be empty")
        if self.duration.total_seconds() < 0:
            raise ValueError("scenario duration must not be negative")
        if self.step.total_seconds() <= 0:
            raise ValueError("scenario step must be positive")
        ordered = tuple(sorted(self.events, key=lambda event: event.occurs_at))
        object.__setattr__(self, "events", ordered)


@dataclass(slots=True)
class SimulationExecutor:
    """Execution adapter that applies normalized commands to simulated state."""

    simulation: "Simulation"
    equipment_id: str

    def execute(self, command: Command) -> Mapping[str, Any]:
        return self.simulation._execute_equipment_command(self.equipment_id, command)


@dataclass(slots=True)
class Simulation:
    """Deterministic PoolOS world, command adapter, thermal model, and replay log."""

    kernel: PoolKernel
    clock: SimulationClock
    weather: WeatherState = field(default_factory=WeatherState)
    grid_available: bool = True
    thermal_models: dict[str, BodyThermalModel] = field(default_factory=dict)
    execution: ExecutionEngine = field(init=False)
    _events: list[SimulationEvent] = field(default_factory=list)
    _applied_events: list[SimulationEvent] = field(default_factory=list)
    _snapshots: list[SimulationSnapshot] = field(default_factory=list)
    _baseline_availability: dict[str, bool] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if self.clock.now().tzinfo is None:
            raise ValueError("simulation clock must be timezone-aware")
        self.kernel.clock = self.clock
        self.execution = ExecutionEngine(clock=self.clock)
        self.refresh_equipment()
        self._snapshots.append(self.snapshot())

    @classmethod
    def create(cls, kernel: PoolKernel, *, start_at: datetime) -> "Simulation":
        """Create a simulation and make its clock authoritative for the kernel."""

        return cls(kernel=kernel, clock=SimulationClock(start_at))

    def refresh_equipment(self) -> None:
        """Register executors and initialize missing normalized equipment state."""

        for equipment in self.kernel.equipment.all():
            if equipment.id not in self._baseline_availability:
                existing = self.kernel.state.get_equipment(equipment.id)
                available = equipment.enabled if existing is None else existing.available
                self._baseline_availability[equipment.id] = available
            if self.kernel.state.get_equipment(equipment.id) is None:
                self.kernel.update_equipment_state(
                    equipment.id,
                    EquipmentState(available=equipment.enabled, observed_at=self.clock.now()),
                )
            try:
                self.execution.register_executor(
                    equipment.id, SimulationExecutor(self, equipment.id)
                )
            except ValueError:
                self.execution.register_executor(
                    equipment.id, SimulationExecutor(self, equipment.id), replace=True
                )

    def add_thermal_model(self, model: BodyThermalModel) -> None:
        self.kernel.bodies.get(model.body_id)
        self.thermal_models[model.body_id] = model

    def schedule(self, event: SimulationEvent) -> None:
        if event.occurs_at < self.clock.now():
            raise ValueError("cannot schedule a simulation event in the past")
        self._events.append(event)
        self._events.sort(key=lambda item: item.occurs_at)

    def load_scenario(self, scenario: SimulationScenario) -> None:
        """Replace pending events and weather with a reusable scenario."""

        if scenario.events and scenario.events[0].occurs_at < self.clock.now():
            raise ValueError("scenario contains events before the simulation clock")
        self.weather = scenario.initial_weather
        self._events = list(scenario.events)

    def submit(self, command: Command) -> None:
        self.execution.submit(command)

    def run_scenario(self, scenario: SimulationScenario) -> SimulationResult:
        self.load_scenario(scenario)
        return self.advance(scenario.duration, step=scenario.step)

    def advance(
        self,
        duration: timedelta,
        *,
        step: timedelta = timedelta(minutes=1),
    ) -> SimulationResult:
        """Advance time, apply events, execute commands, and update temperatures."""

        if duration.total_seconds() < 0:
            raise ValueError("simulation duration must not be negative")
        if step.total_seconds() <= 0:
            raise ValueError("simulation step must be positive")

        started_at = self.clock.now()
        end_at = started_at + duration
        self._apply_due_events()
        self.execution.drain()
        self._synchronize_body_flags()

        while self.clock.now() < end_at:
            now = self.clock.now()
            next_at = min(now + step, end_at)
            if self._events and now < self._events[0].occurs_at < next_at:
                next_at = self._events[0].occurs_at
            interval = next_at - now
            self._integrate_thermal_state(interval)
            self.clock.advance(interval)
            self._apply_due_events()
            self.execution.drain()
            self._synchronize_body_flags()
            self._snapshots.append(self.snapshot())

        return SimulationResult(
            started_at=started_at,
            ended_at=self.clock.now(),
            snapshots=tuple(self._snapshots),
            applied_events=tuple(self._applied_events),
        )

    def snapshot(self) -> SimulationSnapshot:
        return SimulationSnapshot(
            recorded_at=self.clock.now(),
            grid_available=self.grid_available,
            weather=self.weather,
            bodies=self.kernel.state.body_snapshot(),
            equipment=self.kernel.state.equipment_snapshot(),
        )

    def timeline(self) -> tuple[SimulationSnapshot, ...]:
        return tuple(self._snapshots)

    def _apply_due_events(self) -> None:
        while self._events and self._events[0].occurs_at <= self.clock.now():
            event = self._events.pop(0)
            self._apply_event(event)
            self._applied_events.append(event)

    def _apply_event(self, event: SimulationEvent) -> None:
        if event.kind is SimulationEventKind.WEATHER:
            if not isinstance(event.value, WeatherState):
                raise TypeError("weather event value must be WeatherState")
            self.weather = event.value
            return
        if event.kind is SimulationEventKind.GRID:
            self._set_grid_available(bool(event.value))
            return
        if event.kind is SimulationEventKind.EQUIPMENT_AVAILABILITY:
            self._set_equipment_available(event.target or "", bool(event.value))
            return
        if event.kind is SimulationEventKind.COMMAND:
            if not isinstance(event.value, Command):
                raise TypeError("command event value must be Command")
            if event.value.target != event.target:
                raise ValueError("command event target must match command target")
            self.submit(event.value)
            return
        raise ValueError(f"unsupported simulation event: {event.kind}")

    def _set_grid_available(self, available: bool) -> None:
        self.grid_available = available
        for equipment in self.kernel.equipment.all():
            prior = self.kernel.state.get_equipment(equipment.id) or EquipmentState()
            restored = self._baseline_availability.get(equipment.id, equipment.enabled)
            is_available = restored if available else False
            self.kernel.update_equipment_state(
                equipment.id,
                EquipmentState(
                    available=is_available,
                    active=prior.active if is_available else False,
                    attributes=prior.attributes,
                    observed_at=self.clock.now(),
                ),
            )

    def _set_equipment_available(self, equipment_id: str, available: bool) -> None:
        self.kernel.equipment.get(equipment_id)
        self._baseline_availability[equipment_id] = available
        prior = self.kernel.state.get_equipment(equipment_id) or EquipmentState()
        effective = available and self.grid_available
        self.kernel.update_equipment_state(
            equipment_id,
            EquipmentState(
                available=effective,
                active=prior.active if effective else False,
                attributes=prior.attributes,
                observed_at=self.clock.now(),
            ),
        )

    def _execute_equipment_command(
        self, equipment_id: str, command: Command
    ) -> Mapping[str, Any]:
        equipment = self.kernel.equipment.get(equipment_id)
        prior = self.kernel.state.get_equipment(equipment_id) or EquipmentState()
        if not prior.available or not self.grid_available:
            raise RuntimeError(f"equipment unavailable: {equipment_id}")

        active = prior.active
        attributes = dict(prior.attributes)
        if command.action in {CommandAction.START, CommandAction.ENABLE}:
            active = True
        elif command.action in {CommandAction.STOP, CommandAction.DISABLE}:
            active = False
        elif command.action is CommandAction.SET:
            if isinstance(command.value, Mapping):
                attributes.update(command.value)
                if "active" in command.value:
                    active = bool(command.value["active"])
            else:
                attributes["value"] = command.value
                if equipment.has_capability(Capability.CIRCULATION) and isinstance(
                    command.value, (int, float)
                ):
                    attributes["speed"] = command.value
                    active = command.value > 0

        if (
            equipment.has_capability(Capability.HEATING)
            and command.action in {CommandAction.START, CommandAction.SET}
            and isinstance(command.value, (int, float))
        ):
            attributes["target_temperature"] = float(command.value)
            if equipment.body is not None:
                self._set_body_target(equipment, float(command.value))

        state = EquipmentState(
            available=True,
            active=active,
            attributes=attributes,
            observed_at=self.clock.now(),
        )
        self.kernel.update_equipment_state(equipment_id, state)
        self._synchronize_body_flags()
        return MappingProxyType(
            {"equipment_id": equipment_id, "active": active, "attributes": attributes}
        )

    def _set_body_target(self, equipment: Equipment, target: float) -> None:
        if equipment.body is None:
            return
        for body in self.kernel.bodies.find_by_type(equipment.body):
            state = self.kernel.state.get_body(body.id)
            if state is None:
                continue
            self.kernel.update_body_state(
                body.id,
                BodyState(
                    body=state.body,
                    temperature=TemperatureState(
                        current=state.temperature.current,
                        target=target,
                        heating=state.temperature.heating,
                    ),
                    circulation_running=state.circulation_running,
                    sanitizer_enabled=state.sanitizer_enabled,
                ),
            )

    def _equipment_for_body(self, body_id: str) -> tuple[tuple[Equipment, EquipmentState], ...]:
        body = self.kernel.bodies.get(body_id)
        items = []
        for equipment in self.kernel.equipment.find_for_body(body.body_type):
            state = self.kernel.state.get_equipment(equipment.id)
            if state is not None:
                items.append((equipment, state))
        return tuple(items)

    def _synchronize_body_flags(self) -> None:
        for body in self.kernel.bodies.all():
            state = self.kernel.state.get_body(body.id)
            if state is None:
                continue
            equipment = self._equipment_for_body(body.id)
            circulation = any(
                item.has_capability(Capability.CIRCULATION) and item_state.active
                for item, item_state in equipment
            )
            heat_active = any(
                item.has_capability(Capability.HEATING) and item_state.active
                for item, item_state in equipment
            )
            sanitizer = any(
                item.has_capability(Capability.SANITIZATION) and item_state.active
                for item, item_state in equipment
            )
            target = state.temperature.target
            heating = heat_active and circulation and (
                target is None or state.temperature.current < target
            )
            updated = BodyState(
                body=state.body,
                temperature=TemperatureState(
                    current=state.temperature.current,
                    target=target,
                    heating=heating,
                ),
                circulation_running=circulation,
                sanitizer_enabled=sanitizer,
            )
            if updated != state:
                self.kernel.update_body_state(body.id, updated)

    def _integrate_thermal_state(self, duration: timedelta) -> None:
        hours = duration.total_seconds() / 3600.0
        if hours <= 0:
            return
        for body_id, model in self.thermal_models.items():
            state = self.kernel.state.get_body(body_id)
            if state is None:
                continue
            equipment = self._equipment_for_body(body_id)
            circulation = any(
                item.has_capability(Capability.CIRCULATION) and item_state.active
                for item, item_state in equipment
            )
            heater = any(
                item.has_capability(Capability.HEATING) and item_state.active
                for item, item_state in equipment
            )
            target = state.temperature.target
            heater_effective = heater and circulation and (
                target is None or state.temperature.current < target
            )
            heater_gain = model.heater_gain_per_hour if heater_effective else 0.0
            solar_gain = (
                model.solar_gain_per_hour * self.weather.solar_intensity
                if circulation
                else 0.0
            )
            ambient_gain = (
                self.weather.ambient_temperature - state.temperature.current
            ) * model.ambient_exchange_per_hour * self.weather.wind_factor
            current = state.temperature.current + (
                heater_gain + solar_gain + ambient_gain
            ) * hours
            if target is not None and heater_effective:
                current = min(current, target)
            current = min(max(current, model.minimum_temperature), model.maximum_temperature)
            updated = BodyState(
                body=state.body,
                temperature=TemperatureState(
                    current=round(current, 6),
                    target=target,
                    heating=heater_effective and (target is None or current < target),
                ),
                circulation_running=state.circulation_running,
                sanitizer_enabled=state.sanitizer_enabled,
            )
            self.kernel.update_body_state(body_id, updated)
