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
        )
        final = asyncio.run(driver.process_epoch(frame, delivery_factory=factory))

    assert evaluator.pool_temperature_probe.started_at == NOW + timedelta(seconds=3)
    assert evaluator.pool_temperature_probe.last_assessment is not None
    assert evaluator.pool_temperature_probe.last_assessment.reason_code == "probe_settled"
    assert final is not None
    assert driver.probe_execution_evidence() is None
    assert len(delivery.calls) == 3
    assert isinstance(delivery.calls[-1], SetPumpSpeed)
    assert delivery.calls[-1].rpm == 2900

    handoff = asyncio.run(
        driver.process_epoch(
            _frame(
                orchestrator,
                NOW + timedelta(seconds=124),
                pool_active=True,
                pump_rpm=2900,
                configured_rpm=2900,
                mode=ThermalRequestedMode.SOLAR,
                solar_temperature=110.0,
                evaluator=evaluator,
                driver=driver,
            ),
            delivery_factory=factory,
        )
    )
    assert handoff.state is ThermalAutomaticDriverState.AWAITING_REOBSERVATION
    assert isinstance(delivery.calls[-1], SetHeatMode)
    assert delivery.calls[-1].mode is PhysicalHeatMode.SOLAR

    observing = asyncio.run(
        driver.process_epoch(
            _frame(
                orchestrator,
                NOW + timedelta(seconds=125),
                pool_active=True,
                pump_rpm=2900,
                configured_rpm=2900,
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
    assert active.state is ThermalAutomaticDriverState.OBSERVING_SOLAR_ENGAGEMENT

    converged = asyncio.run(
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
    assert converged.state is ThermalAutomaticDriverState.CONVERGED

    lease = orchestrator.ownership.state.lease
    assert lease is not None
    assert lease.owns_body_activation is True
    assert lease.owns_pump_setpoint is True
    assert lease.pump_setpoint is not None
    assert lease.pump_setpoint.intended_value == 2900
    assert lease.owns_heat_source is True
