from dataclasses import dataclass
from datetime import datetime, timezone

import pytest

from poolos.clock import FixedClock
from poolos.commands import Command, CommandAction
from poolos.constraints import (
    ConstraintContext,
    ConstraintDecision,
    ConstraintDisposition,
    ConstraintEngine,
)
from poolos.kernel import PoolKernel


@dataclass
class AllowConstraint:
    constraint_id: str = "allow"
    priority: int = 0

    def evaluate(self, command, context):
        return ConstraintDecision.allow(self.constraint_id, command, context.evaluated_at)


@dataclass
class CapRpmConstraint:
    maximum: int = 1800
    constraint_id: str = "grid_outage_rpm_cap"
    priority: int = 100

    def evaluate(self, command, context):
        if command.target == "pump.main.rpm" and command.value > self.maximum:
            replacement = ConstraintEngine.replace_command(
                command,
                value=self.maximum,
                metadata={**command.metadata, "constrained_by": self.constraint_id},
            )
            return ConstraintDecision.modify(
                self.constraint_id,
                command,
                replacement,
                context.evaluated_at,
                "pump speed capped during grid outage",
                details={"requested": command.value, "maximum": self.maximum},
            )
        return ConstraintDecision.allow(self.constraint_id, command, context.evaluated_at)


@dataclass
class DenyHeaterConstraint:
    constraint_id: str = "heater_flow_interlock"
    priority: int = 50

    def evaluate(self, command, context):
        if command.target == "heater.main" and command.action is CommandAction.START:
            return ConstraintDecision.deny(
                self.constraint_id,
                command,
                context.evaluated_at,
                "verified water flow is required",
            )
        return ConstraintDecision.allow(self.constraint_id, command, context.evaluated_at)


@dataclass
class DeferConstraint:
    constraint_id: str = "pump_prime_wait"
    priority: int = 10

    def evaluate(self, command, context):
        return ConstraintDecision.defer(
            self.constraint_id,
            command,
            context.evaluated_at,
            "pump priming has not completed",
        )


@dataclass
class EscalateConstraint:
    constraint_id: str = "pump_fault"
    priority: int = 20

    def evaluate(self, command, context):
        return ConstraintDecision.escalate(
            self.constraint_id,
            command,
            context.evaluated_at,
            "pump fault requires operator attention",
            details={"notify": True},
        )


def make_kernel():
    return PoolKernel(clock=FixedClock(datetime(2026, 7, 26, 12, 0, tzinfo=timezone.utc)))


def test_empty_engine_allows_command():
    kernel = make_kernel()
    command = Command(target="pump.main", action=CommandAction.START)

    result = ConstraintEngine().evaluate(command, kernel)

    assert result.disposition is ConstraintDisposition.ALLOW
    assert result.effective_command is command
    assert result.executable
    assert result.decisions == ()


def test_modify_preserves_logical_command_identity_and_continues_chain():
    kernel = make_kernel()
    engine = ConstraintEngine()
    engine.register(AllowConstraint(constraint_id="later", priority=0))
    engine.register(CapRpmConstraint())
    command = Command(target="pump.main.rpm", action=CommandAction.SET, value=3200)

    result = engine.evaluate(command, kernel)

    assert result.disposition is ConstraintDisposition.MODIFY
    assert result.executable
    assert result.effective_command.value == 1800
    assert result.effective_command.command_id == command.command_id
    assert [item.constraint_id for item in result.decisions] == [
        "grid_outage_rpm_cap",
        "later",
    ]
    assert result.decisions[1].command.value == 1800


def test_deny_is_terminal_and_audited():
    kernel = make_kernel()
    engine = ConstraintEngine(events=kernel.events)
    engine.register(DenyHeaterConstraint())
    engine.register(AllowConstraint(constraint_id="never_reached", priority=0))
    observed = []
    kernel.events.subscribe("constraint.command.denied", observed.append)
    command = Command(target="heater.main", action=CommandAction.START)

    result = engine.evaluate(command, kernel)

    assert result.disposition is ConstraintDisposition.DENY
    assert not result.executable
    assert result.effective_command is None
    assert [item.constraint_id for item in result.decisions] == ["heater_flow_interlock"]
    assert observed[0].payload["reason"] == "verified water flow is required"
    assert engine.audit_log() == (result,)


@pytest.mark.parametrize(
    ("constraint", "expected"),
    [
        (DeferConstraint(), ConstraintDisposition.DEFER),
        (EscalateConstraint(), ConstraintDisposition.ESCALATE),
    ],
)
def test_non_executable_terminal_dispositions(constraint, expected):
    kernel = make_kernel()
    engine = ConstraintEngine()
    engine.register(constraint)

    result = engine.evaluate(
        Command(target="pump.main", action=CommandAction.START), kernel
    )

    assert result.disposition is expected
    assert not result.executable


def test_registration_is_deterministic_by_priority_then_insertion_order():
    engine = ConstraintEngine()
    engine.register(AllowConstraint("second", priority=10))
    engine.register(AllowConstraint("first", priority=20))
    engine.register(AllowConstraint("third", priority=10))

    assert [item.constraint_id for item in engine.constraints()] == [
        "first",
        "second",
        "third",
    ]


def test_duplicate_registration_and_invalid_modify_are_rejected():
    engine = ConstraintEngine()
    engine.register(AllowConstraint())
    with pytest.raises(ValueError):
        engine.register(AllowConstraint())

    command = Command(target="pump", action=CommandAction.START)
    at = datetime(2026, 7, 26, 12, 0, tzinfo=timezone.utc)
    with pytest.raises(ValueError):
        ConstraintDecision(
            constraint_id="bad",
            disposition=ConstraintDisposition.MODIFY,
            command=command,
            reason="missing replacement",
            decided_at=at,
        )
