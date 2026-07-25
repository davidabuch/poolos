from dataclasses import dataclass, field

from poolos.commands import Command, CommandAction
from poolos.enums import CommandPriority
from poolos.execution import ExecutionEngine, ExecutionStatus


@dataclass
class RecordingExecutor:
    commands: list[Command] = field(default_factory=list)
    result: object = "ok"

    def execute(self, command: Command) -> object:
        self.commands.append(command)
        return self.result


class FailingExecutor:
    def execute(self, command: Command) -> object:
        raise RuntimeError("adapter failure")


def test_execution_orders_by_priority_then_submission_order():
    engine = ExecutionEngine()
    pump = RecordingExecutor()
    light = RecordingExecutor()
    engine.register_executor("pump", pump)
    engine.register_executor("light", light)

    normal = Command("pump", CommandAction.START)
    critical = Command(
        "light", CommandAction.STOP, priority=CommandPriority.CRITICAL
    )
    engine.submit(normal)
    engine.submit(critical)

    completed = engine.drain()

    assert [record.command for record in completed] == [critical, normal]
    assert all(record.status is ExecutionStatus.SUCCEEDED for record in completed)


def test_latest_matching_command_supersedes_pending_command():
    engine = ExecutionEngine()
    executor = RecordingExecutor()
    engine.register_executor("pump", executor)

    first = Command("pump", CommandAction.SET, value=1800)
    second = Command("pump", CommandAction.SET, value=2400)
    engine.submit(first)
    engine.submit(second)

    assert engine.pending() == (second,)
    superseded = [
        record
        for record in engine.audit_log()
        if record.status is ExecutionStatus.SUPERSEDED
    ]
    assert [record.command for record in superseded] == [first]


def test_validator_rejects_before_queueing():
    engine = ExecutionEngine()

    def reject_high_speed(command: Command) -> None:
        if command.value == 3450:
            raise ValueError("speed exceeds configured maximum")

    engine.add_validator(reject_high_speed)
    command = Command("pump", CommandAction.SET, value=3450)

    record = engine.submit(command)

    assert record.status is ExecutionStatus.REJECTED
    assert engine.pending() == ()
    assert "configured maximum" in (record.detail or "")


def test_missing_executor_is_rejected_at_dispatch():
    engine = ExecutionEngine()
    command = Command("unknown", CommandAction.START)
    engine.submit(command)

    record = engine.run_next()

    assert record is not None
    assert record.status is ExecutionStatus.REJECTED
    assert "no executor registered" in (record.detail or "")


def test_executor_failure_is_audited_without_raising():
    engine = ExecutionEngine()
    engine.register_executor("heater", FailingExecutor())
    command = Command("heater", CommandAction.START)
    engine.submit(command)

    record = engine.run_next()

    assert record is not None
    assert record.status is ExecutionStatus.FAILED
    assert record.detail == "adapter failure"


def test_drain_limit_leaves_remaining_commands_pending():
    engine = ExecutionEngine()
    engine.register_executor("pump", RecordingExecutor())
    engine.register_executor("light", RecordingExecutor())
    engine.submit(Command("pump", CommandAction.START))
    engine.submit(Command("light", CommandAction.START))

    completed = engine.drain(limit=1)

    assert len(completed) == 1
    assert len(engine.pending()) == 1


def test_execution_records_use_injected_clock():
    from datetime import datetime, timezone

    from poolos.clock import FixedClock

    timestamp = datetime(2026, 7, 25, 18, 0, tzinfo=timezone.utc)
    engine = ExecutionEngine(clock=FixedClock(timestamp))
    record = engine.submit(Command("pump", CommandAction.START))

    assert record.recorded_at == timestamp


def test_executor_registration_rejects_accidental_replacement():
    import pytest

    engine = ExecutionEngine()
    engine.register_executor("pump", RecordingExecutor())

    with pytest.raises(ValueError, match="already registered"):
        engine.register_executor("pump", RecordingExecutor())


def test_duplicate_command_id_is_rejected():
    engine = ExecutionEngine()
    command = Command("pump", CommandAction.START, command_id="same-id")

    first = engine.submit(command)
    duplicate = engine.submit(command)

    assert first.status is ExecutionStatus.QUEUED
    assert duplicate.status is ExecutionStatus.REJECTED
    assert "duplicate command_id" in (duplicate.detail or "")
