"""Original incident controls using the real HA factory and authority evaluator.

Full command-lock and physical gateway coverage lives in the accompanying
test_filtration_gateway_adversarial_acceptance module.
"""

import asyncio
from datetime import timedelta
from dataclasses import replace
from types import SimpleNamespace

import pytest

import test_filtration_automatic_execution as core_tests
import test_home_assistant_filtration_automatic_runtime as runtime_tests
import test_home_assistant_filtration_live_delivery as delivery_tests
from poolos.filtration_automatic_execution import FiltrationAutomaticExecutionDriver
from poolos.integration import SetBodyActive
from poolos.ownership_evidence import OwnershipDomain, OwnershipHealth
from poolos.physical_command_authority import (
    PoolOSPhysicalCommandAuthority,
    PhysicalCommandRequest,
    PhysicalCommandDeniedError,
)
from poolos.external_change import ExternalChangeBatch
from poolos.pool_circulation_ownership import PoolCirculationOwnershipRegistry


def setup(fail_pump, *, actual_accounting=False):
    runtime = runtime_tests._load_module()
    adapter = delivery_tests._load_module()
    runtime.ManualIntelliCenterFiltrationDelivery = adapter.ManualIntelliCenterFiltrationDelivery
    authority = PoolOSPhysicalCommandAuthority()
    authority.resolve_maintenance(False)
    authority.set_controller_mode("auto")
    authority.configure_automatic_filtration(enabled=True)
    registry = PoolCirculationOwnershipRegistry()
    calls = []
    ledger = core_tests.FiltrationAccountingTracker(tou_profile=core_tests.LADWP_INITIAL_PROFILE)

    class Manual:
        available = True

        async def async_set_body_active(self, target, value, **kwargs):
            authority.require_allowed(
                PhysicalCommandRequest(
                    operation="body_active",
                    target=target,
                    source=kwargs["request_source"],
                    requested_value=value,
                    automatic_filtration_context=kwargs["automatic_filtration_context"],
                )
            )
            calls.append(("body", value))

        async def async_set_pump_circuit_speed(self, target, value, **kwargs):
            authority.require_allowed(
                PhysicalCommandRequest(
                    operation="pump_circuit_speed",
                    target=target,
                    source=kwargs["request_source"],
                    requested_value=value,
                    automatic_filtration_context=kwargs["automatic_filtration_context"],
                )
            )
            calls.append(("pump_attempt", value))
            if fail_pump:
                # Recorder proves FAILED, but does not preserve its underlying cause.
                raise adapter.ManualIntelliCenterCommandError("injected delivery failure")

    factory = runtime._DeliveryFactory(Manual(), authority, registry)
    driver = FiltrationAutomaticExecutionDriver(registry)
    driver.set_enabled(
        True, changed_at=core_tests.NOW - timedelta(seconds=1), current_epoch_identity=None
    )

    async def epoch(seconds, pool, rpm, configured, satisfied=False):
        frame = core_tests._frame(
            core_tests.NOW + timedelta(seconds=seconds),
            pool=pool,
            rpm=rpm,
            configured=configured,
            satisfied=satisfied,
        )
        if actual_accounting:
            assessment = ledger.observe(
                core_tests.FiltrationObservation(
                    observed_at=frame.observed_at,
                    pool_active=pool,
                    spa_active=False,
                    pump_rpm=rpm,
                    water_temperature_f=80,
                    circulation_evidence_usable=True,
                    temperature_evidence_usable=True,
                ),
                safely_deferrable=False,
            )
            frame = replace(frame, filtration=assessment)
        authority.begin_automatic_filtration_epoch(frame.epoch_identity)
        epoch.last_accounting = frame.filtration
        result = await driver.process_epoch(frame, delivery_factory=factory)
        lease = registry.filtration_lease
        print(
            {
                "second": seconds,
                "state": result.state.value,
                "blocker": result.blocker,
                "body_verified": None if lease is None else lease.body_verified,
                "aggregate_verified": None if lease is None else lease.verified,
                "body_origin": None if lease is None else bool(lease.body_activation),
                "calls": list(calls),
            }
        )
        return result

    return driver, registry, calls, epoch, factory


def test_oct8_verified_body_pump_delivery_failure_debt_zero_must_allow_completion():
    async def run():
        driver, registry, calls, epoch, _ = setup(True)
        await epoch(0, False, 0, 2900)
        await epoch(1, True, 0, 2900)
        lease = registry.filtration_lease
        assert lease.body_verified and not lease.verified
        assert lease.body_activation is not None and lease.pump_setpoint is None
        assert lease.domain_state(OwnershipDomain.PUMP).health is OwnershipHealth.FAULTED
        await epoch(2, True, 2900, 2900)
        await epoch(14917, True, 2900, 2900, satisfied=True)
        await epoch(14918, True, 2900, 2900, satisfied=True)
        assert ("body", False) in calls, (
            "verified BODY completion was blocked solely by absent PUMP verification"
        )
        await epoch(14919, False, 900, 2900, satisfied=True)
        await epoch(14920, False, 0, 2900, satisfied=True)
        assert registry.filtration_lease is None

    asyncio.run(run())


def test_control_fully_verified_filtration_completes_through_real_ha_factory():
    async def run():
        _, registry, calls, epoch, _ = setup(False)
        await epoch(0, False, 0, 2900)
        await epoch(1, True, 0, 2900)
        await epoch(2, True, 2600, 2600)
        assert registry.filtration_lease.verified
        await epoch(14917, True, 2600, 2600, satisfied=True)
        assert ("body", False) in calls
        await epoch(14918, False, 900, 2600, satisfied=True)
        assert registry.filtration_lease is not None
        await epoch(14919, False, 0, 2600, satisfied=True)
        assert registry.filtration_lease is None

    asyncio.run(run())


def test_control_manual_pool_satisfied_never_gets_body_completion():
    async def run():
        _, registry, calls, epoch, _ = setup(False)
        await epoch(0, True, 2900, 2900, satisfied=True)
        await epoch(1, True, 2600, 2600, satisfied=True)
        assert not any(kind == "body" for kind, _ in calls)
        assert (
            registry.filtration_lease is None or registry.filtration_lease.body_activation is None
        )

    asyncio.run(run())


def test_control_wrong_session_cleanup_binding_is_rejected():
    async def run():
        _, registry, _, epoch, factory = setup(False)
        await epoch(0, False, 0, 2900)
        await epoch(1, True, 0, 2900)
        await epoch(2, True, 2600, 2600)
        frame = core_tests._frame(
            core_tests.NOW + timedelta(seconds=3),
            pool=True,
            rpm=2600,
            configured=2600,
            satisfied=True,
        )
        with pytest.raises(ValueError, match="cleanup ownership is not current"):
            factory.for_operation(
                frame=frame,
                session_id="obsolete-session",
                operation=SetBodyActive(equipment_id="pool", active=False),
                cleanup=True,
            )

    asyncio.run(run())


def test_filtration_native_callback_during_pump_delivery_must_not_invalidate_exact_context():
    async def run():
        module = runtime_tests._load_module()
        adapter = delivery_tests._load_module()
        module.ManualIntelliCenterFiltrationDelivery = adapter.ManualIntelliCenterFiltrationDelivery
        registry = PoolCirculationOwnershipRegistry()
        authority = PoolOSPhysicalCommandAuthority()
        authority.resolve_maintenance(False)
        authority.set_controller_mode("auto")
        entered = asyncio.Event()
        release = asyncio.Event()
        denial_reasons = []
        calls = []

        class Manual:
            available = True

            async def async_set_body_active(self, target, value, **kwargs):
                authority.require_allowed(
                    PhysicalCommandRequest(
                        operation="body_active",
                        target=target,
                        requested_value=value,
                        source=kwargs["request_source"],
                        automatic_filtration_context=kwargs["automatic_filtration_context"],
                    )
                )
                calls.append(("body", value))

            async def async_set_pump_circuit_speed(self, target, value, **kwargs):
                entered.set()
                await release.wait()  # Deterministic command-lock contention, no timed sleep.
                try:
                    authority.require_allowed(
                        PhysicalCommandRequest(
                            operation="pump_circuit_speed",
                            target=target,
                            requested_value=value,
                            source=kwargs["request_source"],
                            automatic_filtration_context=kwargs["automatic_filtration_context"],
                        )
                    )
                except PhysicalCommandDeniedError as exc:
                    denial_reasons.append(exc.decision.reason.value)
                    raise adapter.ManualIntelliCenterCommandError(str(exc)) from exc
                calls.append(("pump", value))

        hass = runtime_tests.FakeHass()
        accounting = SimpleNamespace(assessment=None)
        coordinator = SimpleNamespace(
            async_update_listeners=lambda: None, native_intellicenter_snapshot=None
        )
        runtime = module.PoolOSFiltrationAutomaticRuntime(
            hass,
            coordinator,
            accounting,
            SimpleNamespace(assessment=SimpleNamespace(pool_pump_circuit_id="p0102")),
            registry,
            authority,
            Manual(),
        )
        runtime.driver.set_enabled(
            True, changed_at=core_tests.NOW - timedelta(seconds=1), current_epoch_identity=None
        )
        runtime._desired_enabled = True
        authority.configure_automatic_filtration(enabled=True)

        def observe(seconds, pool, rpm):
            frame = core_tests._frame(
                core_tests.NOW + timedelta(seconds=seconds), pool=pool, rpm=rpm, configured=2900
            )
            accounting.assessment = frame.filtration
            runtime.observe(
                SimpleNamespace(generated_at=frame.observed_at, observations=frame.observations),
                runtime_tests._orchestration(frame.epoch_identity),
                external_changes=ExternalChangeBatch(()),
            )

        observe(0, False, 0)
        await hass.tasks[-1]
        observe(1, True, 0)
        pump_task = hass.tasks[-1]
        await entered.wait()
        observe(
            2, True, 2900
        )  # Harmless native consequence while exact PUMP request waits for gateway.
        release.set()
        await pump_task
        print(
            {
                "denial_reasons": denial_reasons,
                "accepted": runtime.driver.diagnostics()["accepted_delivery_count"],
                "body_verified": registry.filtration_lease.body_verified,
                "calls": calls,
            }
        )
        # Drain the coalesced successor; no orphan test tasks.
        if hass.tasks[-1] is not pump_task:
            await hass.tasks[-1]
        assert ("pump", 2600) in calls, (
            "native publication invalidated an otherwise current exact PUMP dispatch"
        )

    asyncio.run(run())


def test_real_accounting_zero_after_native_circulation_preserves_body_completion():
    async def run():
        driver, registry, calls, epoch, _ = setup(True, actual_accounting=True)
        await epoch(0, False, 0, 2900)
        await epoch(1, True, 0, 2900)
        await epoch(17, True, 2900, 2900)
        previous = None
        for seconds in range(137, 36018, 120):
            await epoch(seconds, True, 2900, 2900)
            remaining = epoch.last_accounting.total_remaining_runtime
            if previous is not None:
                assert remaining <= previous
            previous = remaining
            if remaining == timedelta(0):
                break
        else:
            raise AssertionError("real accounting never reached SATISFIED")
        assert driver.diagnostics()["accepted_delivery_count"] == 2
        assert registry.filtration_lease.body_verified
        assert registry.filtration_lease.body_activation is not None
        assert ("body", False) in calls, (
            "real credited debt reached zero but verified BODY could not complete"
        )

    asyncio.run(run())
