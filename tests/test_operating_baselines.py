from datetime import datetime, timedelta, timezone

from poolos.operating_baselines import PumpAntiChatterPolicy, PumpOperatingBaselines, PumpTransitionOrigin


NOW = datetime(2026, 8, 26, tzinfo=timezone.utc)


def test_known_good_baselines_are_configurable_and_not_gpm_based() -> None:
    values = PumpOperatingBaselines()
    assert (
        values.temperature_probe_rpm,
        values.grid_outage_rpm,
        values.filtration_rpm,
        values.solar_heating_rpm,
        values.spillway_rpm,
        values.gas_heating_rpm,
    ) == (1500, 1500, 2600, 2900, 2900, 3000)
    assert "gpm" not in PumpOperatingBaselines.__dataclass_fields__


def test_automatic_transitions_observe_one_minute_on_and_off_guards() -> None:
    policy = PumpAntiChatterPolicy()
    assert not policy.permits(evaluated_at=NOW + timedelta(seconds=59), currently_on=False, requested_on=True, last_transition_at=NOW, origin=PumpTransitionOrigin.AUTONOMOUS)
    assert policy.permits(evaluated_at=NOW + timedelta(minutes=1), currently_on=False, requested_on=True, last_transition_at=NOW, origin=PumpTransitionOrigin.AUTONOMOUS)
    assert not policy.permits(evaluated_at=NOW + timedelta(seconds=59), currently_on=True, requested_on=False, last_transition_at=NOW, origin=PumpTransitionOrigin.AUTONOMOUS)


def test_user_and_safety_transitions_override_anti_chatter() -> None:
    policy = PumpAntiChatterPolicy()
    for origin in (PumpTransitionOrigin.USER, PumpTransitionOrigin.SAFETY):
        assert policy.permits(evaluated_at=NOW + timedelta(seconds=1), currently_on=True, requested_on=False, last_transition_at=NOW, origin=origin)
