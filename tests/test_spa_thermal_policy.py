from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

import pytest

from poolos.spa_thermal_policy import SpaHeatingMode, SpaPolicyInput, SpaPolicyState, SpaThermalPolicyTracker, SpaUserSource
from poolos.thermal_source_policy import HeatSourcePermissions, ThermalHeatSource


LOCAL = ZoneInfo("America/Los_Angeles")
NOW = datetime(2026, 8, 26, 14, 0, tzinfo=LOCAL)


def observation(*, at: datetime = NOW, active: bool = False, source: SpaUserSource | None = None, spa: float = 90, target: float = 100, roof: float = 125, mode: SpaHeatingMode = SpaHeatingMode.SOLAR_PREFERRED, allowed: bool = True, pool_satisfied: bool = True, debt: timedelta = timedelta(0), conflict: bool = False, permissions: HeatSourcePermissions = HeatSourcePermissions()) -> SpaPolicyInput:
    return SpaPolicyInput(at, active, source, spa, target, roof, mode, permissions, allowed, pool_satisfied, debt, conflict)


@pytest.mark.parametrize("source", (SpaUserSource.HOME_ASSISTANT, SpaUserSource.ICP, SpaUserSource.OCP))
def test_all_user_sources_create_and_end_one_spa_in_use_session(source: SpaUserSource) -> None:
    tracker = SpaThermalPolicyTracker()
    active = tracker.evaluate(observation(active=True, source=source))
    off = tracker.evaluate(observation(at=NOW + timedelta(minutes=1), active=False, source=source, allowed=False))
    assert active.spa_in_use
    assert active.state is SpaPolicyState.SPA_IN_USE_HEAT_UP
    assert not off.spa_in_use


def test_user_spa_uses_gas_immediately_without_pool_probe() -> None:
    result = SpaThermalPolicyTracker().evaluate(observation(active=True, source=SpaUserSource.ICP, roof=129))
    assert result.heat_source is ThermalHeatSource.GAS
    assert result.recommended_pump_rpm == 3000
    assert not result.pool_reprobe_allowed


def test_heat_up_switches_gas_to_solar_after_130_for_two_minutes() -> None:
    tracker = SpaThermalPolicyTracker()
    first = tracker.evaluate(observation(active=True, source=SpaUserSource.HOME_ASSISTANT, roof=130))
    solar = tracker.evaluate(observation(at=NOW + timedelta(minutes=2), active=True, roof=130))
    assert first.heat_source is ThermalHeatSource.GAS
    assert solar.heat_source is ThermalHeatSource.SOLAR
    assert solar.recommended_pump_rpm == 2900


def test_heat_up_solar_falls_back_after_below_130_for_two_minutes() -> None:
    tracker = SpaThermalPolicyTracker()
    tracker.evaluate(observation(active=True, roof=130))
    tracker.evaluate(observation(at=NOW + timedelta(minutes=2), active=True, roof=130))
    still_solar = tracker.evaluate(observation(at=NOW + timedelta(minutes=3), active=True, roof=129))
    gas = tracker.evaluate(observation(at=NOW + timedelta(minutes=5), active=True, roof=129))
    assert still_solar.heat_source is ThermalHeatSource.SOLAR
    assert gas.heat_source is ThermalHeatSource.GAS


def test_target_reached_latches_maintenance_for_remainder_of_session() -> None:
    tracker = SpaThermalPolicyTracker()
    tracker.evaluate(observation(active=True, spa=100, target=100, roof=125))
    result = tracker.evaluate(observation(at=NOW + timedelta(minutes=1), active=True, spa=98.5, target=100, roof=125))
    assert result.state is SpaPolicyState.SPA_IN_USE_MAINTENANCE
    assert result.heat_source is ThermalHeatSource.SOLAR


def test_maintenance_source_rules() -> None:
    tracker = SpaThermalPolicyTracker()
    tracker.evaluate(observation(active=True, spa=100, roof=125))
    solar = tracker.evaluate(observation(at=NOW + timedelta(minutes=1), active=True, spa=99, roof=120))
    low_roof = tracker.evaluate(observation(at=NOW + timedelta(minutes=2), active=True, spa=99, roof=119))
    deficit = tracker.evaluate(observation(at=NOW + timedelta(minutes=3), active=True, spa=97, roof=125))
    hot_roof = tracker.evaluate(observation(at=NOW + timedelta(minutes=4), active=True, spa=97, roof=130))
    assert solar.heat_source is ThermalHeatSource.SOLAR
    assert low_roof.heat_source is ThermalHeatSource.GAS
    assert deficit.heat_source is ThermalHeatSource.GAS
    assert hot_roof.heat_source is ThermalHeatSource.SOLAR


def test_spa_gas_only_suppresses_solar_and_opportunistic() -> None:
    user = SpaThermalPolicyTracker().evaluate(observation(active=True, roof=140, mode=SpaHeatingMode.GAS_ONLY))
    opportunistic = SpaThermalPolicyTracker().evaluate(observation(active=False, roof=140, mode=SpaHeatingMode.GAS_ONLY))
    assert user.heat_source is ThermalHeatSource.GAS
    assert opportunistic.state is SpaPolicyState.IDLE


def test_opportunistic_toggle_off_blocks_entry_without_affecting_user_spa() -> None:
    autonomous = SpaThermalPolicyTracker().evaluate(observation(roof=140, allowed=False))
    user = SpaThermalPolicyTracker().evaluate(
        observation(active=True, source=SpaUserSource.HOME_ASSISTANT, roof=140, allowed=False)
    )
    assert autonomous.state is SpaPolicyState.IDLE
    assert user.spa_in_use


def test_opportunistic_entry_requires_window_toggle_debt_and_two_minutes_at_130() -> None:
    tracker = SpaThermalPolicyTracker()
    early = tracker.evaluate(observation(at=NOW.replace(hour=12), roof=140))
    debt = tracker.evaluate(observation(at=NOW, roof=140, debt=timedelta(minutes=1)))
    first = tracker.evaluate(observation(at=NOW + timedelta(minutes=1), roof=130))
    active = tracker.evaluate(observation(at=NOW + timedelta(minutes=3), roof=130))
    assert early.state is SpaPolicyState.IDLE
    assert debt.state is SpaPolicyState.IDLE
    assert first.state is SpaPolicyState.OPPORTUNISTIC_QUALIFYING
    assert active.state is SpaPolicyState.OPPORTUNISTIC_ACTIVE
    assert active.heat_source is ThermalHeatSource.SOLAR


def test_opportunistic_continues_to_120_then_enters_isolated_hold() -> None:
    tracker = SpaThermalPolicyTracker()
    tracker.evaluate(observation(roof=130))
    tracker.evaluate(observation(at=NOW + timedelta(minutes=2), roof=130))
    useful = tracker.evaluate(observation(at=NOW + timedelta(minutes=3), roof=120))
    tracker.evaluate(observation(at=NOW + timedelta(minutes=4), roof=119))
    hold = tracker.evaluate(observation(at=NOW + timedelta(minutes=6), roof=119))
    assert useful.heat_source is ThermalHeatSource.SOLAR
    assert hold.state is SpaPolicyState.OPPORTUNISTIC_HOLD
    assert hold.preserve_spa_mode
    assert hold.recommended_pump_rpm is None
    assert not hold.pool_reprobe_allowed


def test_opportunistic_target_is_a_cap_not_a_gas_backed_obligation() -> None:
    tracker = SpaThermalPolicyTracker()
    tracker.evaluate(observation(roof=130))
    tracker.evaluate(observation(at=NOW + timedelta(minutes=2), roof=130))
    capped = tracker.evaluate(
        observation(at=NOW + timedelta(minutes=3), spa=100, target=100, roof=130)
    )
    assert capped.state is SpaPolicyState.OPPORTUNISTIC_HOLD
    assert capped.heat_source is ThermalHeatSource.NONE
    assert capped.preserve_spa_mode


def test_opportunistic_hold_resumes_after_two_minutes_at_130_before_six() -> None:
    tracker = SpaThermalPolicyTracker()
    tracker.evaluate(observation(roof=130))
    tracker.evaluate(observation(at=NOW + timedelta(minutes=2), roof=130))
    tracker.evaluate(observation(at=NOW + timedelta(minutes=3), roof=119))
    tracker.evaluate(observation(at=NOW + timedelta(minutes=5), roof=119))
    tracker.evaluate(observation(at=NOW + timedelta(minutes=6), roof=130))
    resumed = tracker.evaluate(observation(at=NOW + timedelta(minutes=8), roof=130))
    assert resumed.state is SpaPolicyState.OPPORTUNISTIC_ACTIVE


def test_user_claims_opportunistic_spa_and_off_can_return_to_policy() -> None:
    tracker = SpaThermalPolicyTracker()
    tracker.evaluate(observation(roof=130))
    tracker.evaluate(observation(at=NOW + timedelta(minutes=2), roof=130))
    claimed = tracker.evaluate(observation(at=NOW + timedelta(minutes=3), active=True, source=SpaUserSource.OCP, roof=125))
    off = tracker.evaluate(observation(at=NOW + timedelta(minutes=4), active=False, source=SpaUserSource.OCP, roof=130))
    assert claimed.spa_in_use
    assert claimed.heat_source is ThermalHeatSource.GAS
    assert off.state in {SpaPolicyState.OPPORTUNISTIC_QUALIFYING, SpaPolicyState.OPPORTUNISTIC_ACTIVE}


def test_six_pm_preserves_spa_and_ten_pm_releases_to_pool() -> None:
    tracker = SpaThermalPolicyTracker()
    six = tracker.evaluate(observation(at=NOW.replace(hour=18), roof=130))
    ten = tracker.evaluate(observation(at=NOW.replace(hour=22), roof=130))
    assert six.state is SpaPolicyState.PRESERVE_UNTIL_10PM and six.preserve_spa_mode
    assert ten.state is SpaPolicyState.RELEASE_TO_POOL and not ten.preserve_spa_mode


def test_opportunistic_never_uses_gas_even_when_solar_permission_is_off() -> None:
    result = SpaThermalPolicyTracker().evaluate(observation(roof=80, permissions=HeatSourcePermissions(solar_allowed=False, gas_allowed=True)))
    assert result.heat_source is ThermalHeatSource.NONE


def test_restart_actual_equipment_state_overrides_stale_session_marker() -> None:
    tracker = SpaThermalPolicyTracker()
    off = tracker.recover(evaluated_at=NOW, actual_spa_active=False, persisted_session_active=True)
    on = SpaThermalPolicyTracker().recover(evaluated_at=NOW, actual_spa_active=True, persisted_session_active=False)
    assert not off.spa_in_use
    assert on.spa_in_use
    assert on.state is SpaPolicyState.SPA_IN_USE_HEAT_UP
