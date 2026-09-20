"""Physical-cadence regressions for fresh Solar reacquisition currentness."""

from __future__ import annotations

import asyncio
from datetime import timedelta

import pytest

from poolos.filtration_policy import FiltrationDisposition
from poolos.integration import (
    PhysicalHeatMode,
    SetBodyActive,
    SetHeatMode,
    SetPumpSpeed,
)
from poolos.ownership_evidence import (
    OwnershipAuthority,
    OwnershipDomain,
    OwnershipHealth,
)
from poolos.pump_speed_session import PumpSpeedSessionPurpose
from poolos.thermal_automatic_execution import (
    ThermalAutomaticDriverState,
    ThermalAutomaticExecutionDriver,
)
from poolos.thermal_execution_currentness import assess_execution_compatibility
from poolos.thermal_live_execution import ThermalLiveExecutionStatus
from poolos.thermal_runtime_assessment import (
    ThermalRequestedMode,
    ThermalRuntimeEvaluator,
)
from poolos.thermal_runtime_orchestration import ThermalRuntimeOrchestrator
from test_thermal_automatic_execution import (
    FakeDelivery,
    FakeDeliveryFactory,
    NOW,
    _frame,
)


def test_fresh_solar_reacquisition_delivers_source_after_slow_compatible_probe_successor() -> None:
    """A fresh Solar opportunity may outlive its first immutable plan instance."""

    orchestrator = ThermalRuntimeOrchestrator()
    driver = ThermalAutomaticExecutionDriver(orchestrator)
    delivery = FakeDelivery()
    factory = FakeDeliveryFactory(delivery, driver=driver)
    evaluator = ThermalRuntimeEvaluator()
    baseline = _frame(
        orchestrator,
        NOW,
        pool_active=False,
        pump_rpm=0,
        configured_rpm=2600,
        pool_heater="00000",
        solar_active=False,
        pool_temperature=81.0,
        solar_temperature=94.0,
        mode=ThermalRequestedMode.SOLAR,
        missing=("pool.temperature",),
        evaluator=evaluator,
        driver=driver,
        verification_timeout=timedelta(seconds=300),
    )
    assert orchestrator.ownership.state.lease is None
    assert orchestrator.ownership.residual_termination is None
    assert driver.cleanup_provenance is None
    driver.note_disabled_epoch(baseline)
    driver.set_enabled(
        True,
        changed_at=NOW,
        current_epoch_identity=baseline.epoch_identity,
    )

    for seconds, pool_active, rpm, configured in (
        (1, False, 0, 2600),
        (2, True, 2600, 2600),
        (3, True, 1500, 1500),
    ):
        result = asyncio.run(
            driver.process_epoch(
                _frame(
                    orchestrator,
                    NOW + timedelta(seconds=seconds),
                    pool_active=pool_active,
                    pump_rpm=rpm,
                    configured_rpm=configured,
                    pool_heater="00000",
                    solar_active=False,
                    pool_temperature=81.0,
                    solar_temperature=94.0,
                    mode=ThermalRequestedMode.SOLAR,
                    missing=("pool.temperature",),
                    evaluator=evaluator,
                    driver=driver,
                    verification_timeout=timedelta(seconds=300),
                ),
                delivery_factory=factory,
            )
        )
        assert result.blocker is None, (seconds, result.state, result.blocker)

    for seconds in (23, 43, 63, 83, 103, 123):
        result = asyncio.run(
            driver.process_epoch(
                _frame(
                    orchestrator,
                    NOW + timedelta(seconds=seconds),
                    pool_active=True,
                    pump_rpm=1500,
                    configured_rpm=1500,
                    pool_heater="00000",
                    solar_active=False,
                    pool_temperature=81.0,
                    solar_temperature=94.0,
                    mode=ThermalRequestedMode.SOLAR,
                    evaluator=evaluator,
                    driver=driver,
                    verification_timeout=timedelta(seconds=300),
                ),
                delivery_factory=factory,
            )
        )

    assert result.state is ThermalAutomaticDriverState.AWAITING_REOBSERVATION
    assert isinstance(delivery.calls[-1], SetPumpSpeed)
    assert delivery.calls[-1].rpm == 2600
    successor = driver.active_session
    assert successor is not None
    assert successor.status is ThermalLiveExecutionStatus.AWAITING_VERIFICATION

    pump_delivery_count = sum(
        isinstance(operation, SetPumpSpeed) and operation.rpm == 2600
        for operation in delivery.calls
    )
    for seconds in (143, 163, 183, 203, 223):
        pending = asyncio.run(
            driver.process_epoch(
                _frame(
                    orchestrator,
                    NOW + timedelta(seconds=seconds),
                    pool_active=True,
                    pump_rpm=1500,
                    configured_rpm=1500,
                    pool_heater="00000",
                    solar_active=False,
                    pool_temperature=81.0,
                    solar_temperature=94.0,
                    mode=ThermalRequestedMode.SOLAR,
                    evaluator=evaluator,
                    driver=driver,
                    verification_timeout=timedelta(seconds=300),
                ),
                delivery_factory=factory,
            )
        )
        assert pending.state is ThermalAutomaticDriverState.AWAITING_VERIFICATION
        assert sum(
            isinstance(operation, SetPumpSpeed) and operation.rpm == 2600
            for operation in delivery.calls
        ) == pump_delivery_count

    source_epoch_at = NOW + timedelta(seconds=244)
    source_epoch = _frame(
        orchestrator,
        source_epoch_at,
        pool_active=True,
        pump_rpm=2600,
        configured_rpm=2600,
        pool_heater="00000",
        solar_active=False,
        pool_temperature=81.0,
        solar_temperature=94.0,
        mode=ThermalRequestedMode.SOLAR,
        evaluator=evaluator,
        driver=driver,
        verification_timeout=timedelta(seconds=300),
    )
    assert source_epoch.thermal is not None
    currentness = source_epoch.thermal.pool.execution_currentness
    compatibility = assess_execution_compatibility(
        successor.originating_currentness,
        currentness,
        progress=successor.execution_progress,
    )
    assert compatibility.continuation_allowed, compatibility
    assert source_epoch.thermal.pool.plan.desired.evaluated_at == source_epoch_at
    before = len(delivery.calls)

    source_requested = asyncio.run(
        driver.process_epoch(source_epoch, delivery_factory=factory)
    )

    assert source_requested.state is ThermalAutomaticDriverState.AWAITING_REOBSERVATION, (
        source_requested.state,
        source_requested.blocker,
        source_requested.last_failure_reason,
        source_requested.runtime_ownership_status,
    )
    assert len(delivery.calls) == before + 1
    assert isinstance(delivery.calls[-1], SetHeatMode)
    assert delivery.calls[-1].mode is PhysicalHeatMode.SOLAR

    source_delivery_count = sum(
        isinstance(operation, SetHeatMode)
        and operation.mode is PhysicalHeatMode.SOLAR
        for operation in delivery.calls
    )
    for seconds in (264, 284):
        pending = asyncio.run(
            driver.process_epoch(
                _frame(
                    orchestrator,
                    NOW + timedelta(seconds=seconds),
                    pool_active=True,
                    pump_rpm=2600,
                    configured_rpm=2600,
                    pool_heater="00000",
                    solar_active=False,
                    pool_temperature=81.0,
                    solar_temperature=94.0,
                    mode=ThermalRequestedMode.SOLAR,
                    evaluator=evaluator,
                    driver=driver,
                    verification_timeout=timedelta(seconds=300),
                ),
                delivery_factory=factory,
            )
        )
        assert pending.state is ThermalAutomaticDriverState.AWAITING_VERIFICATION
        assert sum(
            isinstance(operation, SetHeatMode)
            and operation.mode is PhysicalHeatMode.SOLAR
            for operation in delivery.calls
        ) == source_delivery_count

    physical = {
        "pool_active": True,
        "pump_rpm": 2600,
        "configured_rpm": 2600,
        "pool_heater": "H0002",
        "solar_active": True,
    }
    stable = False
    stable_lease_id = None
    stable_generation = None
    for seconds in range(285, 371):
        before = len(delivery.calls)
        frame = _frame(
            orchestrator,
            NOW + timedelta(seconds=seconds),
            pool_temperature=81.0,
            solar_temperature=94.0,
            mode=ThermalRequestedMode.SOLAR,
            evaluator=evaluator,
            driver=driver,
            verification_timeout=timedelta(seconds=300),
            **physical,
        )
        result = asyncio.run(
            driver.process_epoch(frame, delivery_factory=factory)
        )
        for operation in delivery.calls[before:]:
            if isinstance(operation, SetPumpSpeed):
                physical["pump_rpm"] = operation.rpm
                physical["configured_rpm"] = operation.rpm
            elif isinstance(operation, SetHeatMode):
                physical["pool_heater"] = (
                    "H0002"
                    if operation.mode is PhysicalHeatMode.SOLAR
                    else "00000"
                )
                physical["solar_active"] = (
                    operation.mode is PhysicalHeatMode.SOLAR
                )
        lease = orchestrator.ownership.state.lease
        if (
            lease is not None
            and lease.owns_body_activation
            and lease.owns_pump_setpoint
            and lease.owns_heat_source
            and physical["pump_rpm"] == 2900
            and all(
                lease.domain_state(domain).authority
                is OwnershipAuthority.POOLOS
                for domain in OwnershipDomain
            )
            and all(
                lease.domain_state(domain).health is OwnershipHealth.STABLE
                for domain in OwnershipDomain
            )
        ):
            stable = True
            stable_lease_id = lease.lease_id
            stable_generation = lease.generation
            break

    assert stable, (result.state, result.blocker, physical)
    assert physical == {
        "pool_active": True,
        "pump_rpm": 2900,
        "configured_rpm": 2900,
        "pool_heater": "H0002",
        "solar_active": True,
    }
    assert sum(
        isinstance(operation, SetHeatMode) for operation in delivery.calls
    ) == 1
    assert stable_lease_id is not None
    assert stable_generation is not None
    assert result.state in {
        ThermalAutomaticDriverState.CONVERGED,
        ThermalAutomaticDriverState.OBSERVING_SOLAR_ENGAGEMENT,
    }


def test_restart_active_solar_wrong_pump_establishes_only_pump_provenance() -> None:
    """A fresh accepted correction may prospectively acquire PUMP only."""

    orchestrator = ThermalRuntimeOrchestrator()
    driver = ThermalAutomaticExecutionDriver(orchestrator)
    delivery = FakeDelivery()
    factory = FakeDeliveryFactory(delivery, driver=driver)
    evaluator = ThermalRuntimeEvaluator()
    driver.set_enabled(True, changed_at=NOW, current_epoch_identity=None)

    requested = asyncio.run(
        driver.process_epoch(
            _frame(
                orchestrator,
                NOW + timedelta(seconds=1),
                pool_active=True,
                pump_rpm=2600,
                configured_rpm=2600,
                pool_heater="H0002",
                solar_active=True,
                pool_temperature=81.0,
                pool_target=90.0,
                solar_temperature=110.0,
                mode=ThermalRequestedMode.SOLAR,
                filtration_remaining=timedelta(0),
                filtration_disposition=FiltrationDisposition.SATISFIED,
                evaluator=evaluator,
                driver=driver,
            ),
            delivery_factory=factory,
        )
    )

    assert requested.state is ThermalAutomaticDriverState.AWAITING_REOBSERVATION
    assert len(delivery.calls) == 1
    assert isinstance(delivery.calls[0], SetPumpSpeed)
    assert delivery.calls[0].rpm == 2900
    lease = orchestrator.ownership.state.lease
    assert lease is not None
    assert lease.owns_body_activation is False
    assert lease.owns_pump_setpoint is True
    assert lease.owns_heat_source is False

    repeated = asyncio.run(
        driver.process_epoch(
            _frame(
                orchestrator,
                NOW + timedelta(seconds=2),
                pool_active=True,
                pump_rpm=2600,
                configured_rpm=2600,
                pool_heater="H0002",
                solar_active=True,
                pool_temperature=81.0,
                pool_target=90.0,
                solar_temperature=110.0,
                mode=ThermalRequestedMode.SOLAR,
                filtration_remaining=timedelta(0),
                filtration_disposition=FiltrationDisposition.SATISFIED,
                evaluator=evaluator,
                driver=driver,
            ),
            delivery_factory=factory,
        )
    )
    assert repeated.state is ThermalAutomaticDriverState.AWAITING_VERIFICATION
    assert len(delivery.calls) == 1

    verified = asyncio.run(
        driver.process_epoch(
            _frame(
                orchestrator,
                NOW + timedelta(seconds=3),
                pool_active=True,
                pump_rpm=2900,
                configured_rpm=2900,
                pool_heater="H0002",
                solar_active=True,
                pool_temperature=81.0,
                pool_target=90.0,
                solar_temperature=110.0,
                mode=ThermalRequestedMode.SOLAR,
                filtration_remaining=timedelta(0),
                filtration_disposition=FiltrationDisposition.SATISFIED,
                evaluator=evaluator,
                driver=driver,
            ),
            delivery_factory=factory,
        )
    )
    assert verified.state is ThermalAutomaticDriverState.CONVERGED
    assert len(delivery.calls) == 1
    lease = orchestrator.ownership.state.lease
    assert lease is not None
    assert lease.owns_body_activation is False
    assert lease.owns_pump_setpoint is True
    assert lease.owns_heat_source is False
    assert lease.domain_state(OwnershipDomain.PUMP).authority is OwnershipAuthority.POOLOS
    assert lease.domain_state(OwnershipDomain.PUMP).health is OwnershipHealth.STABLE


def test_restart_active_solar_matching_pump_prospectively_adopts_fresh_domains() -> None:
    """Scenario 53: fresh current Solar policy may adopt converged live domains."""

    orchestrator = ThermalRuntimeOrchestrator()
    driver = ThermalAutomaticExecutionDriver(orchestrator)
    delivery = FakeDelivery()
    factory = FakeDeliveryFactory(delivery, driver=driver)
    evaluator = ThermalRuntimeEvaluator()
    driver.set_enabled(True, changed_at=NOW, current_epoch_identity=None)

    result = asyncio.run(
        driver.process_epoch(
            _frame(
                orchestrator,
                NOW + timedelta(seconds=1),
                pool_active=True,
                pump_rpm=2900,
                configured_rpm=2900,
                pool_heater="H0002",
                solar_active=True,
                pool_temperature=81.0,
                pool_target=90.0,
                solar_temperature=110.0,
                mode=ThermalRequestedMode.SOLAR,
                filtration_remaining=timedelta(0),
                filtration_disposition=FiltrationDisposition.SATISFIED,
                evaluator=evaluator,
                driver=driver,
                pool_opportunity_id="pool:thermal:restart-solar",
            ),
            delivery_factory=factory,
        )
    )

    assert result.state is ThermalAutomaticDriverState.CONVERGED
    assert result.command_delivery_performed is False
    assert delivery.calls == []
    lease = orchestrator.ownership.state.lease
    assert lease is not None
    assert lease.owns_body_adoption
    assert lease.owns_pump_setpoint
    assert lease.owns_heat_source
    assert lease.body_activation is None
    assert lease.pump_setpoint is None
    assert lease.heat_source is None
    assert lease.body_adoption is not None
    assert lease.body_adoption.opportunity_id == "pool:thermal:restart-solar"
    assert lease.pump_adoption is not None
    assert lease.pump_adoption.intended_value == 2900
    assert lease.heat_source_adoption is not None
    assert lease.heat_source_adoption.intended_value is PhysicalHeatMode.SOLAR
    assert result.runtime_ownership_summary["owns_body"] is True
    assert result.runtime_ownership_summary["owns_pump_setpoint"] is True
    assert result.runtime_ownership_summary["owns_heat_source"] is True




def test_adopted_converged_solar_supersession_retains_pool_cleanup_authority() -> None:
    """Commissioning regression: adopted Solar must still unwind Pool circulation."""

    orchestrator = ThermalRuntimeOrchestrator()
    driver = ThermalAutomaticExecutionDriver(orchestrator)
    delivery = FakeDelivery()
    factory = FakeDeliveryFactory(delivery, driver=driver)
    evaluator = ThermalRuntimeEvaluator()
    driver.set_enabled(True, changed_at=NOW, current_epoch_identity=None)

    active = _frame(
        orchestrator,
        NOW + timedelta(seconds=1),
        pool_active=True,
        pump_rpm=2900,
        configured_rpm=2900,
        pool_heater="H0002",
        solar_active=True,
        pool_temperature=83.0,
        pool_target=90.0,
        solar_temperature=119.0,
        mode=ThermalRequestedMode.SOLAR,
        filtration_remaining=timedelta(hours=5),
        filtration_disposition=FiltrationDisposition.CREDITING,
        filtration_independent_disposition=FiltrationDisposition.DEFERRED_OPTIMIZATION,
        evaluator=evaluator,
        driver=driver,
        pool_opportunity_id="pool:thermal:commissioning",
    )
    asyncio.run(driver.process_epoch(active, delivery_factory=factory))
    lease = orchestrator.ownership.state.lease
    assert lease is not None
    assert lease.owns_body_adoption
    assert lease.pump_adoption is not None
    assert lease.heat_source_adoption is not None
    assert delivery.calls == []

    ending = _frame(
        orchestrator,
        NOW + timedelta(seconds=2),
        pool_active=True,
        pump_rpm=2900,
        configured_rpm=2900,
        pool_heater="00000",
        solar_active=False,
        pool_temperature=83.0,
        pool_target=80.0,
        solar_temperature=108.0,
        mode=ThermalRequestedMode.SOLAR,
        filtration_remaining=timedelta(hours=5),
        filtration_disposition=FiltrationDisposition.CREDITING,
        filtration_independent_disposition=FiltrationDisposition.DEFERRED_OPTIMIZATION,
        evaluator=evaluator,
        driver=driver,
        pool_opportunity_id=None,
    )
    asyncio.run(driver.process_epoch(ending, delivery_factory=factory))

    residual = orchestrator.ownership.residual_termination
    if residual is not None:
        assert residual.body_adoption == lease.body_adoption
    if driver.cleanup_provenance is not None:
        assert driver.cleanup_provenance.body_adoption == lease.body_adoption

    # The adopted BODY origin must never disappear merely because the Solar
    # purpose ended. It must survive into either residual or cleanup provenance
    # until exact monotonic cleanup completes.
    assert (
        orchestrator.ownership.residual_termination is not None
        or driver.cleanup_provenance is not None
        or any(
            isinstance(operation, SetBodyActive) and operation.active is False
            for operation in delivery.calls
        )
    )

def test_restart_pump_only_provenance_never_grants_body_shutdown_authority() -> None:
    """A prospectively acquired pump receipt cannot widen to BODY cleanup."""

    orchestrator = ThermalRuntimeOrchestrator()
    driver = ThermalAutomaticExecutionDriver(orchestrator)
    delivery = FakeDelivery()
    factory = FakeDeliveryFactory(delivery, driver=driver)
    evaluator = ThermalRuntimeEvaluator()
    driver.set_enabled(True, changed_at=NOW, current_epoch_identity=None)

    common = {
        "pool_active": True,
        "pool_heater": "H0002",
        "solar_active": True,
        "pool_temperature": 81.0,
        "pool_target": 90.0,
        "solar_temperature": 110.0,
        "mode": ThermalRequestedMode.SOLAR,
        "filtration_remaining": timedelta(0),
        "filtration_disposition": FiltrationDisposition.SATISFIED,
        "evaluator": evaluator,
        "driver": driver,
    }
    asyncio.run(
        driver.process_epoch(
            _frame(
                orchestrator,
                NOW + timedelta(seconds=1),
                pump_rpm=2600,
                configured_rpm=2600,
                **common,
            ),
            delivery_factory=factory,
        )
    )
    asyncio.run(
        driver.process_epoch(
            _frame(
                orchestrator,
                NOW + timedelta(seconds=2),
                pump_rpm=2900,
                configured_rpm=2900,
                **common,
            ),
            delivery_factory=factory,
        )
    )
    lease = orchestrator.ownership.state.lease
    assert lease is not None and lease.owns_pump_setpoint
    assert not lease.owns_body_activation
    calls_before_completion = len(delivery.calls)

    ended = asyncio.run(
        driver.process_epoch(
            _frame(
                orchestrator,
                NOW + timedelta(seconds=3),
                pool_active=True,
                pump_rpm=2900,
                configured_rpm=2900,
                pool_heater="00000",
                solar_active=False,
                pool_temperature=91.0,
                pool_target=90.0,
                solar_temperature=110.0,
                mode=ThermalRequestedMode.SOLAR,
                filtration_remaining=timedelta(0),
                filtration_disposition=FiltrationDisposition.SATISFIED,
                evaluator=evaluator,
                driver=driver,
            ),
            delivery_factory=factory,
        )
    )

    assert ended.command_delivery_performed is False
    assert len(delivery.calls) == calls_before_completion
    assert not any(
        isinstance(operation, SetBodyActive) and operation.active is False
        for operation in delivery.calls
    )
    assert driver.cleanup_provenance is not None
    assert driver.cleanup_provenance.body_activation is None
    released = asyncio.run(
        driver.process_epoch(
            _frame(
                orchestrator,
                NOW + timedelta(seconds=4),
                pool_active=True,
                pump_rpm=2900,
                configured_rpm=2900,
                pool_heater="00000",
                solar_active=False,
                pool_temperature=91.0,
                pool_target=90.0,
                solar_temperature=110.0,
                mode=ThermalRequestedMode.SOLAR,
                filtration_remaining=timedelta(0),
                filtration_disposition=FiltrationDisposition.SATISFIED,
                evaluator=evaluator,
                driver=driver,
            ),
            delivery_factory=factory,
        )
    )
    assert released.blocker == "thermal_cleanup_pump_provenance_relinquished"
    assert driver.cleanup_provenance is None
    assert len(delivery.calls) == calls_before_completion


@pytest.mark.parametrize(
    ("pool_active", "pump_rpm", "pool_heater", "solar_active", "mode"),
    (
        (True, 2900, "H0002", True, ThermalRequestedMode.SOLAR),
        (True, 2900, "00000", False, ThermalRequestedMode.SOLAR),
        (False, 0, "00000", False, ThermalRequestedMode.OFF),
    ),
)
def test_restart_during_cleanup_replays_nothing_and_reconstructs_no_authority(
    pool_active: bool,
    pump_rpm: int,
    pool_heater: str,
    solar_active: bool,
    mode: ThermalRequestedMode,
) -> None:
    """Volatile cleanup receipts do not survive restart as command authority."""

    orchestrator = ThermalRuntimeOrchestrator()
    driver = ThermalAutomaticExecutionDriver(orchestrator)
    delivery = FakeDelivery()
    factory = FakeDeliveryFactory(delivery, driver=driver)
    evaluator = ThermalRuntimeEvaluator()
    driver.set_enabled(True, changed_at=NOW, current_epoch_identity=None)

    for seconds in (1, 2):
        result = asyncio.run(
            driver.process_epoch(
                _frame(
                    orchestrator,
                    NOW + timedelta(seconds=seconds),
                    pool_active=pool_active,
                    pump_rpm=pump_rpm,
                    configured_rpm=2900,
                    pool_heater=pool_heater,
                    solar_active=solar_active,
                    pool_temperature=100.0,
                    pool_target=90.0,
                    solar_temperature=110.0,
                    mode=mode,
                    filtration_remaining=timedelta(0),
                    filtration_disposition=FiltrationDisposition.SATISFIED,
                    evaluator=evaluator,
                    driver=driver,
                ),
                delivery_factory=factory,
            )
        )
        assert result.command_delivery_performed is False
        assert delivery.calls == []
        assert orchestrator.ownership.state.lease is None
        assert orchestrator.ownership.residual_termination is None
        assert driver.cleanup_provenance is None


def test_target_down_shutdown_then_target_up_reacquires_fresh_solar_generation() -> None:
    """One driver can retire Solar completely and later acquire it again."""

    orchestrator = ThermalRuntimeOrchestrator()
    driver = ThermalAutomaticExecutionDriver(orchestrator)
    delivery = FakeDelivery()
    factory = FakeDeliveryFactory(delivery, driver=driver)
    evaluator = ThermalRuntimeEvaluator()
    physical = {
        "pool_active": False,
        "pump_rpm": 0,
        "configured_rpm": 2600,
        "pool_heater": "00000",
        "solar_active": False,
    }
    baseline = _frame(
        orchestrator,
        NOW,
        pool_temperature=81.0,
        pool_target=90.0,
        solar_temperature=110.0,
        mode=ThermalRequestedMode.SOLAR,
        evaluator=evaluator,
        driver=driver,
        filtration_remaining=timedelta(0),
        filtration_disposition=FiltrationDisposition.SATISFIED,
        **physical,
    )
    driver.note_disabled_epoch(baseline)
    driver.set_enabled(
        True,
        changed_at=NOW,
        current_epoch_identity=baseline.epoch_identity,
    )

    phase = "first_solar"
    target = 90.0
    first_lease_id = None
    first_generation = None
    shutdown_command_count = None
    second_generation = None
    native_refresh_at = NOW
    native_transition_pending = False
    for seconds in range(1, 1201):
        at = NOW + timedelta(seconds=seconds)
        if native_transition_pending:
            # Accepted commands are followed by a distinct authoritative
            # IntelliCenter consequence observation. Strict post-delivery
            # chronology requires this epoch to be later than acceptance.
            native_refresh_at = at
            native_transition_pending = False
        special_purpose = driver.active_pump_session_purpose()
        probe = driver.probe_execution_evidence()
        refresh_owned_session = bool(
            special_purpose is PumpSpeedSessionPurpose.PRIMING
            or (
                probe is not None
                and probe.phase.value == "acquiring"
            )
        )
        if refresh_owned_session:
            if (at - native_refresh_at).total_seconds() >= 15:
                # The production GetParamList refresh updates selected native
                # model objects and then republishes one new authoritative
                # transport snapshot. Canonical observations derived from that
                # snapshot therefore share the refreshed observation epoch.
                native_refresh_at = at
        else:
            # Outside an owned priming/probe hold, normal native traffic
            # republishes the authoritative snapshot as seen on live hardware.
            native_refresh_at = at
        before = len(delivery.calls)
        frame = _frame(
            orchestrator,
            at,
            pool_temperature=81.0,
            pool_target=target,
            solar_temperature=110.0,
            mode=ThermalRequestedMode.SOLAR,
            evaluator=evaluator,
            driver=driver,
            filtration_remaining=timedelta(0),
            filtration_disposition=FiltrationDisposition.SATISFIED,
            native_observation_at=native_refresh_at,
            **physical,
        )
        result = asyncio.run(
            driver.process_epoch(frame, delivery_factory=factory)
        )
        if delivery.calls[before:]:
            native_transition_pending = True
        for operation in delivery.calls[before:]:
            if isinstance(operation, SetBodyActive):
                physical["pool_active"] = operation.active
                if not operation.active:
                    physical["pump_rpm"] = 0
                    physical["solar_active"] = False
            elif isinstance(operation, SetPumpSpeed):
                physical["pump_rpm"] = operation.rpm
                physical["configured_rpm"] = operation.rpm
            elif isinstance(operation, SetHeatMode):
                physical["pool_heater"] = (
                    "H0002"
                    if operation.mode is PhysicalHeatMode.SOLAR
                    else "00000"
                )
                physical["solar_active"] = (
                    operation.mode is PhysicalHeatMode.SOLAR
                )

        lease = orchestrator.ownership.state.lease
        all_poolos = bool(
            lease is not None
            and all(
                lease.domain_state(domain).authority
                is OwnershipAuthority.POOLOS
                for domain in OwnershipDomain
            )
            and all(
                lease.domain_state(domain).health is OwnershipHealth.STABLE
                for domain in OwnershipDomain
            )
        )
        if (
            phase == "first_solar"
            and all_poolos
            and physical["solar_active"]
            and physical["pump_rpm"] == 2900
        ):
            assert lease is not None
            first_lease_id = lease.lease_id
            first_generation = lease.generation
            target = 80.0
            phase = "shutdown"
        elif (
            phase == "shutdown"
            and not physical["pool_active"]
            and physical["pump_rpm"] == 0
            and physical["pool_heater"] == "00000"
            and orchestrator.ownership.residual_termination is None
            and driver.cleanup_provenance is None
        ):
            shutdown_command_count = len(delivery.calls)
            target = 90.0
            phase = "second_solar"
        elif (
            phase == "second_solar"
            and all_poolos
            and physical["solar_active"]
            and physical["pump_rpm"] == 2900
        ):
            assert lease is not None
            second_generation = lease.generation
            assert lease.lease_id != first_lease_id
            break

    final_diagnostics = dict(driver.diagnostics())
    ownership_summary = final_diagnostics["runtime_ownership_summary"]
    assert isinstance(ownership_summary, dict)
    terminal_debug = (
        result.state.value,
        result.blocker,
        ownership_summary["reason_code"],
        ownership_summary["terminal_transition_reason_code"],
        ownership_summary["terminal_transition_affected_concept"],
        ownership_summary["terminal_transition_expected_value"],
        ownership_summary["terminal_transition_observed_value"],
        ownership_summary["failed_pool_opportunity_id"],
        ownership_summary["pool_opportunity_id"],
        ownership_summary["accepted_consequence_pending_role"],
        ownership_summary["accepted_consequence_pending_value"],
        physical["pool_active"],
        physical["pump_rpm"],
        physical["configured_rpm"],
        physical["pool_heater"],
        physical["solar_active"],
    )
    assert phase == "second_solar", terminal_debug
    assert first_generation is not None
    assert shutdown_command_count is not None
    assert second_generation is not None and second_generation > first_generation, terminal_debug
    assert len(delivery.calls) > shutdown_command_count
    assert physical == {
        "pool_active": True,
        "pump_rpm": 2900,
        "configured_rpm": 2900,
        "pool_heater": "H0002",
        "solar_active": True,
    }
