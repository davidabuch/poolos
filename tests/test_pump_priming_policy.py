from datetime import timedelta

import pytest

from poolos.operating_baselines import PumpOperatingBaselines
from poolos.pump_priming_policy import (
    PumpPrimingDisposition,
    PumpPrimingPolicy,
)


def test_cold_start_requires_3000_rpm_prime_for_60_seconds() -> None:
    decision = PumpPrimingPolicy().evaluate(
        circulation_requested=True,
        currently_circulating=False,
    )

    assert decision.disposition is PumpPrimingDisposition.REQUIRED
    assert decision.priming_required is True
    assert decision.priming_rpm == 3000
    assert decision.minimum_duration == timedelta(seconds=60)


def test_running_pump_does_not_reprime_for_new_requirement() -> None:
    decision = PumpPrimingPolicy().evaluate(
        circulation_requested=True,
        currently_circulating=True,
    )

    assert (
        decision.disposition
        is PumpPrimingDisposition.NOT_REQUIRED_ALREADY_CIRCULATING
    )
    assert decision.priming_required is False
    assert decision.priming_rpm is None
    assert decision.minimum_duration is None


def test_no_circulation_request_does_not_prime() -> None:
    decision = PumpPrimingPolicy().evaluate(
        circulation_requested=False,
        currently_circulating=False,
    )

    assert decision.disposition is PumpPrimingDisposition.NOT_REQUIRED_NO_START
    assert decision.priming_required is False
    assert decision.priming_rpm is None
    assert decision.minimum_duration is None


def test_priming_baseline_is_explicit_and_independent() -> None:
    baselines = PumpOperatingBaselines()

    assert baselines.priming_rpm == 3000
    assert baselines.filtration_rpm == 2600
    assert baselines.solar_heating_rpm == 2900
    assert baselines.temperature_probe_rpm == 1500
    assert baselines.grid_outage_rpm == 1500


def test_nonpositive_priming_duration_is_rejected() -> None:
    with pytest.raises(ValueError, match="minimum_duration must be positive"):
        PumpPrimingPolicy(minimum_duration=timedelta(0))
