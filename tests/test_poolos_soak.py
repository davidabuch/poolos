from datetime import datetime, timedelta, timezone

import pytest

from poolos.bodies import Body
from poolos.enums import BodyType
from poolos.kernel import PoolKernel
from poolos.models import BodyState, TemperatureState
from poolos.soak import (
    SimulationSoakSession,
    SoakHealth,
    SoakSessionStatus,
    SoakTestPlan,
)
from poolos.simulation import Simulation

START = datetime(2026, 7, 29, 0, 0, tzinfo=timezone.utc)


def build_simulation() -> Simulation:
    kernel = PoolKernel()
    kernel.bodies.register(Body("pool", "Pool", BodyType.POOL))
    kernel.update_body_state(
        "pool",
        BodyState(
            body=BodyType.POOL,
            temperature=TemperatureState(current=84.0, target=None, heating=False),
            circulation_running=False,
            sanitizer_enabled=False,
        ),
    )
    return Simulation.create(kernel, start_at=START)


def test_multi_day_soak_runs_with_accelerated_time():
    session = SimulationSoakSession(
        build_simulation(),
        SoakTestPlan("three-day baseline", timedelta(days=3), step=timedelta(hours=6)),
    )

    report = session.run()

    assert report.simulated_duration == timedelta(days=3)
    assert report.snapshot_count == 13
    assert report.health is SoakHealth.HEALTHY
    assert session.status is SoakSessionStatus.COMPLETED
    assert session.result is not None


def test_soak_report_contains_dashboard_friendly_counts():
    report = SimulationSoakSession(
        build_simulation(),
        SoakTestPlan("one day", timedelta(days=1), step=timedelta(hours=12)),
    ).run()

    assert report.details == {"body_count": 1, "equipment_count": 0}
    assert report.applied_event_count == 0
    assert report.unavailable_snapshot_count == 0


def test_soak_session_can_only_run_once():
    session = SimulationSoakSession(
        build_simulation(), SoakTestPlan("once", timedelta(hours=1))
    )
    session.run()

    with pytest.raises(RuntimeError, match="only be run once"):
        session.run()


@pytest.mark.parametrize(
    "duration,step,maximum",
    [
        (timedelta(0), timedelta(minutes=1), 0),
        (timedelta(hours=1), timedelta(0), 0),
        (timedelta(hours=1), timedelta(minutes=1), -1),
    ],
)
def test_soak_plan_rejects_invalid_limits(duration, step, maximum):
    with pytest.raises(ValueError):
        SoakTestPlan(
            "invalid",
            duration,
            step=step,
            maximum_unavailable_snapshots=maximum,
        )
