"""Combined operator intent and native consequences on one adopted Spa body."""

import asyncio
from dataclasses import replace
from datetime import timedelta

import pytest

from test_thermal_automatic_execution import NOW, FakeDelivery, FakeDeliveryFactory, _frame
from test_thermal_runtime_ownership import external_event
from poolos.external_change import ExternalChangeBatch
from poolos.integration import PhysicalHeatMode, SetBodyActive, SetHeatMode, SetPumpSpeed, ThermalBody
from poolos.ownership_evidence import OwnershipAuthority, OwnershipDomain, PositiveOperatorEvidence
from poolos.thermal_automatic_execution import (
    ThermalAutomaticDriverState,
    ThermalAutomaticExecutionDriver,
)
from poolos.thermal_runtime_assessment import ThermalRuntimeEvaluator, ThermalRequestedMode
from poolos.thermal_runtime_orchestration import ThermalRuntimeOrchestrator


@pytest.mark.parametrize("source_return", ["H0002", "HXSLR"])
@pytest.mark.parametrize("pump_outcome", ["converges", "timeout", "new_operator"])
@pytest.mark.parametrize("engagement_delay", [0, 5])
def test_spa_pump_and_thermal_handback_preserve_continuous_body(source_return, pump_outcome, engagement_delay):
    async def run():
        orchestrator = ThermalRuntimeOrchestrator()
        driver = ThermalAutomaticExecutionDriver(orchestrator)
        evaluator = ThermalRuntimeEvaluator()
        class TimedDelivery(FakeDelivery):
            async def deliver(self, operation, *, correlation_id):
                receipt = await super().deliver(operation, correlation_id=correlation_id)
                return replace(receipt, issued_at=at, acknowledged_at=at)

        delivery = TimedDelivery()
        factory = FakeDeliveryFactory(delivery, driver=driver)
        rpm, configured, source, solar, gas = 2600, 2600, "00000", False, False
        at = NOW
        active = False
        selected_at = None
        batch = ExternalChangeBatch(())

        def frame():
            return _frame(
                orchestrator, at, pool_active=False, spa_active=active,
                body=ThermalBody.HOT_TUB, pump_rpm=rpm, configured_rpm=configured,
                spa_pump_circuit_id="p0102", spa_heater=source,
                solar_active=solar, heater_active=gas,
                spa_heating_demand_active=active, spa_temperature=80, spa_target=97,
                solar_temperature=140, mode=ThermalRequestedMode.SOLAR_PREFERRED,
                driver=driver, evaluator=evaluator, external_changes=batch,
            )

        baseline = frame()
        driver.note_disabled_epoch(baseline)
        driver.set_enabled(True, changed_at=NOW, current_epoch_identity=baseline.epoch_identity)
        active = True

        async def epoch(second):
            nonlocal at, rpm, configured, source, solar, gas, selected_at
            at = NOW + timedelta(seconds=second)
            if source == "H0002" and selected_at is not None and second >= selected_at + engagement_delay:
                solar = True
            before = len(delivery.calls)
            current_frame = frame()
            result = await driver.process_epoch(current_frame, delivery_factory=factory)
            for operation in delivery.calls[before:]:
                assert not isinstance(operation, SetBodyActive), (operation, result)
                if isinstance(operation, SetPumpSpeed):
                    rpm = configured = operation.rpm
                elif isinstance(operation, SetHeatMode):
                    assert operation.mode is not PhysicalHeatMode.GAS
                    source = "H0002" if operation.mode is PhysicalHeatMode.SOLAR else "00000"
                    selected_at = second if source == "H0002" else None
                    solar, gas = source == "H0002" and engagement_delay == 0, False
            return result

        for second in range(1, 160):
            await epoch(second)
        origin = orchestrator.ownership.state.lease
        assert driver.active_session is None or driver.active_session.status.value != "awaiting_verification", driver.active_session
        assert source == "H0002" and rpm == 2900
        assert all(origin.domain_state(d).authority is OwnershipAuthority.POOLOS for d in OwnershipDomain)

        def intent(second, domain, concept, old, new):
            nonlocal batch
            when = NOW + timedelta(seconds=second)
            current = orchestrator.ownership.state.lease
            event = replace(
                external_event(concept, old, new, observed_at=when),
                positive_operator_evidence=PositiveOperatorEvidence(
                    f"intent-{second}", current.body_session_generation,
                    current.body_session_id, domain,
                    "pump.rpm" if domain is OwnershipDomain.PUMP else "spa.raw_heater_id",
                    when,
                ),
            )
            batch = ExternalChangeBatch((event,))
            # The native boundary consumes configured domain intent before
            # purpose evaluation sees its physical consequences.
            orchestrator.ownership.record_operator_events(batch, evaluated_at=when)

        def owners(pump, thermal):
            lease = orchestrator.ownership.state.lease
            assert lease.body_session_id == origin.body_session_id
            assert lease.domain_state(OwnershipDomain.BODY).authority is OwnershipAuthority.POOLOS
            assert lease.domain_state(OwnershipDomain.PUMP).authority is pump
            assert lease.domain_state(OwnershipDomain.THERMAL).authority is thermal, (at, source, driver.assessment.blocker)
            assert lease.status.value == "owned", (at, lease.reason_code, driver.assessment.blocker)
            assert not driver._reenable_required

        configured = 3200
        intent(160, OwnershipDomain.PUMP, "spa.pump_circuit.configured_speed_rpm", 2900, 3200)
        for second, actual in ((160, 0), (161, 3450), (162, 3200), (163, 2900)):
            rpm = actual
            before = len(delivery.calls)
            await epoch(second)
            owners(OwnershipAuthority.OPERATOR, OwnershipAuthority.POOLOS)
            assert len(delivery.calls) == before
        # The motor's coincidental 2900 at 163 was not configured hand-back.
        configured = 2900
        intent(164, OwnershipDomain.PUMP, "spa.pump_circuit.configured_speed_rpm", 3200, 2900)
        if pump_outcome != "converges":
            before = len(delivery.calls)
            deadline = None
            for second in range(164, 285):
                rpm = 0
                await epoch(second)
                owners(OwnershipAuthority.POOLOS, OwnershipAuthority.POOLOS)
                pump = orchestrator.ownership.state.lease.domain_state(OwnershipDomain.PUMP)
                if deadline is None:
                    deadline = pump.episode.deadline
                assert pump.episode.deadline == deadline
                assert len(delivery.calls) == before
                if pump_outcome == "new_operator":
                    configured = 3300
                    intent(second + 1, OwnershipDomain.PUMP, "spa.pump_circuit.configured_speed_rpm", 2900, 3300)
                    owners(OwnershipAuthority.OPERATOR, OwnershipAuthority.POOLOS)
                    return
            assert pump.health.value == "faulted"
            assert pump.command_blocker == "ownership_reconciliation_deadline_exhausted"
            return
        for second, actual in ((164, 0), (165, 3450), (166, 2900), (167, 2900)):
            rpm = actual
            before = len(delivery.calls)
            await epoch(second)
            owners(OwnershipAuthority.POOLOS, OwnershipAuthority.POOLOS)
            assert len(delivery.calls) == before
        source, solar, gas = "H0001", False, True
        intent(168, OwnershipDomain.THERMAL, "spa.raw_heater_id", "H0002", "H0001")
        for second in (168, 169, 170):
            await epoch(second)
            owners(OwnershipAuthority.POOLOS, OwnershipAuthority.OPERATOR)
            assert source == "H0001" and gas
        source, solar, gas = source_return, False, False
        selected_at = 171 if source_return == "H0002" else None
        intent(171, OwnershipDomain.THERMAL, "spa.raw_heater_id", "H0001", source_return)
        transitions = []
        converged_reacquisition_seen = False
        for second in range(171, 330):
            result = await epoch(second)
            lease = orchestrator.ownership.state.lease
            thermal_authority = lease.domain_state(OwnershipDomain.THERMAL).authority
            transitions.append(
                (
                    second,
                    driver.assessment.blocker,
                    lease.reason_code,
                    result.state.value,
                    source,
                    solar,
                    rpm,
                    thermal_authority.value,
                )
            )
            assert lease.body_session_id == origin.body_session_id, transitions
            assert thermal_authority is not OwnershipAuthority.OPERATOR
            if (
                source == "H0002"
                and solar
                and rpm == 2900
                and result.state is ThermalAutomaticDriverState.CONVERGED
            ):
                # Physical convergence is not enough by itself to manufacture
                # authority. But by the time automatic execution declares this
                # HXSLR policy hand-back CONVERGED, PoolOS must already have
                # accepted/verified its own Solar-source successor and restored
                # THERMAL authority. This is the Sep 27 physical regression:
                # H0002/2900/CONVERGED while THERMAL remained NONE/PENDING.
                assert thermal_authority is OwnershipAuthority.POOLOS, transitions
                assert lease.owns_heat_source, transitions
                converged_reacquisition_seen = True
                break
        assert converged_reacquisition_seen, transitions[-40:]
        owners(OwnershipAuthority.POOLOS, OwnershipAuthority.POOLOS)
        assert source == "H0002" and solar and rpm == 2900 and not gas

    asyncio.run(run())
