from dataclasses import dataclass, field

import pytest

from poolos.commands import Command, CommandAction
from poolos.execution import ExecutionEngine, ExecutionStatus
from poolos.work_dispatch import (
    UnsupportedWorkItemError,
    WorkDispatcher,
    build_command_dispatcher,
)


@dataclass
class RecordingExecutor:
    commands: list[Command] = field(default_factory=list)

    def execute(self, command: Command) -> object:
        self.commands.append(command)
        return "ok"


def test_command_dispatcher_preserves_existing_execution_submission_contract():
    execution = ExecutionEngine()
    dispatcher = build_command_dispatcher(execution)
    command = Command("pump", CommandAction.START)

    record = dispatcher.dispatch(command)

    assert record.command is command
    assert record.status is ExecutionStatus.QUEUED
    assert execution.pending() == (command,)


def test_dispatcher_uses_base_type_route_for_specialized_work_items():
    class BaseWork:
        pass

    class SpecializedWork(BaseWork):
        pass

    dispatcher = WorkDispatcher()
    dispatcher.register(BaseWork, lambda item: "base")

    assert dispatcher.dispatch(SpecializedWork()) == "base"


def test_exact_type_route_takes_precedence_over_base_type_route():
    class BaseWork:
        pass

    class SpecializedWork(BaseWork):
        pass

    dispatcher = WorkDispatcher()
    dispatcher.register(BaseWork, lambda item: "base")
    dispatcher.register(SpecializedWork, lambda item: "specialized")

    assert dispatcher.dispatch(SpecializedWork()) == "specialized"


def test_duplicate_route_requires_explicit_replacement():
    dispatcher = WorkDispatcher()
    dispatcher.register(str, lambda item: item)

    with pytest.raises(ValueError, match="already registered"):
        dispatcher.register(str, lambda item: item.upper())

    dispatcher.register(str, lambda item: item.upper(), replace=True)
    assert dispatcher.dispatch("poolos") == "POOLOS"


def test_unsupported_work_item_fails_at_dispatch_boundary():
    dispatcher = WorkDispatcher()

    with pytest.raises(UnsupportedWorkItemError, match="no work handler registered"):
        dispatcher.dispatch(object())
