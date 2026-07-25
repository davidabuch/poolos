from datetime import datetime, timezone

import pytest

from poolos.commands import Command, CommandAction
from poolos.enums import CommandPriority


def test_command_is_immutable_and_has_stable_defaults():
    command = Command(target="pump", action=CommandAction.SET, value=2500)

    assert command.target == "pump"
    assert command.value == 2500
    assert command.priority is CommandPriority.NORMAL
    assert command.issued_at.tzinfo is not None
    assert command.command_id


def test_command_metadata_is_immutable_copy():
    source = {"reason": "filtering"}
    command = Command("pump", CommandAction.START, metadata=source)
    source["reason"] = "changed"

    assert command.metadata["reason"] == "filtering"
    with pytest.raises(TypeError):
        command.metadata["new"] = "value"


def test_command_rejects_naive_timestamp():
    with pytest.raises(ValueError, match="timezone-aware"):
        Command(
            "pump",
            CommandAction.START,
            issued_at=datetime(2026, 1, 1),
        )


def test_deduplication_key_uses_target_and_action():
    command = Command("pump", CommandAction.SET, value=1800)
    assert command.deduplication_key == ("pump", CommandAction.SET)
