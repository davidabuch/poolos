from dataclasses import dataclass
from datetime import datetime, timezone

import pytest

from poolos.bodies import Body
from poolos.capabilities import Capability
from poolos.clock import FixedClock
from poolos.commands import Command, CommandAction
from poolos.default_policies import (
    CirculationSafetyPolicy,
    HeatingDemandPolicy,
    SanitizerCirculationInterlockPolicy,
    build_default_policy_engine,
)
from poolos.enums import BodyType, CommandPriority, EquipmentType, PolicyPriority
from poolos.equipment import Equipment
from poolos.exceptions import DuplicatePolicyError, UnknownPolicyError
from poolos.kernel import PoolKernel
from poolos.models import BodyState, TemperatureState
from poolos.policies import PolicyContext, PolicyEngine, PolicyOutcome
from poolos.state import EquipmentState


def make_kernel(
    *,
    current=80.0,
    target=85.0,
    heating=False,
    circulation=False,
    sanitizer=False,
):
    kernel = PoolKernel()
    kernel.bodies.register(Body("pool", "Pool", BodyType.POOL))
    kernel.equipment.register(
        Equipment(
            "pump",
            "Filter Pump",
            EquipmentType.PUMP,
            frozenset({Capability.CIRCULATION}),
            BodyType.POOL,
        )
    )
    kernel.equipment.register(
        Equipment(
            "heater",
            "Gas Heater",
            EquipmentType.HEATER,
            frozenset({Capability.HEATING}),
            BodyType.POOL,
        )
    )
    kernel.equipment.register(
        Equipment(
            "chlorinator",
            "Chlorinator",
            EquipmentType.CHLORINATOR,
            frozenset({Capability.SANITIZATION}),
            BodyType.POOL,
        )
    )
    kernel.update_body_state(
        "pool",
        BodyState(
            BodyType.POOL,
            TemperatureState(current=current, target=target, heating=heating),
            circulation_running=circulation,
            sanitizer_enabled=sanitizer,
        ),
    )
    return kernel


def test_heating_policy_starts_heater_below_deadband():
    outcome = HeatingDemandPolicy(deadband=0.5).evaluate(PolicyContext(make_kernel(), datetime.now(timezone.utc)))
    assert len(outcome.commands) == 1
    command = outcome.commands[0]
    assert command.target == "heater"
    assert command.action is CommandAction.START
    assert command.priority is CommandPriority.HIGH
    assert command.requested_by == "comfort.heating_demand"


def test_heating_policy_stops_heater_at_target():
    kernel = make_kernel(current=85.0, target=85.0, heating=True, circulation=True)
    outcome = HeatingDemandPolicy().evaluate(PolicyContext(kernel, datetime.now(timezone.utc)))
    assert outcome.commands[0].action is CommandAction.STOP


def test_heating_policy_holds_inside_deadband():
    kernel = make_kernel(current=84.75, target=85.0, heating=False)
    outcome = HeatingDemandPolicy(deadband=0.5).evaluate(PolicyContext(kernel, datetime.now(timezone.utc)))
    assert outcome.commands == ()


def test_heating_policy_rejects_negative_deadband():
    with pytest.raises(ValueError, match="deadband"):
        HeatingDemandPolicy(deadband=-0.1)


def test_unavailable_heater_is_not_commanded():
    kernel = make_kernel()
    kernel.update_equipment_state("heater", EquipmentState(available=False))
    outcome = HeatingDemandPolicy().evaluate(PolicyContext(kernel, datetime.now(timezone.utc)))
    assert outcome.commands == ()
    assert "no available heating equipment" in outcome.rationale[0]


def test_circulation_safety_starts_pump_while_heating():
    kernel = make_kernel(heating=True, circulation=False)
    outcome = CirculationSafetyPolicy().evaluate(PolicyContext(kernel, datetime.now(timezone.utc)))
    assert outcome.commands[0].target == "pump"
    assert outcome.commands[0].action is CommandAction.START
    assert outcome.commands[0].priority is CommandPriority.CRITICAL


def test_sanitizer_interlock_stops_chlorinator_without_flow():
    kernel = make_kernel(circulation=False, sanitizer=True)
    outcome = SanitizerCirculationInterlockPolicy().evaluate(PolicyContext(kernel, datetime.now(timezone.utc)))
    assert outcome.commands[0].target == "chlorinator"
    assert outcome.commands[0].action is CommandAction.STOP


@dataclass(frozen=True)
class StaticPolicy:
    policy_id: str
    priority: PolicyPriority
    command: Command

    def evaluate(self, context):
        return PolicyOutcome(self.policy_id, self.priority, (self.command,))


def test_policy_engine_resolves_target_conflict_by_policy_priority():
    engine = PolicyEngine()
    low = StaticPolicy(
        "low",
        PolicyPriority.OPTIMIZATION,
        Command("pump", CommandAction.STOP, requested_by="low"),
    )
    high = StaticPolicy(
        "high",
        PolicyPriority.SAFETY,
        Command("pump", CommandAction.START, requested_by="high"),
    )
    engine.register(low)
    engine.register(high)
    result = engine.evaluate(PoolKernel())
    assert result.commands == (high.command,)
    assert result.suppressions[0].command is low.command
    assert result.suppressions[0].winning_policy_id == "high"


def test_same_priority_uses_registration_order():
    first = StaticPolicy(
        "first",
        PolicyPriority.SAFETY,
        Command("pump", CommandAction.START, requested_by="first"),
    )
    second = StaticPolicy(
        "second",
        PolicyPriority.SAFETY,
        Command("pump", CommandAction.STOP, requested_by="second"),
    )
    engine = PolicyEngine()
    engine.register(first)
    engine.register(second)
    assert engine.evaluate(PoolKernel()).commands == (first.command,)


def test_policy_enable_disable_and_lookup_errors():
    engine = PolicyEngine()
    policy = HeatingDemandPolicy()
    engine.register(policy)
    engine.disable(policy.policy_id)
    assert engine.evaluate(make_kernel()).outcomes == ()
    assert not engine.is_enabled(policy.policy_id)
    engine.enable(policy.policy_id)
    assert engine.is_enabled(policy.policy_id)
    with pytest.raises(DuplicatePolicyError):
        engine.register(policy)
    with pytest.raises(UnknownPolicyError):
        engine.disable("missing")


def test_default_policy_builder_is_configurable():
    engine = build_default_policy_engine(
        include_heating=False,
        include_sanitizer_interlock=False,
    )
    assert tuple(policy.policy_id for policy in engine.all()) == (
        "safety.circulation_for_heating",
    )


def test_policy_cannot_emit_multiple_commands_for_same_target():
    @dataclass(frozen=True)
    class BadPolicy:
        policy_id: str = "bad"
        priority: PolicyPriority = PolicyPriority.SAFETY

        def evaluate(self, context):
            return PolicyOutcome(
                self.policy_id,
                self.priority,
                (
                    Command("pump", CommandAction.START),
                    Command("pump", CommandAction.STOP),
                ),
            )

    engine = PolicyEngine()
    engine.register(BadPolicy())
    with pytest.raises(ValueError, match="multiple commands"):
        engine.evaluate(PoolKernel())


def test_policy_engine_uses_kernel_clock_for_evaluation_and_commands():
    instant = datetime(2026, 7, 25, 18, 0, tzinfo=timezone.utc)
    kernel = make_kernel()
    kernel.clock = FixedClock(instant)
    engine = PolicyEngine()
    engine.register(HeatingDemandPolicy())
    result = engine.evaluate(kernel)
    assert result.evaluated_at == instant
    assert result.commands[0].issued_at == instant


def test_shared_equipment_can_serve_a_body_policy():
    kernel = make_kernel(heating=True, circulation=False)
    shared = Equipment(
        "shared_pump",
        "Shared Pump",
        EquipmentType.PUMP,
        frozenset({Capability.CIRCULATION}),
        None,
    )
    kernel.equipment = type(kernel.equipment)()
    kernel.equipment.register(shared)
    outcome = CirculationSafetyPolicy().evaluate(
        PolicyContext(kernel, datetime.now(timezone.utc))
    )
    assert outcome.commands[0].target == "shared_pump"
