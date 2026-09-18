from __future__ import annotations

import asyncio
from datetime import timedelta

from poolos.integration import PhysicalHeatMode, SetBodyActive, SetHeatMode, SetPumpSpeed
from poolos.thermal_automatic_execution import (
    ThermalAutomaticDriverState,
    ThermalAutomaticExecutionDriver,
)
from poolos.thermal_runtime_assessment import ThermalRequestedMode, ThermalRuntimeEvaluator
from poolos.thermal_runtime_orchestration import ThermalRuntimeOrchestrator
from test_thermal_automatic_execution import FakeDelivery, FakeDeliveryFactory, NOW, _frame


def test_real_probe_continuity_rejects_unchanged_configured_speed_after_freshness_window() -> None:
    """Reproduce the 2026-09-18 live failure boundary without synthetic freshness."""

    from poolos.grid_outage_confirmation import GridOutageDisposition
    from poolos.thermal_runtime_orchestration import (
        assess_pool_temperature_probe_continuity,
    )
    from test_thermal_automatic_execution import _observation

    started = NOW + timedelta(seconds=3)
    evaluated = started + timedelta(seconds=35)
    observations = (
        _observation("pool.active", True, evaluated),
        _observation("spa.active", False, evaluated),
        _observation("pump.rpm", 1500, evaluated),
        _observation(
            "pool.pump_circuit.configured_speed_rpm",
            1500,
            started,
        ),
        _observation("pool.temperature", 82.0, evaluated),
        _observation("grid.outage_active", False, evaluated),
        _observation("waterfall.active", False, evaluated),
        _observation("jets.active", False, evaluated),
        _observation("slide.active", False, evaluated),
    )

    continuity = assess_pool_temperature_probe_continuity(
        generated_at=evaluated,
        observations=observations,
        prior_grid_disposition=GridOutageDisposition.ON_GRID,
    )

    assert continuity.valid is False
    assert continuity.blocker == "temperature_probe_pool_circulation_not_proven"


def test_real_cadence_probe_hands_off_to_owned_solar_successor() -> None:
    """Carry realistic probe cadence through fresh Solar successor ownership."""

    orchestrator = ThermalRuntimeOrchestrator()
    driver = ThermalAutomaticExecutionDriver(orchestrator)
    delivery = FakeDelivery()
    factory = FakeDeliveryFactory(delivery)
    evaluator = ThermalRuntimeEvaluator()
    baseline = _frame(
        orchestrator,
        NOW,
        pool_active=False,
        mode=ThermalRequestedMode.SOLAR,
        solar_temperature=110.0,
        missing=("pool.temperature",),
        evaluator=evaluator,
        driver=driver,
    )
    driver.note_disabled_epoch(baseline)
    driver.set_enabled(
        True,
        changed_at=NOW,
        current_epoch_identity=baseline.epoch_identity,
    )

    for seconds, active, rpm, configured in (
        (1, False, 0, 2600),
        (2, True, 2600, 2600),
        (3, True, 1500, 1500),
    ):
        frame = _frame(
            orchestrator,
            NOW + timedelta(seconds=seconds),
            pool_active=active,
            pump_rpm=rpm,
            configured_rpm=configured,
            mode=ThermalRequestedMode.SOLAR,
            solar_temperature=110.0,
            missing=("pool.temperature",),
            evaluator=evaluator,
            driver=driver,
        )
        result = asyncio.run(driver.process_epoch(frame, delivery_factory=factory))
        assert result.blocker is None, (seconds, result.state, result.blocker)

    probe = driver.probe_execution_evidence()
    assert probe is not None
    assert probe.phase.value == "acquiring"
    assert probe.acquisition_started_at == NOW + timedelta(seconds=3)
    assert [type(operation).__name__ for operation in delivery.calls] == [
        "SetBodyActive",
        "SetPumpSpeed",
    ]
    assert isinstance(delivery.calls[0], SetBodyActive)
    assert isinstance(delivery.calls[1], SetPumpSpeed)
    assert delivery.calls[1].rpm == 1500

    final = None
    for seconds in (23, 43, 63, 83, 103, 123):
        frame = _frame(
            orchestrator,
            NOW + timedelta(seconds=seconds),
            pool_active=True,
            pump_rpm=1500,
            configured_rpm=1500,
            mode=ThermalRequestedMode.SOLAR,
            solar_temperature=110.0,
            evaluator=evaluator,
            driver=driver,
            real_probe_continuity=True,
        )
        final = asyncio.run(driver.process_epoch(frame, delivery_factory=factory))

    assert evaluator.pool_temperature_probe.started_at == NOW + timedelta(seconds=3)
    assert evaluator.pool_temperature_probe.last_assessment is not None
    assert evaluator.pool_temperature_probe.last_assessment.reason_code == "probe_settled"
    assert final is not None
    assert driver.probe_execution_evidence() is None
    assert len(delivery.calls) == 3
    assert isinstance(delivery.calls[-1], SetPumpSpeed)
    assert delivery.calls[-1].rpm == 2600

    # One semantic morning opportunity may activate the Pool only once.
    # Probe sampling and the probe->Solar successor handoff must never create
    # an OFF/ON replay loop.
    body_calls = [
        operation
        for operation in delivery.calls
        if isinstance(operation, SetBodyActive)
    ]
    assert len(body_calls) == 1
    assert body_calls[0].active is True

    handoff = asyncio.run(
        driver.process_epoch(
            _frame(
                orchestrator,
                NOW + timedelta(seconds=124),
                pool_active=True,
                pump_rpm=2600,
                configured_rpm=2600,
                mode=ThermalRequestedMode.SOLAR,
                solar_temperature=110.0,
                evaluator=evaluator,
                driver=driver,
            ),
            delivery_factory=factory,
        )
    )
    assert handoff.state is ThermalAutomaticDriverState.AWAITING_REOBSERVATION, (
        handoff.state,
        handoff.blocker,
        handoff.runtime_ownership_summary,
        orchestrator.ownership.state.lease,
    )
    assert isinstance(delivery.calls[-1], SetHeatMode)
    assert delivery.calls[-1].mode is PhysicalHeatMode.SOLAR

    observing = asyncio.run(
        driver.process_epoch(
            _frame(
                orchestrator,
                NOW + timedelta(seconds=125),
                pool_active=True,
                pump_rpm=2600,
                configured_rpm=2600,
                pool_heater="H0002",
                mode=ThermalRequestedMode.SOLAR,
                solar_temperature=110.0,
                evaluator=evaluator,
                driver=driver,
            ),
            delivery_factory=factory,
        )
    )
    assert observing.state is ThermalAutomaticDriverState.OBSERVING_SOLAR_ENGAGEMENT

    active = asyncio.run(
        driver.process_epoch(
            _frame(
                orchestrator,
                NOW + timedelta(seconds=126),
                pool_active=True,
                pump_rpm=2600,
                configured_rpm=2600,
                pool_heater="H0002",
                solar_active=True,
                mode=ThermalRequestedMode.SOLAR,
                solar_temperature=110.0,
                evaluator=evaluator,
                driver=driver,
            ),
            delivery_factory=factory,
        )
    )
    assert active.state is ThermalAutomaticDriverState.AWAITING_REOBSERVATION
    assert isinstance(delivery.calls[-1], SetPumpSpeed)
    assert delivery.calls[-1].rpm == 2900

    observing_active = asyncio.run(
        driver.process_epoch(
            _frame(
                orchestrator,
                NOW + timedelta(seconds=127),
                pool_active=True,
                pump_rpm=2900,
                configured_rpm=2900,
                pool_heater="H0002",
                solar_active=True,
                mode=ThermalRequestedMode.SOLAR,
                solar_temperature=110.0,
                evaluator=evaluator,
                driver=driver,
            ),
            delivery_factory=factory,
        )
    )
    assert observing_active.state is ThermalAutomaticDriverState.OBSERVING_SOLAR_ENGAGEMENT

    verified_active = asyncio.run(
        driver.process_epoch(
            _frame(
                orchestrator,
                NOW + timedelta(seconds=156),
                pool_active=True,
                pump_rpm=2900,
                configured_rpm=2900,
                pool_heater="H0002",
                solar_active=True,
                mode=ThermalRequestedMode.SOLAR,
                solar_temperature=110.0,
                evaluator=evaluator,
                driver=driver,
            ),
            delivery_factory=factory,
        )
    )
    assert verified_active.state is ThermalAutomaticDriverState.OBSERVING_SOLAR_ENGAGEMENT

    converged = asyncio.run(
        driver.process_epoch(
            _frame(
                orchestrator,
                NOW + timedelta(seconds=187),
                pool_active=True,
                pump_rpm=2900,
                configured_rpm=2900,
                pool_heater="H0002",
                solar_active=True,
                mode=ThermalRequestedMode.SOLAR,
                solar_temperature=110.0,
                evaluator=evaluator,
                driver=driver,
            ),
            delivery_factory=factory,
        )
    )
    assert converged.state is ThermalAutomaticDriverState.CONVERGED

    lease = orchestrator.ownership.state.lease
    assert lease is not None
    assert lease.owns_body_activation is True
    assert lease.owns_pump_setpoint is True
    assert lease.pump_setpoint is not None
    assert lease.pump_setpoint.intended_value == 2900
    assert lease.owns_heat_source is True


def test_real_cadence_adopted_probe_hands_off_to_owned_solar_successor() -> None:
    """Spa successor: adopted Pool BODY must survive probe -> Solar handoff."""

    orchestrator = ThermalRuntimeOrchestrator()
    driver = ThermalAutomaticExecutionDriver(orchestrator)
    delivery = FakeDelivery()
    factory = FakeDeliveryFactory(delivery)
    evaluator = ThermalRuntimeEvaluator()
    baseline = _frame(
        orchestrator,
        NOW,
        pool_active=False,
        mode=ThermalRequestedMode.SOLAR,
        solar_temperature=125.0,
        missing=("pool.temperature",),
        evaluator=evaluator,
        driver=driver,
    )
    driver.note_disabled_epoch(baseline)
    driver.set_enabled(
        True,
        changed_at=NOW,
        current_epoch_identity=baseline.epoch_identity,
    )

    adopted = _frame(
        orchestrator,
        NOW + timedelta(seconds=1),
        pool_active=True,
        pump_rpm=0,
        configured_rpm=2600,
        pool_heater="H0002",
        solar_active=True,
        mode=ThermalRequestedMode.SOLAR,
        solar_temperature=125.0,
        missing=("pool.temperature",),
        evaluator=evaluator,
        driver=driver,
        pool_opportunity_id="pool:thermal:spa-successor",
    )
    first = asyncio.run(driver.process_epoch(adopted, delivery_factory=factory))
    assert first.state is ThermalAutomaticDriverState.AWAITING_REOBSERVATION
    assert isinstance(delivery.calls[-1], SetHeatMode)
    assert delivery.calls[-1].mode is PhysicalHeatMode.OFF

    source_off = _frame(
        orchestrator,
        NOW + timedelta(seconds=2),
        pool_active=True,
        pump_rpm=0,
        configured_rpm=2600,
        pool_heater="00000",
        solar_active=False,
        mode=ThermalRequestedMode.SOLAR,
        solar_temperature=125.0,
        missing=("pool.temperature",),
        evaluator=evaluator,
        driver=driver,
        pool_opportunity_id="pool:thermal:spa-successor",
    )
    second = asyncio.run(driver.process_epoch(source_off, delivery_factory=factory))
    assert second.state in {
        ThermalAutomaticDriverState.AWAITING_REOBSERVATION,
        ThermalAutomaticDriverState.AWAITING_VERIFICATION,
    }
    assert isinstance(delivery.calls[-1], SetPumpSpeed)
    assert delivery.calls[-1].rpm == 1500

    probe_started = _frame(
        orchestrator,
        NOW + timedelta(seconds=3),
        pool_active=True,
        pump_rpm=1500,
        configured_rpm=1500,
        pool_heater="00000",
        solar_active=False,
        mode=ThermalRequestedMode.SOLAR,
        solar_temperature=125.0,
        missing=("pool.temperature",),
        evaluator=evaluator,
        driver=driver,
        pool_opportunity_id="pool:thermal:spa-successor",
    )
    third = asyncio.run(driver.process_epoch(probe_started, delivery_factory=factory))
    assert third.state is not ThermalAutomaticDriverState.PREEMPTED

    final = None
    for seconds in (23, 43, 63, 83, 103, 123):
        frame = _frame(
            orchestrator,
            NOW + timedelta(seconds=seconds),
            pool_active=True,
            pump_rpm=1500,
            configured_rpm=1500,
            pool_heater="00000",
            solar_active=False,
            mode=ThermalRequestedMode.SOLAR,
            solar_temperature=125.0,
            evaluator=evaluator,
            driver=driver,
            real_probe_continuity=True,
            pool_opportunity_id="pool:thermal:spa-successor",
        )
        final = asyncio.run(driver.process_epoch(frame, delivery_factory=factory))

    assert final is not None
    lease = orchestrator.ownership.state.lease
    assert lease is not None
    assert lease.status.value == "owned", (
        lease.reason_code,
        final.state,
        final.blocker,
        final.runtime_ownership_summary,
    )
    assert lease.owns_body_adoption
    assert driver.probe_execution_evidence() is None

    handoff = asyncio.run(
        driver.process_epoch(
            _frame(
                orchestrator,
                NOW + timedelta(seconds=124),
                pool_active=True,
                pump_rpm=1500,
                configured_rpm=1500,
                pool_heater="00000",
                solar_active=False,
                mode=ThermalRequestedMode.SOLAR,
                solar_temperature=125.0,
                evaluator=evaluator,
                driver=driver,
                pool_opportunity_id="pool:thermal:spa-successor",
            ),
            delivery_factory=factory,
        )
    )
    assert handoff.state is ThermalAutomaticDriverState.AWAITING_REOBSERVATION, (
        handoff.state,
        handoff.blocker,
        handoff.runtime_ownership_summary,
        orchestrator.ownership.state.lease,
    )
    assert isinstance(delivery.calls[-1], SetPumpSpeed)
    assert delivery.calls[-1].rpm == 2600

    prepared = asyncio.run(
        driver.process_epoch(
            _frame(
                orchestrator,
                NOW + timedelta(seconds=125),
                pool_active=True,
                pump_rpm=2600,
                configured_rpm=2600,
                pool_heater="00000",
                solar_active=False,
                mode=ThermalRequestedMode.SOLAR,
                solar_temperature=125.0,
                evaluator=evaluator,
                driver=driver,
                pool_opportunity_id="pool:thermal:spa-successor",
            ),
            delivery_factory=factory,
        )
    )
    assert prepared.state is ThermalAutomaticDriverState.AWAITING_REOBSERVATION
    assert isinstance(delivery.calls[-1], SetHeatMode)
    assert delivery.calls[-1].mode is PhysicalHeatMode.SOLAR

    engaged = asyncio.run(
        driver.process_epoch(
            _frame(
                orchestrator,
                NOW + timedelta(seconds=126),
                pool_active=True,
                pump_rpm=2600,
                configured_rpm=2600,
                pool_heater="H0002",
                solar_active=True,
                mode=ThermalRequestedMode.SOLAR,
                solar_temperature=125.0,
                evaluator=evaluator,
                driver=driver,
                pool_opportunity_id="pool:thermal:spa-successor",
            ),
            delivery_factory=factory,
        )
    )
    assert engaged.state in {
        ThermalAutomaticDriverState.AWAITING_REOBSERVATION,
        ThermalAutomaticDriverState.OBSERVING_SOLAR_ENGAGEMENT,
    }

    if not isinstance(delivery.calls[-1], SetPumpSpeed):
        engaged = asyncio.run(
            driver.process_epoch(
                _frame(
                    orchestrator,
                    NOW + timedelta(seconds=127),
                    pool_active=True,
                    pump_rpm=2600,
                    configured_rpm=2600,
                    pool_heater="H0002",
                    solar_active=True,
                    mode=ThermalRequestedMode.SOLAR,
                    solar_temperature=125.0,
                    evaluator=evaluator,
                    driver=driver,
                    pool_opportunity_id="pool:thermal:spa-successor",
                ),
                delivery_factory=factory,
            )
        )
    assert isinstance(delivery.calls[-1], SetPumpSpeed)
    assert delivery.calls[-1].rpm == 2900
