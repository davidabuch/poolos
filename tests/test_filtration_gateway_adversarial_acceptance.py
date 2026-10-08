"""Permanent PR-517 independent acceptance through the real physical gateway.

Only the final transport is a recorder. Command-lock contention, runtime,
domain permission, cleanup binding, and final gateway admission are production
objects. The clock and coordinator frames are deterministic and equipment-free.
"""

import asyncio
import importlib.util
import sys
from datetime import timedelta, datetime
from types import SimpleNamespace
import pytest
import test_filtration_automatic_execution as c
import test_home_assistant_filtration_automatic_runtime as r
import test_home_assistant_filtration_live_delivery as d
import test_home_assistant_thermal_automatic_runtime as t
import test_home_assistant_native_pump_rpm_behavior as m
from poolos.external_change import ExternalChangeBatch
from poolos.pool_circulation_ownership import PoolCirculationOwnershipRegistry
from poolos.ownership_evidence import OwnershipDomain


TEST_CLOCK = SimpleNamespace(now=c.NOW)


class AuditDateTime(datetime):
    @classmethod
    def now(cls, tz=None):
        value = TEST_CLOCK.now
        return value.astimezone(tz) if tz is not None else value.replace(tzinfo=None)


@pytest.fixture(autouse=True)
def _deterministic_dispatch_clock(monkeypatch):
    TEST_CLOCK.now = c.NOW
    monkeypatch.setattr(m.manual_module, "datetime", AuditDateTime)


def load_delivery():
    d._load_module()
    name = f"{d.PACKAGE_NAME}.manual_intellicenter"
    sys.modules[name] = m.manual_module
    spec = importlib.util.spec_from_file_location(
        f"{d.PACKAGE_NAME}.real_filtration_delivery", d.MODULE_PATH
    )
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    module.datetime = AuditDateTime
    return module


def bridge(registry=None):
    module = r._load_module()
    module.ManualIntelliCenterFiltrationDelivery = (
        load_delivery().ManualIntelliCenterFiltrationDelivery
    )
    gateway, recorder = m._gateway([])
    authority = gateway._command_authority
    authority.configure_automatic_filtration(enabled=True)
    registry = registry or PoolCirculationOwnershipRegistry()
    hass = r.FakeHass()
    accounting = SimpleNamespace(assessment=None)
    coord = SimpleNamespace(async_update_listeners=lambda: None)
    runtime = module.PoolOSFiltrationAutomaticRuntime(
        hass,
        coord,
        accounting,
        SimpleNamespace(assessment=SimpleNamespace(pool_pump_circuit_id="p0102")),
        registry,
        authority,
        gateway,
    )
    runtime.driver.set_enabled(
        True, changed_at=c.NOW - timedelta(seconds=1), current_epoch_identity=None
    )
    runtime._desired_enabled = True
    authority.configure_automatic_filtration(enabled=True)
    # Actual canonical domain-permission callback, no permissive replacement.
    thermal_type = t._load_module().PoolOSThermalAutomaticRuntime
    thermal = thermal_type.__new__(thermal_type)
    thermal.circulation_ownership = registry
    thermal.pool_automatic_control = runtime.pool_automatic_control
    thermal.orchestrator = SimpleNamespace(
        ownership=SimpleNamespace(state=SimpleNamespace(lease=None))
    )
    thermal._latest_frame = None
    authority.ownership_permission_reader = thermal._domain_command_permitted

    def observe(
        seconds,
        *,
        pool=False,
        spa=False,
        circuit="p0102",
        thermal_ready=False,
        missing=(),
        stale=(),
        satisfied=False,
        rpm=0,
        configured=2600,
    ):
        TEST_CLOCK.now = max(TEST_CLOCK.now, c.NOW + timedelta(seconds=seconds))
        frame = c._frame(
            c.NOW + timedelta(seconds=seconds),
            pool=pool,
            spa=spa,
            rpm=rpm,
            configured=configured,
            satisfied=satisfied,
            pump_circuit_id=circuit,
            missing=missing,
            stale=stale,
        )
        accounting.assessment = frame.filtration
        runtime.thermal_runtime.assessment.pool_pump_circuit_id = circuit
        orchestration = r._orchestration(frame.epoch_identity, pool_candidate=thermal_ready)
        if thermal_ready:
            registry.begin_epoch(frame.epoch_identity)
            registry.reserve_thermal(epoch_identity=frame.epoch_identity)
        thermal._latest_frame = SimpleNamespace(observations=frame.observations)
        # Production thermal observe advances registry identity before filtration observe.
        registry.begin_epoch(frame.epoch_identity)
        runtime.observe(
            SimpleNamespace(generated_at=frame.observed_at, observations=frame.observations),
            orchestration,
            external_changes=ExternalChangeBatch(()),
        )
        return frame

    return runtime, hass, gateway, recorder, authority, registry, observe


@pytest.mark.parametrize(
    "change",
    [
        "benign",
        "spa_on",
        "pool_on",
        "topology",
        "missing",
        "thermal",
        "maintenance",
        "reset",
        "manual_off",
        "unload",
        "grid",
        "expired",
        "delayed",
    ],
)
def test_pending_body_dispatch_rechecks_material_authority(change):
    async def run():
        runtime, hass, gateway, recorder, authority, registry, observe = bridge()
        await gateway._command_lock.acquire()
        observe(0)
        task = hass.tasks[-1]
        # Yield for actual reserve and command-lock wait, not a timed race.
        await asyncio.sleep(0)
        assert task is runtime._task and not task.done()
        if change == "spa_on":
            observe(1, spa=True)
        elif change == "pool_on":
            observe(1, pool=True)
        elif change == "topology":
            observe(1, circuit="p0103")
        elif change == "missing":
            observe(1, missing=("spa.active",))
        elif change == "thermal":
            observe(1, thermal_ready=True)
        elif change == "maintenance":
            authority.resolve_maintenance(True)
        elif change == "reset":
            authority.begin_reset_recovery()
        elif change == "manual_off":
            authority.set_pool_automatic_control_suppressed(True)
        elif change == "unload":
            authority.unload_automatic_filtration_driver()
        elif change == "expired":
            observe(121, stale=("pool.active",))
        elif change == "delayed":
            observe(-1)
        elif change == "grid":
            authority.set_grid_outage_domain_state(
                active=True, outage_epoch_id="outage", pump_ceiling_required=True
            )
        else:
            observe(1)
        gateway._command_lock.release()
        await task
        first_calls = list(recorder.calls)
        # Drain coalesced successor task without any live transport.
        if hass.tasks[-1] is not task:
            await hass.tasks[-1]
        if change in {"benign", "pool_on", "delayed"}:
            assert ("B1101", {"STATUS": "ON"}) in first_calls
        else:
            assert not first_calls, f"{change} failed to revoke obsolete BODY ON: {first_calls}"

    asyncio.run(run())


def test_gateway_not_dispatched_cleanup_denial_does_not_poison_body():
    driver, delivery, factory = c._verified_filtration_driver()

    async def run():
        module = r._load_module()
        module.ManualIntelliCenterFiltrationDelivery = (
            load_delivery().ManualIntelliCenterFiltrationDelivery
        )
        gateway, recorder = m._gateway([])
        authority = gateway._command_authority
        authority.configure_automatic_filtration(enabled=True)
        frame = c._frame(
            c.NOW + timedelta(seconds=3), pool=True, rpm=2600, configured=2600, satisfied=True
        )
        authority.begin_automatic_filtration_epoch(frame.epoch_identity)
        real_factory = module._DeliveryFactory(gateway, authority, driver.ownership)
        await gateway._command_lock.acquire()
        task = asyncio.create_task(driver.process_epoch(frame, delivery_factory=real_factory))
        await asyncio.sleep(0)
        authority.resolve_maintenance(True)
        gateway._command_lock.release()
        result = await task
        print(
            "denied cleanup:",
            result.blocker,
            "body blocker:",
            driver.ownership.domain_permission_blocker(OwnershipDomain.BODY),
        )
        assert recorder.calls == []
        authority.resolve_maintenance(False)
        next_frame = c._frame(
            c.NOW + timedelta(seconds=4), pool=True, rpm=2600, configured=2600, satisfied=True
        )
        authority.begin_automatic_filtration_epoch(next_frame.epoch_identity)
        retry = await driver.process_epoch(next_frame, delivery_factory=real_factory)
        print("after maintenance cleared:", retry.blocker, "physical calls:", recorder.calls)
        assert driver.ownership.domain_permission_blocker(OwnershipDomain.BODY) is None, (
            "pre-dispatch gateway denial poisoned BODY after fresh recovery epoch"
        )
        assert ("B1101", {"STATUS": "OFF"}) in recorder.calls

    asyncio.run(run())


def test_shutdown_stale_configured_evidence_retains_completion_until_pump_zero():
    driver, delivery, factory = c._verified_filtration_driver()
    asyncio.run(
        driver.process_epoch(
            c._frame(
                c.NOW + timedelta(seconds=3), pool=True, rpm=2600, configured=2600, satisfied=True
            ),
            delivery_factory=factory,
        )
    )
    result = asyncio.run(
        driver.process_epoch(
            c._frame(
                c.NOW + timedelta(seconds=4),
                pool=False,
                rpm=900,
                configured=2600,
                satisfied=True,
                stale=("pool.pump_circuit.configured_speed_rpm",),
            ),
            delivery_factory=factory,
        )
    )
    print("stale during coastdown:", result.blocker, "lease:", driver.ownership.filtration_lease)
    assert driver.ownership.filtration_lease is not None
    restored = asyncio.run(
        driver.process_epoch(
            c._frame(
                c.NOW + timedelta(seconds=5), pool=False, rpm=900, configured=2600, satisfied=True
            ),
            delivery_factory=factory,
        )
    )
    print("fresh coastdown after suspension:", restored.blocker)
    assert driver.ownership.filtration_lease is not None, (
        "accepted shutdown completion discarded before pump zero"
    )


@pytest.mark.parametrize(
    "change", ["benign", "spa_on", "topology", "released", "thermal_successor", "operator"]
)
def test_pending_cleanup_revalidates_exact_current_body_entitlement(change):
    driver, _, _ = c._verified_filtration_driver()

    async def run():
        runtime, hass, gateway, recorder, authority, registry, observe = bridge(driver.ownership)
        runtime.driver = driver
        await gateway._command_lock.acquire()
        observe(3, pool=True, rpm=2600, satisfied=True)
        task = hass.tasks[-1]
        await asyncio.sleep(0)
        assert not recorder.calls and not task.done()
        if change == "spa_on":
            observe(4, pool=True, spa=True, rpm=2600, satisfied=True)
        elif change == "topology":
            observe(4, pool=True, circuit="p0103", rpm=2600, satisfied=True)
        elif change == "released":
            registry.release_filtration(session_id=registry.filtration_lease.session_id)
        elif change == "thermal_successor":
            observe(4, pool=True, rpm=2600, satisfied=True, thermal_ready=True)
            token = registry.begin_filtration_to_thermal(
                thermal_purpose_id="new-thermal-purpose",
                established_at=c.NOW + timedelta(seconds=4),
            )
            assert token is not None
            registry.complete_filtration_to_thermal(
                token_id=token.token_id, thermal_lease_id="valid-new-thermal-lease"
            )
        elif change == "operator":
            from poolos.ownership_evidence import PositiveOperatorEvidence

            lease = registry.filtration_lease
            evidence = PositiveOperatorEvidence(
                "operator-body",
                lease.body_session_generation or lease.generation,
                lease.body_session_id or lease.session_id,
                OwnershipDomain.BODY,
                "B1101",
                c.NOW + timedelta(seconds=4),
            )
            assert registry.record_operator_intent(
                evidence, evaluated_at=c.NOW + timedelta(seconds=4)
            )
        else:
            observe(4, pool=True, rpm=2600, satisfied=True)
        gateway._command_lock.release()
        await task
        first = list(recorder.calls)
        if hass.tasks[-1] is not task:
            await hass.tasks[-1]
        if change == "benign":
            assert ("B1101", {"STATUS": "OFF"}) in first
        else:
            assert first == [], (
                f"{change} allowed BODY OFF with superseded cleanup authority: {first}"
            )

    asyncio.run(run())


def test_actual_resume_switch_keeps_last_assessment_until_fresh_filtration_epoch():
    import test_home_assistant_native_switch as switches
    from poolos.pool_automatic_control_suppression import PoolAutomaticControlSuppressionSource

    async def run():
        runtime, hass, gateway, recorder, authority, registry, observe = bridge()
        control = runtime.pool_automatic_control
        control.add_listener(
            lambda state: authority.set_pool_automatic_control_suppressed(
                control.globally_suppressed
            )
        )
        control.suppress(
            source=PoolAutomaticControlSuppressionSource.OPERATOR_RESTRAINT,
            suppressed_at=c.NOW - timedelta(seconds=1),
            reason="operator_disabled_autonomous_pool_control",
        )
        observe(0, satisfied=True)
        await hass.tasks[-1]
        assert (
            runtime.driver.assessment.blocker == "automatic_filtration_manual_pool_off_suppressed"
        )
        entity = switches._load_executable_switch_module().PoolOSPoolAutonomousControlSwitch(
            SimpleNamespace(
                entry_id="audit",
                runtime_data=SimpleNamespace(
                    pool_automatic_control=control,
                    physical_command_authority=authority,
                    coordinator=runtime.coordinator,
                ),
            )
        )
        entity.async_write_ha_state = lambda: None
        await entity.async_turn_on()
        assert entity.is_on and not control.globally_suppressed
        assert (
            runtime.driver.assessment.blocker == "automatic_filtration_manual_pool_off_suppressed"
        )
        assert recorder.calls == []
        observe(30, satisfied=True)
        await hass.tasks[-1]
        assert runtime.driver.assessment.blocker == "automatic_filtration_not_immediately_required"
        assert recorder.calls == [] and registry.filtration_lease is None

    asyncio.run(run())


def test_partial_body_verified_full_gateway_cleanup_reaches_zero_without_replay():
    async def run():
        runtime, hass, gateway, recorder, authority, registry, observe = bridge()
        observe(0)
        await hass.tasks[-1]
        assert recorder.calls == [("B1101", {"STATUS": "ON"})]
        observe(1, pool=True, rpm=0)
        await hass.tasks[-1]
        lease = registry.filtration_lease
        assert lease is not None and lease.body_verified and not lease.verified
        assert lease.body_activation is not None and lease.pump_setpoint is None
        assert (
            registry.domain_permission_blocker(OwnershipDomain.PUMP)
            == "automatic_filtration_domain_control_fault:pump"
        )
        observe(2, pool=True, rpm=2600, satisfied=True)
        await hass.tasks[-1]
        assert recorder.calls[-1] == ("B1101", {"STATUS": "OFF"})
        observe(3, pool=False, rpm=900, satisfied=True)
        await hass.tasks[-1]
        assert registry.filtration_lease is not None
        observe(4, pool=False, rpm=0, satisfied=True)
        await hass.tasks[-1]
        assert registry.filtration_lease is None
        for second in range(5, 26):
            observe(second, pool=False, rpm=0, satisfied=True)
            await hass.tasks[-1]
        assert recorder.calls == [("B1101", {"STATUS": "ON"}), ("B1101", {"STATUS": "OFF"})]
        assert runtime.driver.assessment.accepted_delivery_count == 2

    asyncio.run(run())


def test_real_transport_pump_failure_does_not_prevent_verified_body_completion():
    import conftest as fixtures

    async def run():
        runtime, hass, gateway, recorder, authority, registry, observe = bridge()
        pump = fixtures.pump_object_factory.__wrapped__()()
        circuit = fixtures.pump_circuit_object_factory.__wrapped__()("p0102", circuit_id="C0006")
        gateway._model = m._Model([pump, circuit])
        observe(0)
        await hass.tasks[-1]
        assert recorder.calls == [("B1101", {"STATUS": "ON"})]
        attempted = []
        original = recorder.request_changes

        async def reject_pump(objnam, changes):
            attempted.append((objnam, dict(changes)))
            if objnam == "p0102":
                raise RuntimeError("transport failure after dispatch began")
            await original(objnam, changes)

        recorder.request_changes = reject_pump
        observe(1, pool=True, rpm=3000)
        await hass.tasks[-1]
        print(
            "pump model failure diagnostic:",
            runtime.driver.assessment.blocker,
            runtime.driver.assessment.last_failure_reason,
            gateway._last_error_code,
            attempted,
        )
        assert ("p0102", {"SPEED": "2600"}) in attempted
        lease = registry.filtration_lease
        assert lease is not None and lease.body_verified and not lease.verified
        observe(2, pool=True, rpm=2900, satisfied=True)
        await hass.tasks[-1]
        assert recorder.calls[-1] == ("B1101", {"STATUS": "OFF"})
        observe(3, pool=False, rpm=900, satisfied=True)
        await hass.tasks[-1]
        assert registry.filtration_lease is not None
        observe(4, pool=False, rpm=0, satisfied=True)
        await hass.tasks[-1]
        assert registry.filtration_lease is None

    asyncio.run(run())


@pytest.mark.parametrize(
    "missing_concept", ["pool.active", "spa.active", "pool.pump_circuit.configured_speed_rpm"]
)
def test_partial_verified_body_retains_completion_across_temporary_evidence_loss(missing_concept):
    async def run():
        runtime, hass, gateway, recorder, authority, registry, observe = bridge()
        observe(0)
        await hass.tasks[-1]
        observe(1, pool=True, rpm=2600)
        await hass.tasks[-1]
        prior = registry.filtration_lease
        assert prior is not None and prior.body_verified and not prior.verified
        observe(2, pool=True, rpm=2600, satisfied=True, missing=(missing_concept,))
        await hass.tasks[-1]
        assert recorder.calls == [("B1101", {"STATUS": "ON"})]
        first_blocker = runtime.driver.assessment.blocker
        lease_after_loss = registry.filtration_lease
        observe(3, pool=True, rpm=2600, satisfied=True)
        await hass.tasks[-1]
        print(
            "partial-body evidence loss:",
            missing_concept,
            first_blocker,
            "retained:",
            lease_after_loss,
            "fresh recovery:",
            runtime.driver.assessment.blocker,
            "commands:",
            recorder.calls,
        )
        assert lease_after_loss is not None, (
            "temporary evidence loss erased verified BODY provenance because PUMP was not verified"
        )
        assert ("B1101", {"STATUS": "OFF"}) in recorder.calls

    asyncio.run(run())


@pytest.mark.parametrize(
    "change",
    [
        "settling",
        "near_target",
        "converged",
        "spa",
        "pool_off",
        "configured_intent",
        "missing",
        "invalid_rpm",
        "operator_pump",
        "operator_body",
        "maintenance",
        "reset",
        "unload",
        "thermal",
        "topology",
    ],
)
def test_real_gateway_pending_pump_preserves_only_compatible_convergence(change):
    """Same command lock, actual RPM feedback versus genuine authority loss."""
    import conftest as fixtures
    from poolos.ownership_evidence import PositiveOperatorEvidence

    async def run():
        runtime, hass, gateway, recorder, authority, registry, observe = bridge()
        pump = fixtures.pump_object_factory.__wrapped__()()
        circuit = fixtures.pump_circuit_object_factory.__wrapped__()("p0102", circuit_id="C0006")
        gateway._model = m._Model([pump, circuit])
        observe(0)
        await hass.tasks[-1]
        await gateway._command_lock.acquire()
        observe(1, pool=True, rpm=3000)
        task = hass.tasks[-1]
        await asyncio.sleep(0)
        assert not task.done()
        proof = registry.filtration_lease.body_activation
        assert registry.filtration_lease.body_verified
        if change in {"settling", "near_target", "converged"}:
            observe(
                2, pool=True, rpm={"settling": 3450, "near_target": 2550, "converged": 2600}[change]
            )
        elif change == "spa":
            observe(2, pool=True, spa=True, rpm=3000)
        elif change == "pool_off":
            observe(2, pool=False, rpm=3000)
        elif change == "configured_intent":
            observe(2, pool=True, rpm=3000, configured=3100)
        elif change == "missing":
            observe(2, pool=True, rpm=3000, missing=("spa.active",))
        elif change == "invalid_rpm":
            observe(2, pool=True, rpm=-1)
        elif change in {"operator_pump", "operator_body"}:
            lease = registry.filtration_lease
            domain = OwnershipDomain.PUMP if change == "operator_pump" else OwnershipDomain.BODY
            evidence = PositiveOperatorEvidence(
                "positive-operator-intent",
                lease.body_session_generation,
                lease.body_session_id,
                domain,
                "p0102" if domain is OwnershipDomain.PUMP else "B1101",
                c.NOW + timedelta(seconds=2),
            )
            assert registry.record_operator_intent(evidence, evaluated_at=evidence.requested_at)
        elif change == "maintenance":
            authority.resolve_maintenance(True)
        elif change == "reset":
            authority.begin_reset_recovery()
        elif change == "unload":
            authority.unload_automatic_filtration_driver()
        elif change == "thermal":
            observe(2, pool=True, rpm=3000, thermal_ready=True)
            # An unverified acquiring lease cannot hand off yet. A refused
            # reservation is not a transfer of authority; finish its Pump step.
            assert not registry.thermal_reserved_for(runtime._latest_frame.epoch_identity)
        elif change == "topology":
            observe(2, pool=True, rpm=3000, circuit="p0103")
        gateway._command_lock.release()
        await task
        first_calls = list(recorder.calls)
        if hass.tasks[-1] is not task:
            await hass.tasks[-1]
        if change in {"settling", "near_target", "converged", "thermal"}:
            assert ("p0102", {"SPEED": "2600"}) in first_calls
            assert registry.filtration_lease.body_activation == proof
            assert registry.filtration_lease.pump_setpoint is not None
        else:
            assert first_calls == [("B1101", {"STATUS": "ON"})]

    asyncio.run(run())
