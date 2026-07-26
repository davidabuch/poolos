from datetime import datetime, timedelta, timezone

from poolos.clock import FixedClock
from poolos.commands import Command, CommandAction
from poolos.execution import ExecutionRecord, ExecutionStatus
from poolos.kernel import PoolKernel
from poolos.reconciliation import (
    DriftCategory,
    ReconciliationDisposition,
    ReconciliationEngine,
    VerificationObservation,
    VerificationPolicy,
)


def make_engine():
    clock = FixedClock(datetime(2026, 7, 26, 12, 0, tzinfo=timezone.utc))
    return ReconciliationEngine(clock=clock), clock


def succeeded(command, clock):
    return ExecutionRecord(command, ExecutionStatus.SUCCEEDED, clock.now())


def test_successful_command_creates_due_expectation_and_stabilizes():
    engine, clock = make_engine()
    actual = {"rpm": 1800}
    engine.register_verifier(
        "pump.speed",
        lambda kernel, command: VerificationObservation(
            actual["rpm"] == command.value,
            actual=actual["rpm"],
            category=DriftCategory.HARDWARE,
        ),
        policy=VerificationPolicy(verification_delay=timedelta(seconds=5)),
    )
    command = Command(target="pump.speed", action=CommandAction.SET, value=1800)
    expectation = engine.track(succeeded(command, clock))
    assert expectation is not None

    kernel = PoolKernel(clock=clock)
    assert engine.evaluate(kernel).records == ()
    clock.current += timedelta(seconds=5)
    evaluation = engine.evaluate(kernel)

    assert evaluation.records[0].disposition is ReconciliationDisposition.STABLE
    assert evaluation.records[0].actual == 1800
    assert engine.pending() == ()


def test_mismatch_generates_retry_with_new_identity_and_preserved_intent():
    engine, clock = make_engine()
    engine.register_verifier(
        "pump.speed",
        lambda kernel, command: VerificationObservation(
            False, actual=1200, detail="rpm mismatch", category=DriftCategory.HARDWARE
        ),
        policy=VerificationPolicy(retry_delay=timedelta(seconds=10), max_attempts=3),
    )
    command = Command(target="pump.speed", action=CommandAction.SET, value=1800)
    engine.track(succeeded(command, clock))

    evaluation = engine.evaluate(PoolKernel(clock=clock))
    retry = evaluation.retry_commands[0]

    assert evaluation.records[0].disposition is ReconciliationDisposition.RETRY
    assert retry.command_id != command.command_id
    assert retry.target == command.target
    assert retry.value == command.value
    assert retry.metadata["retry_of"] == command.command_id
    assert retry.metadata["retry_attempt"] == 1


def test_retries_exhaust_without_infinite_resubmission():
    engine, clock = make_engine()
    engine.register_verifier(
        "heater",
        lambda kernel, command: VerificationObservation(False, detail="still off"),
        policy=VerificationPolicy(retry_delay=timedelta(seconds=1), max_attempts=2),
    )
    command = Command(target="heater", action=CommandAction.START)
    engine.track(succeeded(command, clock))
    kernel = PoolKernel(clock=clock)

    first = engine.evaluate(kernel)
    assert first.records[0].disposition is ReconciliationDisposition.RETRY
    clock.current += timedelta(seconds=1)
    second = engine.evaluate(kernel)

    assert second.records[0].disposition is ReconciliationDisposition.EXHAUSTED
    assert second.retry_commands == ()
    assert engine.pending() == ()


def test_namespace_verifier_uses_most_specific_match():
    engine, clock = make_engine()
    seen = []
    engine.register_verifier(
        "pump", lambda kernel, command: seen.append("pump") or VerificationObservation(True),
        namespace=True,
    )
    engine.register_verifier(
        "pump.main", lambda kernel, command: seen.append("main") or VerificationObservation(True),
        namespace=True,
    )
    command = Command(target="pump.main.speed", action=CommandAction.SET, value=2000)
    engine.track(succeeded(command, clock))
    engine.evaluate(PoolKernel(clock=clock))
    assert seen == ["main"]


def test_failed_execution_and_retry_execution_do_not_create_expectations():
    engine, clock = make_engine()
    engine.register_verifier("pump", lambda kernel, command: VerificationObservation(True))
    command = Command(target="pump", action=CommandAction.START)
    failed = ExecutionRecord(command, ExecutionStatus.FAILED, clock.now())
    assert engine.track(failed) is None

    retry = Command(
        target="pump",
        action=CommandAction.START,
        metadata={"reconciliation_expectation_id": "existing"},
    )
    assert engine.track(succeeded(retry, clock)) is None


def test_verifier_exception_is_classified_as_communications_drift():
    engine, clock = make_engine()

    def broken(kernel, command):
        raise RuntimeError("adapter unavailable")

    engine.register_verifier("pump", broken, policy=VerificationPolicy(max_attempts=1))
    command = Command(target="pump", action=CommandAction.START)
    engine.track(succeeded(command, clock))
    record = engine.evaluate(PoolKernel(clock=clock)).records[0]
    assert record.disposition is ReconciliationDisposition.EXHAUSTED
    assert record.category is DriftCategory.COMMUNICATIONS
    assert record.detail == "adapter unavailable"


def test_duplicate_verifier_registration_requires_explicit_replace():
    engine, _ = make_engine()
    def verifier(kernel, command):
        return VerificationObservation(True)
    engine.register_verifier("pump", verifier)
    try:
        engine.register_verifier("pump", verifier)
    except ValueError as exc:
        assert "already registered" in str(exc)
    else:
        raise AssertionError("duplicate verifier should fail")
    engine.register_verifier("pump", verifier, replace_existing=True)


def test_reconciliation_uses_runtime_memory_for_adaptive_delay():
    from poolos.runtime_memory import RuntimeMemory
    now = datetime(2026, 7, 26, 12, 0, tzinfo=timezone.utc)
    clock = FixedClock(now)
    memory = RuntimeMemory(clock=clock, retention_per_metric=10)
    for seconds in (8, 10, 12):
        memory.observe("reconciliation.pump.response_seconds", seconds)
    engine = ReconciliationEngine(clock=clock, memory=memory)
    engine.register_verifier(
        "pump",
        lambda kernel, command: VerificationObservation(True),
        policy=VerificationPolicy(verification_delay=timedelta(seconds=60)),
    )
    command = Command(target="pump", action=CommandAction.START, issued_at=now)
    record = ExecutionRecord(command, ExecutionStatus.SUCCEEDED, now)
    expectation = engine.track(record)
    assert expectation.verify_at == now + timedelta(seconds=15)
