"""Opinionated, configurable default policies shipped with PoolOS."""

from __future__ import annotations

from dataclasses import dataclass

from .capabilities import Capability
from .commands import Command, CommandAction
from .enums import CommandPriority, PolicyPriority
from .policies import PolicyContext, PolicyEngine, PolicyOutcome


def _equipment_available(context: PolicyContext, equipment_id: str) -> bool:
    state = context.kernel.state.get_equipment(equipment_id)
    return state is None or state.available


@dataclass(frozen=True, slots=True)
class CirculationSafetyPolicy:
    """Require circulation whenever a body reports active heating."""

    policy_id: str = "safety.circulation_for_heating"
    priority: PolicyPriority = PolicyPriority.SAFETY

    def evaluate(self, context: PolicyContext) -> PolicyOutcome:
        commands: list[Command] = []
        rationale: list[str] = []
        for body in context.kernel.bodies.enabled_bodies():
            state = context.kernel.state.get_body(body.id)
            if state is None or not state.temperature.heating or state.circulation_running:
                continue
            pump = context.kernel.equipment.primary_for(
                Capability.CIRCULATION,
                body=body.body_type,
            )
            if pump is None or not _equipment_available(context, pump.id):
                rationale.append(
                    f"{body.id}: heating requires circulation, but no available pump exists"
                )
                continue
            commands.append(
                Command(
                    target=pump.id,
                    action=CommandAction.START,
                    priority=CommandPriority.CRITICAL,
                    requested_by=self.policy_id,
                    metadata={"body_id": body.id, "reason": "heating_requires_circulation"},
                    issued_at=context.evaluated_at,
                )
            )
            rationale.append(f"{body.id}: start circulation before or during heating")
        return PolicyOutcome(self.policy_id, self.priority, tuple(commands), tuple(rationale))


@dataclass(frozen=True, slots=True)
class HeatingDemandPolicy:
    """Start or stop available heating equipment using a configurable deadband."""

    deadband: float = 0.5
    policy_id: str = "comfort.heating_demand"
    priority: PolicyPriority = PolicyPriority.OPTIMIZATION

    def __post_init__(self) -> None:
        if self.deadband < 0:
            raise ValueError("deadband must be zero or greater")

    def evaluate(self, context: PolicyContext) -> PolicyOutcome:
        commands: list[Command] = []
        rationale: list[str] = []
        for body in context.kernel.bodies.enabled_bodies():
            state = context.kernel.state.get_body(body.id)
            if state is None or state.temperature.target is None:
                continue
            heater = context.kernel.equipment.primary_for(
                Capability.HEATING,
                body=body.body_type,
            )
            if heater is None or not _equipment_available(context, heater.id):
                rationale.append(f"{body.id}: no available heating equipment")
                continue

            current = state.temperature.current
            target = state.temperature.target
            if current < target - self.deadband and not state.temperature.heating:
                commands.append(
                    Command(
                        target=heater.id,
                        action=CommandAction.START,
                        priority=CommandPriority.HIGH,
                        requested_by=self.policy_id,
                        metadata={"body_id": body.id, "target_temperature": target},
                        issued_at=context.evaluated_at,
                    )
                )
                rationale.append(f"{body.id}: temperature is below target deadband")
            elif current >= target and state.temperature.heating:
                commands.append(
                    Command(
                        target=heater.id,
                        action=CommandAction.STOP,
                        priority=CommandPriority.HIGH,
                        requested_by=self.policy_id,
                        metadata={"body_id": body.id, "target_temperature": target},
                        issued_at=context.evaluated_at,
                    )
                )
                rationale.append(f"{body.id}: target temperature reached")

        return PolicyOutcome(self.policy_id, self.priority, tuple(commands), tuple(rationale))


@dataclass(frozen=True, slots=True)
class SanitizerCirculationInterlockPolicy:
    """Stop sanitization when a body has no active circulation."""

    policy_id: str = "safety.sanitizer_requires_circulation"
    priority: PolicyPriority = PolicyPriority.SAFETY

    def evaluate(self, context: PolicyContext) -> PolicyOutcome:
        commands: list[Command] = []
        rationale: list[str] = []
        for body in context.kernel.bodies.enabled_bodies():
            state = context.kernel.state.get_body(body.id)
            if state is None or not state.sanitizer_enabled or state.circulation_running:
                continue
            sanitizer = context.kernel.equipment.primary_for(
                Capability.SANITIZATION,
                body=body.body_type,
            )
            if sanitizer is None or not _equipment_available(context, sanitizer.id):
                rationale.append(f"{body.id}: sanitizer interlock cannot find available equipment")
                continue
            commands.append(
                Command(
                    target=sanitizer.id,
                    action=CommandAction.STOP,
                    priority=CommandPriority.CRITICAL,
                    requested_by=self.policy_id,
                    metadata={"body_id": body.id, "reason": "circulation_not_running"},
                    issued_at=context.evaluated_at,
                )
            )
            rationale.append(f"{body.id}: stop sanitizer because circulation is off")
        return PolicyOutcome(self.policy_id, self.priority, tuple(commands), tuple(rationale))


def build_default_policy_engine(
    *,
    heating_deadband: float = 0.5,
    include_heating: bool = True,
    include_circulation_safety: bool = True,
    include_sanitizer_interlock: bool = True,
) -> PolicyEngine:
    """Create the opinionated default policy set with explicit opt-outs."""

    engine = PolicyEngine()
    if include_circulation_safety:
        engine.register(CirculationSafetyPolicy())
    if include_sanitizer_interlock:
        engine.register(SanitizerCirculationInterlockPolicy())
    if include_heating:
        engine.register(HeatingDemandPolicy(deadband=heating_deadband))
    return engine
