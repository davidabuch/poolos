"""Regression coverage for configurable preferred filtration catch-up time."""

from datetime import datetime, time, timedelta
from zoneinfo import ZoneInfo

from poolos.filtration_policy import (
    FiltrationAccountingTracker,
    FiltrationDisposition,
    FiltrationObligation,
    FiltrationPolicy,
)
from poolos.time_of_use_policy import LADWP_INITIAL_PROFILE


LOCAL = ZoneInfo(LADWP_INITIAL_PROFILE.timezone_name)


def test_filtration_policy_accepts_2200_preferred_catchup_start() -> None:
    policy = FiltrationPolicy(
        LADWP_INITIAL_PROFILE,
        preferred_catchup_start=time(hour=22),
    )

    result = policy.evaluate(
        FiltrationObligation(timedelta(hours=8)),
        evaluated_at=datetime(2026, 9, 9, 8, 0, tzinfo=LOCAL),
        safely_deferrable=True,
    )

    assert result.disposition is FiltrationDisposition.DEFERRED_OPTIMIZATION
    assert result.next_suitable_at == datetime(
        2026,
        9,
        9,
        22,
        0,
        tzinfo=LOCAL,
    )


def test_2200_preference_preserves_completion_capacity_backstop() -> None:
    policy = FiltrationPolicy(
        LADWP_INITIAL_PROFILE,
        preferred_catchup_start=time(hour=22),
    )

    result = policy.evaluate(
        FiltrationObligation(timedelta(hours=12)),
        evaluated_at=datetime(2026, 9, 9, 8, 0, tzinfo=LOCAL),
        safely_deferrable=True,
    )

    assert result.disposition is FiltrationDisposition.DEFERRED_OPTIMIZATION
    assert result.next_suitable_at == datetime(
        2026,
        9,
        9,
        19,
        30,
        tzinfo=LOCAL,
    )


def test_accounting_tracker_accepts_preferred_catchup_start() -> None:
    tracker = FiltrationAccountingTracker(
        tou_profile=LADWP_INITIAL_PROFILE,
        preferred_catchup_start=time(hour=22),
    )

    assert tracker is not None


def test_home_assistant_exposes_persistent_preferred_catchup_option() -> None:
    from pathlib import Path

    root = Path(__file__).resolve().parents[1]
    component = root / "custom_components" / "poolos"

    const_source = (component / "const.py").read_text(encoding="utf-8")
    flow_source = (component / "config_flow.py").read_text(encoding="utf-8")
    runtime_source = (component / "filtration_runtime.py").read_text(
        encoding="utf-8"
    )
    setup_source = (component / "__init__.py").read_text(encoding="utf-8")

    assert 'CONF_PREFERRED_FILTRATION_CATCHUP_START = ' in const_source
    assert 'DEFAULT_PREFERRED_FILTRATION_CATCHUP_START = "20:00"' in const_source

    assert "CONF_PREFERRED_FILTRATION_CATCHUP_START" in flow_source
    assert "DEFAULT_PREFERRED_FILTRATION_CATCHUP_START" in flow_source
    assert "selector.TimeSelector()" in flow_source
    assert 'vol.Match(r"(?:[01]\\d|2[0-3]):[0-5]\\d")' not in flow_source

    assert "preferred_catchup_start" in runtime_source
    assert "preferred_catchup_start=" in runtime_source

    assert "CONF_PREFERRED_FILTRATION_CATCHUP_START" in setup_source
    assert "preferred_catchup_start=" in setup_source


def test_home_assistant_filtration_runtime_uses_configured_2200_preference() -> None:
    import importlib.util
    import sys
    from pathlib import Path
    from types import ModuleType, SimpleNamespace

    root = Path(__file__).resolve().parents[1]
    module_path = (
        root
        / "custom_components"
        / "poolos"
        / "filtration_runtime.py"
    )

    package_name = "poolos_configurable_catchup_regression"

    package = ModuleType(package_name)
    package.__path__ = [str(module_path.parent)]
    package.__package__ = package_name
    sys.modules[package_name] = package

    observation = ModuleType(f"{package_name}.observation")

    class ObservationSnapshot:
        pass

    observation.ObservationSnapshot = ObservationSnapshot
    sys.modules[f"{package_name}.observation"] = observation

    coordinator = ModuleType(f"{package_name}.coordinator")

    class PoolOSCoordinator:
        pass

    coordinator.PoolOSCoordinator = PoolOSCoordinator
    sys.modules[f"{package_name}.coordinator"] = coordinator

    spec = importlib.util.spec_from_file_location(
        f"{package_name}.filtration_runtime",
        module_path,
    )
    assert spec is not None
    assert spec.loader is not None

    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)

    runtime = module.PoolOSFiltrationRuntime(
        coordinator=SimpleNamespace(),
        preferred_catchup_start=time(hour=22),
    )

    result = runtime.tracker._policy.evaluate(
        FiltrationObligation(timedelta(hours=8)),
        evaluated_at=datetime(2026, 9, 9, 8, 0, tzinfo=LOCAL),
        safely_deferrable=True,
    )

    assert result.disposition is FiltrationDisposition.DEFERRED_OPTIMIZATION
    assert result.next_suitable_at == datetime(
        2026,
        9,
        9,
        22,
        0,
        tzinfo=LOCAL,
    )