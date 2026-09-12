"""Production composition attacks found during the independent release review."""

import asyncio
from dataclasses import replace
from datetime import datetime, timedelta

import pytest

import test_thermal_automatic_execution as thermal
from test_external_change import process, authority as enabled_authority
from test_home_assistant_native_pump_rpm_behavior import _gateway, manual_module
from poolos.external_change import ExternalNativeChangeMonitor, ThermalRuntimeExternalChangeEvidence
from poolos.physical_command_authority import (
    AutomaticThermalDispatchPurpose, PhysicalRequestSource,
    ExpectedNativeConsequence, PhysicalCommandRequest,
)
import test_filtration_automatic_execution as filtration


@pytest.mark.parametrize("order", ["together", "actual_first", "configured_first", "jitter"])
def test_native_cleanup_rpm_consequence_preserves_filtration_handoff(
    monkeypatch, pump_object_factory, pump_circuit_object_factory, order,
):
    orchestrator, driver, factory, _, _ = thermal._driver_awaiting_source_off_verification()
    gateway, recorder = _gateway([
        pump_object_factory(objnam="PMP01"),
        pump_circuit_object_factory(objnam="p0102", pump_id="PMP01", circuit_id="C0006", rpm_setpoint=3000),
    ])
    authority = gateway._command_authority
    authority.configure_automatic_thermal(
        driver_enabled=True, thermal_live_enabled=True, commissioning_scope="pool",
    )
    monitor = ExternalNativeChangeMonitor(authority)
    retained = ThermalRuntimeExternalChangeEvidence()
    at = thermal.NOW

    class Clock(datetime):
        @classmethod
        def now(cls, tz=None):
            return at

    monkeypatch.setattr(manual_module, "datetime", Clock)
    original_deliver = factory.delivery.deliver

    async def deliver(operation, *, correlation_id):
        # Exercise the real central gateway, with only its physical client faked.
        if isinstance(operation, thermal.SetPumpSpeed):
            candidate = driver._last_epoch_identity
            authority.begin_automatic_thermal_epoch(candidate)
            purpose = AutomaticThermalDispatchPurpose.CIRCULATION_PUMP_NORMALIZATION
            authority.register_automatic_thermal_cleanup(
                epoch_identity=candidate, candidate_identity=operation.operation_id,
                body="pool", purpose=purpose, operation="pump_circuit_speed",
                target=operation.equipment_id, requested_value=operation.rpm,
            )
            context = authority.bind_automatic_thermal_dispatch(
                epoch_identity=candidate, session_identity="red-team-cleanup",
                body="pool", pump_circuit_id=operation.equipment_id, purpose=purpose,
                cleanup_candidate_identity=operation.operation_id,
            )
            await gateway.async_set_pump_circuit_speed(
                operation.equipment_id, operation.rpm,
                request_source=PhysicalRequestSource.AUTOMATIC_THERMAL,
                automatic_thermal_context=context,
            )
        return await original_deliver(operation, correlation_id=correlation_id)

    factory.delivery.deliver = deliver
    phases = [(66, 3000, 3000), (67, 3000, 3000)]
    if order == "actual_first":
        phases.append((68, 2600, 3000))
    elif order == "configured_first":
        phases.append((68, 3000, 2600))
    elif order == "jitter":
        phases.extend([(68, 2610, 3000), (68.5, 2600, 3000)])
    phases.append((69, 2600, 2600))
    for seconds, actual, configured in phases:
        at = thermal.NOW + timedelta(seconds=seconds)
        batch = retained.update(process(monitor, at, {
            "pump.rpm": (actual, "PMP01"),
            "pool.pump_circuit.configured_speed_rpm": (configured, "p0102"),
        }))
        frame = thermal._frame(
            orchestrator, at, pool_active=True, pump_rpm=actual,
            configured_rpm=configured, mode=thermal.ThermalRequestedMode.OFF,
            filtration_remaining=timedelta(hours=2), external_changes=batch,
        )
        result = asyncio.run(driver.process_epoch(frame, delivery_factory=factory))
        if seconds == 67:
            assert result.state is thermal.ThermalAutomaticDriverState.AWAITING_CLEANUP_VERIFICATION, result.blocker
        if seconds == 68:
            assert result.state is thermal.ThermalAutomaticDriverState.AWAITING_CLEANUP_VERIFICATION
            assert driver.circulation_ownership.filtration_lease is None
    assert result.blocker == "thermal_cleanup_filtration_handoff_verified"
    assert driver.circulation_ownership.filtration_lease.verified
    assert recorder.calls == [("p0102", {"SPEED": "2600"})]


def test_rejected_thermal_handoff_does_not_reserve_future_filtration_cleanup():
    filtration_driver, delivery, filtration_factory = filtration._verified_filtration_driver(at=thermal.NOW)
    circulation = filtration_driver.ownership
    orchestrator = thermal.ThermalRuntimeOrchestrator()
    driver = thermal.ThermalAutomaticExecutionDriver(orchestrator, circulation_ownership=circulation)
    driver.set_enabled(True, changed_at=thermal.NOW, current_epoch_identity=None)

    class Rejected(thermal.FakeDelivery):
        async def deliver(self, operation, *, correlation_id):
            receipt = await super().deliver(operation, correlation_id=correlation_id)
            return replace(receipt, status=thermal.CommandStatus.REJECTED)

    thermal_delivery = Rejected()
    factory = thermal.FakeDeliveryFactory(thermal_delivery)
    for seconds in (3, 4, 5):
        at = thermal.NOW + timedelta(seconds=seconds)
        frame = thermal._frame(orchestrator, at, pool_active=True, pump_rpm=2600, configured_rpm=2600)
        circulation.begin_epoch(frame.epoch_identity)
        driver.reserve_circulation_candidate(frame)
        result = asyncio.run(driver.process_epoch(frame, delivery_factory=factory))
        if seconds == 3:
            assert driver._reenable_required, result.blocker
            assert circulation.owner is thermal.PoolCirculationOwner.FILTRATION
            continue
        assert result.blocker == "automatic_thermal_reenable_required"
        assert not circulation.thermal_reserved_for(frame.epoch_identity)
        filtration_frame = replace(
            filtration._frame(at, pool=True, rpm=2600, configured=2600, satisfied=True),
            epoch_identity=frame.epoch_identity,
            thermal_candidate_ready=circulation.thermal_reserved_for(frame.epoch_identity),
        )
        asyncio.run(filtration_driver.process_epoch(filtration_frame, delivery_factory=filtration_factory))
    assert isinstance(delivery.operations[-1], thermal.SetBodyActive)
    assert delivery.operations[-1].active is False
    assert len(thermal_delivery.calls) == 1


@pytest.mark.parametrize("retirement", ["contradiction", "supersession", "expiry", "restart"])
def test_repeated_rpm_attribution_retires_without_hiding_new_takeover(retirement):
    authority = enabled_authority()
    request = PhysicalCommandRequest(
        operation="pump_circuit_speed", target="p0102",
        source=PhysicalRequestSource.MANUAL, requested_value=2600,
    )
    token = authority.reserve(request, ExpectedNativeConsequence(
        "pump.rpm", "PMP01", 2600, numeric_tolerance=25,
        retain_matching_updates=True,
    ), now=thermal.NOW)
    assert token is not None

    def correlate(value, seconds):
        return authority.correlate(concept="pump.rpm", native_object_id="PMP01",
                                   value=value, observed_at=thermal.NOW + timedelta(seconds=seconds))

    assert correlate(2600, 1) is None  # A queued request is not dispatched evidence.
    authority.mark_dispatch_started(token)
    assert correlate(2610, 2) is not None
    assert correlate(2600, 3) is not None
    assert authority.correlate(concept="pool.raw_heater_id", native_object_id="B1101",
                               value="H0001", observed_at=thermal.NOW + timedelta(seconds=3)) is None
    if retirement == "contradiction":
        assert correlate(2200, 4) is None
    elif retirement == "supersession":
        successor = replace(request, request_id="new-request", requested_value=2900)
        authority.supersede_dispatched_expectations(successor)
    elif retirement == "expiry":
        authority.expire(now=thermal.NOW + timedelta(seconds=45))
    else:
        authority = enabled_authority()
    assert correlate(2600, 46 if retirement == "expiry" else 5) is None


def test_manual_noop_write_retires_old_automatic_actual_rpm_expectation(
    pump_object_factory, pump_circuit_object_factory,
):
    gateway, recorder = _gateway([
        pump_object_factory(objnam="PMP01"),
        pump_circuit_object_factory(objnam="p0102", pump_id="PMP01",
                                    circuit_id="C0006", rpm_setpoint=3000),
    ])
    authority = gateway._command_authority
    now = datetime.now(thermal.UTC)
    previous = PhysicalCommandRequest(operation="pump_circuit_speed", target="p0102",
        source=PhysicalRequestSource.MANUAL, requested_value=2600)
    token = authority.reserve(previous, ExpectedNativeConsequence(
        "pump.rpm", "PMP01", 2600, numeric_tolerance=25,
        retain_matching_updates=True), now=now)
    authority.mark_dispatch_started(token)
    authority.replace_native_truth({("pool.pump_circuit.configured_speed_rpm", "p0102"): 3000})
    asyncio.run(gateway.async_set_pump_circuit_speed("p0102", 3000))
    assert recorder.calls == [("p0102", {"SPEED": "3000"})]
    assert authority.correlate(concept="pump.rpm", native_object_id="PMP01", value=2600,
                               observed_at=datetime.now(thermal.UTC)) is None


@pytest.mark.parametrize("phase", ["source_off", "pump_cleanup", "body_cleanup"])
def test_timeout_then_late_matching_callback_cannot_create_cleanup_authority(phase):
    orchestrator, driver, factory, _, _ = thermal._driver_awaiting_source_off_verification()
    remaining = timedelta(hours=2) if phase == "pump_cleanup" else timedelta(0)

    def advance(seconds, *, active=True, rpm=3000, heater="00000"):
        frame = thermal._frame(
            orchestrator, thermal.NOW + timedelta(seconds=seconds), pool_active=active,
            pump_rpm=rpm, configured_rpm=rpm, pool_heater=heater,
            mode=thermal.ThermalRequestedMode.OFF, filtration_remaining=remaining,
        )
        return asyncio.run(driver.process_epoch(frame, delivery_factory=factory))

    if phase != "source_off":
        advance(66)
        advance(67)
        assert driver.cleanup_attempt is not None
    calls = len(factory.delivery.calls)
    timed_out = advance(98, heater="H0001" if phase == "source_off" else "00000")
    assert "timed_out" in timed_out.blocker
    for seconds in (99, 100, 101):
        advance(seconds, active=phase != "body_cleanup", rpm=2600 if phase == "pump_cleanup" else 3000)
        assert driver.cleanup_provenance is None
        assert driver.cleanup_attempt is None
        assert driver.termination_attempt is None
        assert driver.circulation_ownership.filtration_lease is None
        assert len(factory.delivery.calls) == calls


@pytest.mark.parametrize("phase", ["source_off", "pump_cleanup", "body_cleanup"])
def test_failed_thermal_reduction_cannot_block_fresh_filtration_forever(phase):
    orchestrator, driver, factory, _, _ = thermal._driver_awaiting_source_off_verification()
    remaining = timedelta(hours=2) if phase == "pump_cleanup" else timedelta(0)
    for seconds in (() if phase == "source_off" else (66, 67)):
        frame = thermal._frame(orchestrator, thermal.NOW + timedelta(seconds=seconds),
            pool_active=True, pump_rpm=3000, configured_rpm=3000,
            mode=thermal.ThermalRequestedMode.OFF, filtration_remaining=remaining)
        asyncio.run(driver.process_epoch(frame, delivery_factory=factory))
    frame = thermal._frame(orchestrator, thermal.NOW + timedelta(seconds=98),
        pool_active=True, pump_rpm=3000, configured_rpm=3000,
        pool_heater="H0001" if phase == "source_off" else "00000",
        mode=thermal.ThermalRequestedMode.OFF, filtration_remaining=remaining)
    result = asyncio.run(driver.process_epoch(frame, delivery_factory=factory))
    assert "timed_out" in result.blocker
    assert orchestrator.ownership.residual_termination is None
    assert driver.cleanup_provenance is None
    filtration_driver = thermal.FiltrationAutomaticExecutionDriver(driver.circulation_ownership)
    filtration_driver.set_enabled(True, changed_at=thermal.NOW, current_epoch_identity=None)
    delivery = filtration._Delivery([])
    # A later fresh Pool-Off baseline permits a new, independently authorized
    # filtration activation. No old thermal provenance may own the registry.
    for seconds in (100, 101):
        at = thermal.NOW + timedelta(seconds=seconds)
        fresh = thermal._frame(orchestrator, at, pool_active=False,
            pump_rpm=0, configured_rpm=2600, mode=thermal.ThermalRequestedMode.OFF)
        driver.circulation_ownership.begin_epoch(fresh.epoch_identity)
        driver.reserve_circulation_candidate(fresh)
        fframe = replace(filtration._frame(at, pool=False, rpm=0, configured=2600),
            epoch_identity=fresh.epoch_identity,
            thermal_owned=driver.circulation_ownership.owner is thermal.PoolCirculationOwner.THERMAL)
        asyncio.run(driver.process_epoch(fresh, delivery_factory=factory))
        asyncio.run(filtration_driver.process_epoch(fframe, delivery_factory=filtration._Factory(delivery)))
    assert len(delivery.operations) == 1
    assert isinstance(delivery.operations[0], thermal.SetBodyActive)
    assert delivery.operations[0].active is True
