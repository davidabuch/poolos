from __future__ import annotations

import asyncio
from datetime import timedelta

from poolos.integration import PhysicalHeatMode, SetPumpSpeed
from poolos.thermal_execution_currentness import (
    ThermalExecutionCompatibilityDisposition,
    ThermalExecutionCurrentness,
    assess_execution_compatibility,
)
from poolos.thermal_live_execution import (
    ThermalLiveExecutionEngine,
    ThermalLiveExecutionStatus,
)
from test_thermal_live_execution import (
    NOW,
    FakeThermalDelivery,
    evidence,
    policy,
    thermal_plan,
)


def test_aligned_successor_delivers_command_to_establish_real_provenance() -> None:
    """Live 2026-09-16 regression: alignment must not kill the successor.

    The hardware may reach the exact desired 2900/Solar state before the
    successor has accepted its own Pump/Thermal command. Matching state alone
    remains unattributed and grants no ownership. The still-valid live
    successor must nevertheless be allowed to issue its pending command so
    accepted command provenance can be established prospectively.
    """

    originating_plan = thermal_plan(
        PhysicalHeatMode.OFF,
        2600,
        PhysicalHeatMode.SOLAR,
        2900,
    )
    engine = ThermalLiveExecutionEngine()
    session = engine.begin(
        originating_plan,
        policy=policy(),
        evidence=evidence(originating_plan),
    )

    already_aligned_plan = thermal_plan(
        PhysicalHeatMode.SOLAR,
        2900,
        PhysicalHeatMode.SOLAR,
        2900,
    )
    aligned_currentness = ThermalExecutionCurrentness.from_assessment(
        already_aligned_plan,
        evaluation_id="evaluation-aligned",
    )

    # Preserve the anti-fabrication invariant: physical equality by itself is
    # still UNKNOWN and does not manufacture execution provenance.
    compatibility = assess_execution_compatibility(
        session.originating_currentness,
        aligned_currentness,
    )
    assert (
        compatibility.disposition
        is ThermalExecutionCompatibilityDisposition.UNKNOWN
    )
    assert compatibility.reason_code == "thermal_execution_convergence_not_attributed"
    assert not compatibility.continuation_allowed

    current_evidence = evidence(
        originating_plan,
        at=NOW + timedelta(seconds=1),
        evaluation_id=session.evaluation_id,
        current_evaluation_id="evaluation-aligned",
        current_plan_id=already_aligned_plan.plan_id,
        execution_currentness=aligned_currentness,
    )
    delivery = FakeThermalDelivery()

    delivered = asyncio.run(
        engine.deliver_current_step(
            session,
            policy=policy(),
            evidence=current_evidence,
            delivery=delivery,
        )
    )

    # Before the fix this became SUPERSEDED with
    # thermal_execution_convergence_not_attributed and delivered nothing.
    assert delivered.status is ThermalLiveExecutionStatus.AWAITING_VERIFICATION
    assert delivered.failure_reason is None
    assert len(delivery.calls) == 1

    operation, _ = delivery.calls[0]
    assert isinstance(operation, SetPumpSpeed)
    assert operation.rpm == 2900

    # Ownership comes from the accepted PoolOS command, never from equality.
    assert delivered.ownership.owns_pump_setpoint
    assert delivered.ownership.commanded_pump_rpm == 2900



def test_prealigned_native_solar_successor_retains_provenance_and_shuts_down() -> None:
    """Real cadence: native 2900 alignment must not strand the owned BODY."""

    from datetime import timedelta

    from poolos.filtration_policy import FiltrationDisposition
    from poolos.integration import SetBodyActive, SetHeatMode
    from poolos.ownership_evidence import OwnershipDomain
    from poolos.thermal_automatic_execution import (
        ThermalAutomaticDriverState,
        ThermalAutomaticExecutionDriver,
    )
    from poolos.thermal_runtime_assessment import (
        ThermalRequestedMode,
        ThermalRuntimeEvaluator,
    )
    from poolos.thermal_runtime_orchestration import ThermalRuntimeOrchestrator
    from test_thermal_automatic_execution import (
        FakeDelivery,
        FakeDeliveryFactory,
        NOW as AUTO_NOW,
        _frame,
    )

    orchestrator = ThermalRuntimeOrchestrator()
    driver = ThermalAutomaticExecutionDriver(orchestrator)
    delivery = FakeDelivery()
    factory = FakeDeliveryFactory(delivery)
    evaluator = ThermalRuntimeEvaluator()

    # Exact cadence from the accepted probe-successor regression.
    baseline = _frame(
        orchestrator,
        AUTO_NOW,
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
        changed_at=AUTO_NOW,
        current_epoch_identity=baseline.epoch_identity,
    )

    for seconds, active, rpm, configured in (
        (1, False, 0, 2600),
        (2, True, 2600, 2600),
        (3, True, 1500, 1500),
    ):
        result = asyncio.run(
            driver.process_epoch(
                _frame(
                    orchestrator,
                    AUTO_NOW + timedelta(seconds=seconds),
                    pool_active=active,
                    pump_rpm=rpm,
                    configured_rpm=configured,
                    mode=ThermalRequestedMode.SOLAR,
                    solar_temperature=110.0,
                    missing=("pool.temperature",),
                    evaluator=evaluator,
                    driver=driver,
                ),
                delivery_factory=factory,
            )
        )
        assert result.blocker is None, (seconds, result.state, result.blocker)

    # Let the real probe settle.
    for seconds in (23, 43, 63, 83, 103, 123):
        asyncio.run(
            driver.process_epoch(
                _frame(
                    orchestrator,
                    AUTO_NOW + timedelta(seconds=seconds),
                    pool_active=True,
                    pump_rpm=1500,
                    configured_rpm=1500,
                    mode=ThermalRequestedMode.SOLAR,
                    solar_temperature=110.0,
                    evaluator=evaluator,
                    driver=driver,
                ),
                delivery_factory=factory,
            )
        )

    # Existing typed handoff: probe -> 2600 Solar preparation.
    assert isinstance(delivery.calls[-1], SetPumpSpeed)
    assert delivery.calls[-1].rpm == 2600

    # PoolOS legitimately selects H0002.
    handoff = asyncio.run(
        driver.process_epoch(
            _frame(
                orchestrator,
                AUTO_NOW + timedelta(seconds=124),
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
    assert handoff.state is ThermalAutomaticDriverState.AWAITING_REOBSERVATION
    assert isinstance(delivery.calls[-1], SetHeatMode)
    assert delivery.calls[-1].mode is PhysicalHeatMode.SOLAR

    # Authoritative reobservation verifies H0002. Thermal provenance is now real.
    observing = asyncio.run(
        driver.process_epoch(
            _frame(
                orchestrator,
                AUTO_NOW + timedelta(seconds=125),
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

    lease = orchestrator.ownership.state.lease
    assert lease is not None
    assert lease.owns_body_activation
    assert lease.owns_heat_source

    # Solar preparation already legitimately owns the Pump domain at 2600.
    # The live failure is the purpose transition from that owned 2600
    # preparation setpoint to the 2900 Solar-active setpoint when native
    # IntelliCenter reaches 2900 before PoolOS issues the successor command.
    assert lease.owns_pump_setpoint
    assert lease.pump_setpoint is not None
    assert lease.pump_setpoint.intended_value == 2600

    # THE PHYSICAL FAILURE:
    # Solar becomes active and native IntelliCenter has already reached 2900
    # before PoolOS has accepted its own 2900 command.
    #
    # Physical equality MUST NOT create Pump provenance. But it must also not
    # kill the valid successor before it can issue the provenance-establishing
    # command.
    before = len(delivery.calls)
    aligned = asyncio.run(
        driver.process_epoch(
            _frame(
                orchestrator,
                AUTO_NOW + timedelta(seconds=126),
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

    assert aligned.state is ThermalAutomaticDriverState.AWAITING_REOBSERVATION, (
        aligned.state,
        aligned.blocker,
        aligned.last_failure_reason,
        aligned.runtime_ownership_status,
        dict(aligned.runtime_ownership_summary),
    )
    assert len(delivery.calls) == before + 1
    assert isinstance(delivery.calls[-1], SetPumpSpeed)
    assert delivery.calls[-1].rpm == 2900

    # The accepted idempotent PoolOS command, not equality, establishes
    # prospective Pump provenance.
    verified = asyncio.run(
        driver.process_epoch(
            _frame(
                orchestrator,
                AUTO_NOW + timedelta(seconds=127),
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
    assert verified.state is ThermalAutomaticDriverState.OBSERVING_SOLAR_ENGAGEMENT

    # Complete Solar engagement hold.
    for seconds in (156, 187):
        verified = asyncio.run(
            driver.process_epoch(
                _frame(
                    orchestrator,
                    AUTO_NOW + timedelta(seconds=seconds),
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

    assert verified.state is ThermalAutomaticDriverState.CONVERGED

    lease = orchestrator.ownership.state.lease
    assert lease is not None
    assert lease.owns_body_activation
    assert lease.owns_pump_setpoint
    assert lease.owns_heat_source
    assert lease.domain_state(OwnershipDomain.BODY).authority.value == "poolos"
    assert lease.domain_state(OwnershipDomain.PUMP).authority.value == "poolos"
    assert lease.domain_state(OwnershipDomain.THERMAL).authority.value == "poolos"

    # Now reproduce the afternoon/target-satisfied portion. H0002 remains
    # selected until PoolOS itself sends SetHeatMode(OFF).
    physical = {
        "pool_active": True,
        "pump_rpm": 2900,
        "configured_rpm": 2900,
        "pool_heater": "H0002",
        "solar_active": True,
    }
    source_off_seen = False
    body_off_seen = False
    history: list[tuple[int, str, str | None]] = []

    for seconds in range(188, 950):
        prior_count = len(delivery.calls)

        result = asyncio.run(
            driver.process_epoch(
                _frame(
                    orchestrator,
                    AUTO_NOW + timedelta(seconds=seconds),
                    evaluator=evaluator,
                    driver=driver,
                    mode=ThermalRequestedMode.SOLAR,
                    solar_temperature=110.0,
                    pool_temperature=100.0,
                    filtration_remaining=timedelta(0),
                    filtration_disposition=FiltrationDisposition.SATISFIED,
                    **physical,
                ),
                delivery_factory=factory,
            )
        )
        history.append((seconds, result.state.value, result.blocker))

        for operation in delivery.calls[prior_count:]:
            if isinstance(operation, SetHeatMode):
                if operation.mode is PhysicalHeatMode.OFF:
                    source_off_seen = True
                    physical["pool_heater"] = "00000"
                    physical["solar_active"] = False

            elif isinstance(operation, SetBodyActive):
                physical["pool_active"] = operation.active
                if not operation.active:
                    body_off_seen = True
                    physical["pump_rpm"] = 0
                    physical["solar_active"] = False

            elif isinstance(operation, SetPumpSpeed):
                physical["pump_rpm"] = operation.rpm
                physical["configured_rpm"] = operation.rpm

        # This specifically prevents the old false-positive regression:
        # H0002 cannot disappear merely because the simulator wants cleanup
        # to progress.
        if not source_off_seen:
            assert physical["pool_heater"] == "H0002"

        if (
            source_off_seen
            and body_off_seen
            and physical["pool_active"] is False
            and physical["pump_rpm"] == 0
        ):
            final = asyncio.run(
                driver.process_epoch(
                    _frame(
                        orchestrator,
                        AUTO_NOW + timedelta(seconds=seconds + 1),
                        evaluator=evaluator,
                        driver=driver,
                        mode=ThermalRequestedMode.SOLAR,
                        solar_temperature=110.0,
                        pool_temperature=100.0,
                        filtration_remaining=timedelta(0),
                        filtration_disposition=FiltrationDisposition.SATISFIED,
                        **physical,
                    ),
                    delivery_factory=factory,
                )
            )
            history.append(
                (seconds + 1, final.state.value, final.blocker)
            )
            break

    assert source_off_seen, history[-20:]
    assert body_off_seen, history[-20:]
    assert physical["pool_heater"] == "00000", history[-20:]
    assert physical["pool_active"] is False, history[-20:]
    assert physical["pump_rpm"] == 0, history[-20:]
    assert driver.cleanup_attempt is None
    assert driver.cleanup_provenance is None
    assert orchestrator.ownership.residual_termination is None
