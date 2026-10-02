import asyncio
from dataclasses import replace
from datetime import datetime, timedelta
import pytest
import test_filtration_automatic_execution as f
import test_thermal_runtime_orchestrator as o
import test_independent_intellicenter_transport as t
from poolos.hal import CommandReceipt, CommandStatus
from poolos.thermal_runtime_ownership import ThermalRuntimeOwnershipStatus


def test_old_same_timestamp_frame_cannot_end_newer_accepted_lease():
    orchestrator = o.ThermalRuntimeOrchestrator()
    o._refresh(orchestrator, o.NOW)
    accepted = o.NOW + timedelta(milliseconds=50)
    o._establish_pool_full_ownership(orchestrator, at=accepted)
    conflicting = tuple(
        o._observation(
            x.observation_id, False if x.observation_id == "pool.active" else x.value, at=o.NOW
        )
        for x in o._observations(o.NOW)
    )
    result = o._refresh(orchestrator, o.NOW, observations=conflicting)
    assert result.ownership_status is ThermalRuntimeOwnershipStatus.OWNED


def test_filtration_preacceptance_observation_cannot_verify_body_on():
    class LateDelivery(f._Delivery):
        async def deliver(self, operation, *, correlation_id):
            self.operations.append(operation)
            return CommandReceipt(
                status=CommandStatus.ACKNOWLEDGED,
                command_id=correlation_id,
                issued_at=f.NOW + timedelta(seconds=2),
                acknowledged_at=f.NOW + timedelta(seconds=3),
            )

    driver, _, _ = f._enabled_driver()
    delivery = LateDelivery([])
    factory = f._Factory(delivery)
    asyncio.run(
        driver.process_epoch(
            f._frame(f.NOW, pool=False, rpm=0, configured=2600), delivery_factory=factory
        )
    )
    result = asyncio.run(
        driver.process_epoch(
            f._frame(f.NOW + timedelta(seconds=1), pool=True, rpm=0, configured=2600),
            delivery_factory=factory,
        )
    )
    assert result.current_step is f.FiltrationExecutionStep.BODY_ON
    assert len(delivery.operations) == 1


def test_unrelated_pump_callback_cannot_reobserve_cached_body(monkeypatch):
    module = t._load_module(monkeypatch)
    transport = module.IndependentIntelliCenterReadOnlyTransport(host="192.0.2.10")
    asyncio.run(transport.async_start())
    old = next(x for x in transport.latest_snapshot.raw_inventory if x.native_id == "B1101")
    transport._on_updated({"P0001": {"RPM": 2300}})
    new = next(x for x in transport.latest_snapshot.raw_inventory if x.native_id == "B1101")
    assert new.attributes == old.attributes
    assert new.observed_at == old.observed_at


def test_old_manager_evidence_cannot_preempt_later_confirmed_lease():
    import test_thermal_runtime_ownership as w

    manager = w.full_manager()
    manager.evaluate(w.evidence(at=w.NOW + timedelta(seconds=2)))
    lease = manager.state.lease
    manager.evaluate(w.evidence(at=w.NOW + timedelta(seconds=1)))
    assert manager.state.lease == lease
    assert manager.state.status is ThermalRuntimeOwnershipStatus.OWNED


def test_real_thermal_runtime_native_callback_preserves_newer_accepted_origin():
    import test_home_assistant_thermal_runtime as h
    from types import SimpleNamespace

    runtime, coordinator, _ = h.runtime_fixture()
    coordinator.data.generated_at = o.NOW
    coordinator.data.observations = o._observations(o.NOW)
    coordinator.native_intellicenter_snapshot.observations = tuple(
        SimpleNamespace(
            observation_id=x.observation_id, value=x.value, source_id=x.source_id, observed_at=o.NOW
        )
        for x in coordinator.native_intellicenter_snapshot.observations
    )
    orchestrator = o.ThermalRuntimeOrchestrator()
    callbacks = []

    def observer(snapshot, thermal):
        callbacks.append(
            orchestrator.refresh(
                generated_at=snapshot.generated_at,
                observations=snapshot.observations,
                thermal=thermal,
            )
        )

    runtime.set_orchestration_observer(observer)
    runtime.refresh()
    o._establish_pool_full_ownership(orchestrator, at=o.NOW + timedelta(milliseconds=50))
    coordinator.native_intellicenter_snapshot.observations = tuple(
        SimpleNamespace(
            observation_id=x.observation_id,
            value=(89.0 if x.observation_id == "pool.target_temperature" else x.value),
            source_id=x.source_id,
            observed_at=o.NOW + timedelta(seconds=1),
        )
        for x in coordinator.native_intellicenter_snapshot.observations
    )
    runtime.refresh()
    assert len(callbacks) == 2
    assert callbacks[-1].ownership_status is ThermalRuntimeOwnershipStatus.OWNED


def test_same_identity_conflict_without_newer_lease_still_blocks():
    orchestrator = o.ThermalRuntimeOrchestrator()
    o._refresh(orchestrator, o.NOW)
    changed = o._observations(o.NOW, spa_active=True)
    result = o._refresh(orchestrator, o.NOW, observations=changed)
    assert result.blocking_reason == "thermal_orchestration_snapshot_conflict"
    assert result.candidate_id is None


def test_current_topology_loss_still_preempts_owned_manager():
    import test_thermal_runtime_ownership as w

    manager = w.full_manager()
    manager.evaluate(w.evidence(at=w.NOW + timedelta(seconds=1), pool_active=False))
    assert manager.state.status is not ThermalRuntimeOwnershipStatus.OWNED


def test_restart_matching_state_remains_unowned():
    import test_thermal_runtime_ownership as w
    from poolos.thermal_runtime_ownership import ThermalRuntimeOwnershipManager

    manager = ThermalRuntimeOwnershipManager()
    manager.evaluate(w.evidence(at=w.NOW + timedelta(seconds=1)))
    assert manager.state.status is ThermalRuntimeOwnershipStatus.UNOWNED
    assert manager.state.lease is None


def test_source_reply_does_not_refresh_body_activity_or_pump(monkeypatch):
    from poolos.intellicenter_readonly import NativeIntelliCenterReadAdapter

    module = t._load_module(monkeypatch)
    clock = [t.NOW]

    class Clock(datetime):
        @classmethod
        def now(cls, tz=None):
            return clock[0]

    monkeypatch.setattr(module, "datetime", Clock)
    transport = module.IndependentIntelliCenterReadOnlyTransport(host="192.0.2.10")
    asyncio.run(transport.async_start())
    transport._controller._updated_callback = lambda _, changes: transport._on_updated(changes)
    clock[0] += timedelta(seconds=1)
    transport._controller._apply_updates([{"objnam": "B1101", "params": {"HEATER": "H0002"}}])
    native = NativeIntelliCenterReadAdapter().capture(transport, generated_at=clock[0])
    facts = {item.observation_id: item for item in native.observations}
    assert facts["pool.raw_heater_id"].observed_at == clock[0]
    assert facts["pool.active"].observed_at == t.NOW
    assert facts["pump.rpm"].observed_at == t.NOW


def test_unchanged_reply_refreshes_only_returned_fields(monkeypatch):
    from poolos.intellicenter_readonly import NativeIntelliCenterReadAdapter

    module = t._load_module(monkeypatch)
    transport = module.IndependentIntelliCenterReadOnlyTransport(host="192.0.2.10")
    asyncio.run(transport.async_start())
    before = NativeIntelliCenterReadAdapter().capture(
        transport, generated_at=transport.latest_snapshot.observed_at
    )
    old = {item.observation_id: item for item in before.observations}
    at = before.generated_at + timedelta(seconds=1)
    publications = []
    transport._set_snapshot_update_callback(lambda: publications.append(transport.latest_snapshot))
    transport._controller._updated_callback = lambda _, changes: transport._on_updated(changes)
    # Simulate the vendor returning no changed fields, while retaining the
    # production PoolOS reply/observation boundary above it.
    monkeypatch.setattr(
        type(transport._controller).__mro__[1], "_apply_updates", lambda self, entries: {}
    )
    transport._controller._apply_updates(
        [{"objnam": "B1101", "params": {"STATUS": "ON"}}], observed_at=at
    )
    assert len(publications) == 1
    mapped = NativeIntelliCenterReadAdapter().capture(transport, generated_at=at)
    facts = {item.observation_id: item for item in mapped.observations}
    assert facts["pool.active"].observed_at == at
    assert facts["pool.raw_heater_id"].observed_at == old["pool.raw_heater_id"].observed_at
    assert facts["pump.rpm"].observed_at == old["pump.rpm"].observed_at


def test_thermal_policy_uses_captured_native_input_not_latest_mutable_pointer():
    import test_home_assistant_thermal_runtime as h
    from poolos.intellicenter_readonly import (
        NativeIntelliCenterObservationSnapshot,
        NativeIntelliCenterStatus,
    )

    runtime, coordinator, _ = h.runtime_fixture()
    captured = NativeIntelliCenterObservationSnapshot(
        h.NOW,
        NativeIntelliCenterStatus.AVAILABLE,
        "native-test",
        tuple(
            o._observation(item.observation_id, item.value, at=h.NOW)
            for item in coordinator.native_intellicenter_snapshot.observations
        ),
        (),
    )
    coordinator.data.native_snapshot = captured
    runtime.refresh()
    original = runtime.assessment
    coordinator.native_intellicenter_snapshot = replace(
        captured,
        generated_at=h.NOW + timedelta(seconds=1),
        observations=tuple(
            replace(item, value=89.0) if item.observation_id == "pool.target_temperature" else item
            for item in captured.observations
        ),
    )
    runtime.refresh()
    assert runtime.assessment == original


@pytest.mark.parametrize("offset, admitted", [(-1, False), (0, False), (1, True)])
def test_shared_consequence_admission_requires_strictly_later_evidence(offset, admitted):
    from poolos.evidence_chronology import EvidenceAdmission, admit_evidence

    result = admit_evidence(o.NOW + timedelta(seconds=offset), boundary=o.NOW)
    assert (result is EvidenceAdmission.POST_BOUNDARY) is admitted


def test_new_evaluation_clock_cannot_make_old_body_off_end_newer_origin():
    import test_thermal_runtime_ownership as w

    manager = w.full_manager()
    lease = manager.state.lease
    evidence = replace(
        w.evidence(at=w.NOW + timedelta(seconds=1), pool_active=False),
        pool_activity_observed_at=w.NOW - timedelta(seconds=1),
    )
    manager.evaluate(evidence)
    assert manager.state.lease == lease
    assert manager.state.status is ThermalRuntimeOwnershipStatus.OWNED


@pytest.mark.parametrize("elapsed", [2, 10, 31])
def test_current_publication_with_old_body_fact_cannot_retire_pending_driver(elapsed):
    import test_thermal_automatic_execution as a

    orchestrator = a.ThermalRuntimeOrchestrator()
    driver = a.ThermalAutomaticExecutionDriver(orchestrator)
    delivery = a.FakeDelivery()
    factory = a.FakeDeliveryFactory(delivery)
    baseline = a._frame(orchestrator, a.NOW, pool_active=False)
    driver.note_disabled_epoch(baseline)
    driver.set_enabled(True, changed_at=a.NOW, current_epoch_identity=baseline.epoch_identity)
    asyncio.run(
        driver.process_epoch(
            a._frame(orchestrator, a.NOW + timedelta(seconds=1), pool_active=False),
            delivery_factory=factory,
        )
    )
    lease = orchestrator.ownership.state.lease
    session = driver.active_session
    pending = a._frame(
        orchestrator,
        a.NOW + timedelta(seconds=elapsed),
        pool_active=False,
        observation_times={"pool.active": a.NOW},
    )
    result = asyncio.run(driver.process_epoch(pending, delivery_factory=factory))
    if elapsed < 31:
        assert orchestrator.ownership.state.lease == lease
        assert driver.active_session == session
    else:
        assert result.blocker == "verification_deadline_reached"
        assert orchestrator.ownership.state.status is ThermalRuntimeOwnershipStatus.RELINQUISHED
    assert result.command_delivery_performed is False
    assert len(delivery.calls) == 1


def test_delayed_metadata_reply_cannot_overwrite_newer_native_body(monkeypatch):
    module = t._load_module(monkeypatch)
    clock = [t.NOW]

    class Clock(datetime):
        @classmethod
        def now(cls, tz=None):
            return clock[0]

    monkeypatch.setattr(module, "datetime", Clock)
    transport = module.IndependentIntelliCenterReadOnlyTransport(host="192.0.2.10")
    asyncio.run(transport.async_start())
    controller = transport._controller

    async def delayed_reply(cmd, extra=None):
        clock[0] += timedelta(seconds=1)
        controller._apply_updates([{"objnam": "B1101", "params": {"STATUS": "ON"}}])
        return {"objectList": [{"objnam": "B1101", "params": {"STATUS": "OFF", "HEATER": "00000"}}]}

    monkeypatch.setattr(controller, "send_cmd", delayed_reply)
    asyncio.run(
        controller.refresh_body_metadata(
            "B1101",
            applying_body_ids=set(),
            generation_is_current=lambda: True,
        )
    )
    assert controller._model["B1101"]["STATUS"] == "ON"
    assert transport._attribute_observed_at[("B1101", "STATUS")] > t.NOW


@pytest.mark.parametrize("domain", ["pump", "thermal"])
def test_new_publication_cannot_reconcile_older_domain_contradiction(domain):
    import test_thermal_runtime_ownership as w
    from poolos.ownership_evidence import OwnershipDomain, OwnershipEvidenceKind

    manager = w.full_manager()
    manager.evaluate(
        w.evidence(
            at=w.NOW + timedelta(seconds=2),
            pump_observed_at=w.NOW + timedelta(seconds=2),
            configured_pump_observed_at=w.NOW + timedelta(seconds=2),
            source_observed_at=w.NOW + timedelta(seconds=2),
        )
    )
    owned = manager.state.lease
    evidence = w.evidence(at=w.NOW + timedelta(seconds=3))
    if domain == "pump":
        evidence = replace(evidence, pump_rpm=3200, pump_observed_at=w.NOW + timedelta(seconds=1))
        affected = OwnershipDomain.PUMP
    else:
        evidence = replace(
            evidence,
            effective_heat_source=w.PhysicalHeatMode.OFF,
            heat_source_observed_at=w.NOW + timedelta(seconds=1),
        )
        affected = OwnershipDomain.THERMAL
    manager.evaluate(evidence)
    assert manager.state.status is ThermalRuntimeOwnershipStatus.OWNED
    state = manager.state.lease.domain_state(affected)
    prior = owned.domain_state(affected)
    assert state.authority == prior.authority
    assert manager.state.lease.pump_setpoint == owned.pump_setpoint
    assert manager.state.lease.heat_source == owned.heat_source
    assert state.observed_at == prior.observed_at
    assert state.observed_value == prior.observed_value
    assert state.episode == prior.episode
    assert state.evidence_kind is OwnershipEvidenceKind.STALE_OR_OLD_GENERATION_CONSEQUENCE
    assert state.command_blocker is not None


def test_same_captured_evidence_can_evaluate_new_policy_without_snapshot_conflict():
    orchestrator = o.ThermalRuntimeOrchestrator()
    observations = o._observations(o.NOW)
    first = orchestrator.refresh(
        generated_at=o.NOW,
        observations=observations,
        thermal=o._thermal(o.NOW),
        evidence_identity="captured-1",
    )
    second = orchestrator.refresh(
        generated_at=o.NOW,
        observations=observations,
        thermal=o._thermal(o.NOW, pool_evaluation="new-policy-eval", pool_plan="new-policy-plan"),
        evidence_identity="captured-1",
    )
    assert second.blocking_reason != "thermal_orchestration_snapshot_conflict"
    assert second.pool_evaluation_id == "new-policy-eval"
    assert second.snapshot_identity != first.snapshot_identity
    assert orchestrator.ownership.state.lease is None


def test_same_claimed_evidence_identity_cannot_change_its_facts():
    orchestrator = o.ThermalRuntimeOrchestrator()
    orchestrator.refresh(
        generated_at=o.NOW,
        observations=o._observations(o.NOW),
        thermal=o._thermal(o.NOW),
        evidence_identity="captured-1",
    )
    result = orchestrator.refresh(
        generated_at=o.NOW,
        observations=o._observations(o.NOW, spa_active=True),
        thermal=o._thermal(o.NOW),
        evidence_identity="captured-1",
    )
    assert result.blocking_reason == "thermal_orchestration_snapshot_conflict"
    assert result.candidate_id is None


def test_distinct_captured_inputs_at_equal_clock_are_not_identity_conflicts():
    orchestrator = o.ThermalRuntimeOrchestrator()
    orchestrator.refresh(
        generated_at=o.NOW,
        observations=o._observations(o.NOW),
        thermal=o._thermal(o.NOW),
        evidence_identity="captured-1",
    )
    result = orchestrator.refresh(
        generated_at=o.NOW,
        observations=o._observations(o.NOW, spa_active=True),
        thermal=o._thermal(o.NOW),
        evidence_identity="captured-2",
    )
    assert result.blocking_reason != "thermal_orchestration_snapshot_conflict"
    assert orchestrator.ownership.state.lease is None
    assert result.candidate_id is None  # contradictory topology still denies commands


@pytest.mark.parametrize(
    "domain, concept", [("pump", "pump.rpm"), ("thermal", "pool.raw_heater_id")]
)
def test_positive_current_operator_intent_wins_despite_old_body_fact(domain, concept):
    import test_thermal_runtime_ownership as w
    from poolos.ownership_evidence import (
        OwnershipAuthority,
        OwnershipDomain,
        PositiveOperatorEvidence,
    )

    manager = w.full_manager()
    lease = manager.state.lease
    affected = OwnershipDomain(domain)
    at = w.NOW + timedelta(seconds=1)
    event = replace(
        w.external_event(concept, 2900, 3200, observed_at=at),
        positive_operator_evidence=PositiveOperatorEvidence(
            "operator-current",
            lease.body_session_generation,
            lease.body_session_id,
            affected,
            concept,
            at,
        ),
    )
    manager.evaluate(
        replace(
            w.evidence(at=at, pool_active=False, changes=w.ExternalChangeBatch((event,))),
            pool_activity_observed_at=w.NOW - timedelta(seconds=1),
        )
    )
    current = manager.state.lease
    assert current.domain_state(affected).authority is OwnershipAuthority.OPERATOR
    assert current.body_activation == lease.body_activation
    assert current.status is ThermalRuntimeOwnershipStatus.OWNED


@pytest.mark.parametrize("old_body_fact", [True, False])
@pytest.mark.parametrize("spa_active", [True, False])
def test_filtration_old_body_fact_cannot_preempt_newer_verified_acquisition(
    old_body_fact, spa_active
):
    driver, _, _ = f._enabled_driver()
    registry = driver.ownership
    delivery = f._Delivery([])
    factory = f._Factory(delivery)
    for seconds, active, rpm in [(0, False, 0), (1, True, 0), (2, True, 2600)]:
        asyncio.run(
            driver.process_epoch(
                f._frame(f.NOW + timedelta(seconds=seconds), pool=active, rpm=rpm, configured=2600),
                delivery_factory=factory,
            )
        )
    lease = registry.filtration_lease
    assert lease is not None and lease.verified
    frame = f._frame(
        f.NOW + timedelta(seconds=3), pool=False, spa=spa_active, rpm=2600, configured=2600
    )
    if old_body_fact:
        frame = replace(
            frame,
            observations=tuple(
                replace(item, observed_at=f.NOW - timedelta(seconds=1))
                if item.observation_id in {"pool.active", "spa.active"}
                else item
                for item in frame.observations
            ),
        )
    result = asyncio.run(driver.process_epoch(frame, delivery_factory=factory))
    if old_body_fact:
        assert registry.filtration_lease is not None
        assert registry.filtration_lease.body_activation == lease.body_activation
        assert driver.session_id == lease.session_id
        assert result.command_delivery_performed is False
    else:
        assert registry.filtration_lease is None or driver.session_id is None
    assert len(delivery.operations) == 2


def test_vendor_read_reply_keeps_request_start_when_applied_later(monkeypatch):
    module = t._load_module(monkeypatch)
    clock = [t.NOW]

    class Clock(datetime):
        @classmethod
        def now(cls, tz=None):
            return clock[0]

    monkeypatch.setattr(module, "datetime", Clock)
    transport = module.IndependentIntelliCenterReadOnlyTransport(host="192.0.2.10")
    asyncio.run(transport.async_start())

    async def delayed_vendor_send(self, cmd, extra=None):
        clock[0] += timedelta(seconds=1)
        return {"objectList": [{"objnam": "B1101", "params": {"STATUS": "ON"}}]}

    monkeypatch.setattr(type(transport._controller).__mro__[1], "send_cmd", delayed_vendor_send)
    response = asyncio.run(transport._controller.send_cmd("RequestParamList", {"objectList": []}))
    # pyintellicenter's startup/new-object monitoring applies the returned list
    # separately after send_cmd returns. It must not acquire completion time.
    transport._controller._apply_updates(response["objectList"])
    assert clock[0] > t.NOW
    assert transport._attribute_observed_at[("B1101", "STATUS")] == t.NOW
