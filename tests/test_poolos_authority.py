from datetime import datetime, timedelta, timezone

import pytest

from poolos.authority import (
    AuthorityDecisionReason,
    ControlAuthority,
    ControlSource,
    ControlSourceType,
)
from poolos.clock import FixedClock
from poolos.commands import Command, CommandAction
from poolos.events import EventBus

NOW = datetime(2026, 7, 26, 16, 0, tzinfo=timezone.utc)


def command(source: str, target: str = "pump.main.speed") -> Command:
    return Command(
        target=target,
        action=CommandAction.SET,
        value=2200,
        requested_by=source,
        metadata={"control_source_id": source},
    )


def authority() -> ControlAuthority:
    manager = ControlAuthority(clock=FixedClock(NOW), events=EventBus())
    manager.register_source(ControlSource("home_assistant", ControlSourceType.USER_INTERFACE))
    manager.register_source(ControlSource("pentair_panel", ControlSourceType.LOCAL_PANEL))
    manager.register_source(ControlSource("pool_service", ControlSourceType.SERVICE))
    return manager


def test_home_assistant_is_an_ordinary_poolos_command_source():
    decision = authority().resolve(command("home_assistant"))
    assert decision.allowed
    assert decision.reason is AuthorityDecisionReason.ALLOWED


def test_unknown_source_is_denied_and_audited():
    manager = authority()
    decision = manager.resolve(command("mystery"))
    assert not decision.allowed
    assert decision.reason is AuthorityDecisionReason.UNKNOWN_SOURCE
    assert manager.audit_log() == (decision,)


def test_scoped_manual_override_blocks_poolos_and_ui_but_allows_owner():
    manager = authority()
    lease = manager.acquire_override(
        source_id="pentair_panel", scope="pump.main", duration=timedelta(minutes=30)
    )
    ui = manager.resolve(command("home_assistant"))
    automatic = manager.resolve(command("poolos"))
    owner = manager.resolve(command("pentair_panel"))
    unrelated = manager.resolve(command("poolos", "light.pool"))
    assert not ui.allowed and ui.lease_id == lease.lease_id
    assert not automatic.allowed
    assert owner.allowed
    assert unrelated.allowed


def test_override_expires_and_automatic_control_resumes():
    clock = FixedClock(NOW)
    manager = ControlAuthority(clock=clock)
    manager.register_source(ControlSource("pentair_panel", ControlSourceType.LOCAL_PANEL))
    manager.acquire_override(
        source_id="pentair_panel", scope="pump.main", duration=timedelta(minutes=5)
    )
    assert not manager.resolve(command("poolos")).allowed
    clock.current += timedelta(minutes=6)
    assert manager.resolve(command("poolos")).allowed
    assert manager.active_leases() == ()


def test_service_mode_blocks_every_source_except_service_owner():
    manager = authority()
    lease = manager.enter_service_mode(source_id="pool_service", reason="maintenance")
    denied = manager.resolve(command("home_assistant", "light.pool"))
    allowed = manager.resolve(command("pool_service", "heater.gas"))
    assert not denied.allowed
    assert denied.reason is AuthorityDecisionReason.SERVICE_MODE_ACTIVE
    assert denied.lease_id == lease.lease_id
    assert allowed.allowed
    assert manager.exit_service_mode(reason="complete")
    assert manager.resolve(command("home_assistant", "light.pool")).allowed


def test_only_manual_or_service_sources_can_acquire_override():
    manager = authority()
    with pytest.raises(ValueError):
        manager.acquire_override(source_id="home_assistant", scope="pump.main")
