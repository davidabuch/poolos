from datetime import datetime, timedelta, timezone

from poolos.water_temperature_policy import TemperatureSample, WaterTemperatureDisposition, WaterTemperatureTracker


NOW = datetime(2026, 8, 26, 18, 0, tzinfo=timezone.utc)


def evaluate(tracker: WaterTemperatureTracker, *, at: datetime = NOW, temperature: float | None = 86, circulating: bool = False, probe: bool = False, started: datetime | None = None, samples: tuple[TemperatureSample, ...] = (), roof: float | None = 95, decision: bool = True):
    return tracker.evaluate(evaluated_at=at, observed_temperature_f=temperature, pool_circulating=circulating, probe_active=probe, probe_started_at=started, samples=samples, collector_temperature_f=roof, thermal_decision_requested=decision)


def test_idle_pipe_temperature_is_not_bulk_water_and_probe_is_demand_driven() -> None:
    tracker = WaterTemperatureTracker()
    idle = evaluate(tracker, roof=75)
    actionable = evaluate(tracker, at=NOW + timedelta(minutes=1), roof=95)
    assert idle.disposition is WaterTemperatureDisposition.NOT_REQUIRED
    assert idle.trusted_temperature_f is None
    assert actionable.disposition is WaterTemperatureDisposition.PROBE_REQUIRED
    assert actionable.recommended_pump_rpm == 1500


def test_existing_circulation_bypasses_probe_and_trusts_temperature() -> None:
    result = evaluate(WaterTemperatureTracker(), circulating=True)
    assert result.disposition is WaterTemperatureDisposition.TRUSTED
    assert result.trusted_temperature_f == 86
    assert result.recommended_pump_rpm is None


def test_probe_requires_two_minutes_and_accepts_smooth_one_degree_per_minute() -> None:
    tracker = WaterTemperatureTracker()
    started = NOW
    early = evaluate(tracker, at=NOW + timedelta(minutes=1), probe=True, started=started)
    samples = (TemperatureSample(NOW + timedelta(minutes=1), 86), TemperatureSample(NOW + timedelta(minutes=2), 87))
    settled = evaluate(tracker, at=NOW + timedelta(minutes=2), temperature=87, probe=True, started=started, samples=samples)
    assert early.disposition is WaterTemperatureDisposition.PROBING
    assert settled.disposition is WaterTemperatureDisposition.TRUSTED
    assert settled.trusted_temperature_f == 87


def test_flush_and_oscillation_are_not_accepted() -> None:
    flush = (TemperatureSample(NOW + timedelta(minutes=1), 98), TemperatureSample(NOW + timedelta(minutes=1, seconds=20), 94), TemperatureSample(NOW + timedelta(minutes=2), 88))
    bounce = (TemperatureSample(NOW + timedelta(minutes=1), 86), TemperatureSample(NOW + timedelta(minutes=1, seconds=30), 87), TemperatureSample(NOW + timedelta(minutes=2), 86))
    assert evaluate(WaterTemperatureTracker(), at=NOW + timedelta(minutes=2), probe=True, started=NOW, samples=flush).disposition is WaterTemperatureDisposition.PROBING
    assert evaluate(WaterTemperatureTracker(), at=NOW + timedelta(minutes=2), probe=True, started=NOW, samples=bounce).disposition is WaterTemperatureDisposition.PROBING


def test_probe_fails_closed_at_five_minutes() -> None:
    result = evaluate(WaterTemperatureTracker(), at=NOW + timedelta(minutes=5), probe=True, started=NOW)
    assert result.disposition is WaterTemperatureDisposition.ACQUISITION_FAILED
    assert result.recommended_pump_rpm is None


def test_trusted_temperature_reused_for_thirty_minutes_then_stales() -> None:
    tracker = WaterTemperatureTracker()
    evaluate(tracker, circulating=True)
    within = evaluate(tracker, at=NOW + timedelta(minutes=30), circulating=False)
    stale = evaluate(tracker, at=NOW + timedelta(minutes=31), circulating=False)
    assert within.disposition is WaterTemperatureDisposition.REUSED
    assert stale.disposition is WaterTemperatureDisposition.PROBE_REQUIRED


def test_successful_probe_result_is_reused_without_reprobing() -> None:
    tracker = WaterTemperatureTracker()
    samples = (TemperatureSample(NOW + timedelta(minutes=1), 86), TemperatureSample(NOW + timedelta(minutes=2), 87))
    evaluate(tracker, at=NOW + timedelta(minutes=2), probe=True, started=NOW, samples=samples)
    result = evaluate(tracker, at=NOW + timedelta(minutes=10), probe=False, roof=96)
    assert result.disposition is WaterTemperatureDisposition.REUSED
    assert result.trusted_temperature_f == 87
