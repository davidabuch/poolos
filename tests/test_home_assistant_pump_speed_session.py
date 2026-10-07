from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime, timedelta
import importlib.util
from pathlib import Path
import sys
from types import ModuleType

from poolos.external_change import (
    ExternalChangeBatch,
    ExternalChangeEvent,
    ExternalChangePolicy,
    ExternalSemanticEventType,
)
from poolos.intellicenter_readonly import (
    NativeIntelliCenterObservationSnapshot,
    NativeIntelliCenterStatus,
    NativeIntelliCenterTransportSnapshot,
    NativePumpState,
    NativeRawAttribute,
    NativeRawObject,
    POOL_PUMP_CIRCUIT_CONFIGURED_SPEED_CONCEPT,
    POOL_PUMP_CIRCUIT_CONFIGURED_MODE_CONCEPT,
    POOL_PUMP_CIRCUIT_CONFIGURED_FLOW_CONCEPT,
    SPA_PUMP_CIRCUIT_CONFIGURED_SPEED_CONCEPT,
)
from poolos.ownership_evidence import OwnershipDomain, PositiveOperatorEvidence
from poolos.observations import (
    ObservationQuality,
    ObservationSourceKind,
    PoolObservation,
)
from poolos.operating_baselines import PumpOperatingBaselines
from poolos.pump_operating_target import (
    PumpOperatingTarget,
    PumpOperatingTargetPolicy,
    PumpTargetUnit,
)
from poolos.physical_command_authority import (
    NativeConsequenceAttribution,
    PhysicalRequestSource,
    PoolOSPhysicalCommandAuthority,
)
from poolos.pump_speed_session import (
    PumpSpeedOverrideSource,
    PumpSpeedOverrideState,
    PumpSpeedSessionBody,
    PumpSpeedSessionPurpose,
    PumpSpeedSessionRuntime,
)
from poolos.pump_target_session import PumpTargetSessionRuntime


NOW = datetime(2026, 9, 10, 17, 0, tzinfo=UTC)
ROOT = Path(__file__).resolve().parents[1]
PACKAGE = "_poolos_pump_session_ha_test"


def _runtime_class():
    package = sys.modules.get(PACKAGE)
    if package is None:
        package = ModuleType(PACKAGE)
        package.__path__ = [str(ROOT / "custom_components" / "poolos")]  # type: ignore[attr-defined]
        sys.modules[PACKAGE] = package
    name = f"{PACKAGE}.pump_speed_session"
    if module := sys.modules.get(name):
        return module.PoolOSPumpSpeedSessionRuntime
    path = ROOT / "custom_components" / "poolos" / "pump_speed_session.py"
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module.PoolOSPumpSpeedSessionRuntime


PoolOSPumpSpeedSessionRuntime = _runtime_class()


def _observation(concept: str, value: object, *, at: datetime = NOW) -> PoolObservation:
    source = (
        "p0102"
        if concept
        in {
            POOL_PUMP_CIRCUIT_CONFIGURED_SPEED_CONCEPT,
            POOL_PUMP_CIRCUIT_CONFIGURED_MODE_CONCEPT,
            POOL_PUMP_CIRCUIT_CONFIGURED_FLOW_CONCEPT,
        }
        else concept
    )
    return PoolObservation(
        concept,
        value,
        observed_at=at,
        source_kind=ObservationSourceKind.LIVE,
        source_id=f"intellicenter_native:native:{source}",
        quality=ObservationQuality.GOOD,
        confidence=1.0,
    )


def _native(
    *,
    at: datetime = NOW,
    configured: int = 2900,
    solar: bool = False,
) -> NativeIntelliCenterObservationSnapshot:
    values = {
        "intellicenter.system_mode": "auto",
        "pool.active": True,
        "spa.active": False,
        "pool.raw_heater_id": "H0002",
        "solar.active": solar,
        "heater.active": False,
        POOL_PUMP_CIRCUIT_CONFIGURED_SPEED_CONCEPT: configured,
    }
    return NativeIntelliCenterObservationSnapshot(
        generated_at=at,
        status=NativeIntelliCenterStatus.AVAILABLE,
        source_id="native",
        observations=tuple(
            _observation(concept, value, at=at) for concept, value in values.items()
        ),
        missing_concepts=(),
    )


def _transport(*, at: datetime = NOW, configured: int = 2900) -> NativeIntelliCenterTransportSnapshot:
    raw = NativeRawObject(
        native_id="p0102",
        object_type="PMPCIRC",
        subtype=None,
        name="Pool",
        parent_id="PMP01",
        observed_at=at,
        attributes=(
            NativeRawAttribute("CIRCUIT", "C0006"),
            NativeRawAttribute("SELECT", "RPM"),
            NativeRawAttribute("PARENT", "PMP01"),
            NativeRawAttribute("SPEED", str(configured)),
        ),
    )
    return NativeIntelliCenterTransportSnapshot(
        source_id="native",
        observed_at=at,
        connected=True,
        temperature_unit="°F",
        pumps=(
            NativePumpState(
                "PMP01",
                "Pump",
                True,
                float(configured),
                None,
                None,
                450.0,
                3450.0,
            ),
        ),
        raw_inventory=(raw,),
    )


def _gpm_policy() -> PumpOperatingTargetPolicy:
    legacy = PumpOperatingTargetPolicy.from_rpm_baselines(PumpOperatingBaselines())
    return PumpOperatingTargetPolicy(
        filtration=PumpOperatingTarget(PumpTargetUnit.GPM, 42),
        solar_heating=PumpOperatingTarget(PumpTargetUnit.GPM, 48),
        gas_heating=PumpOperatingTarget(PumpTargetUnit.GPM, 55),
        temperature_probe=legacy.temperature_probe,
        priming=legacy.priming,
        grid_outage=legacy.grid_outage,
        sanitation=legacy.sanitation,
        spillway=legacy.spillway,
    )


def _gpm_native(
    *,
    at: datetime = NOW,
    configured: int = 42,
    solar: bool = False,
) -> NativeIntelliCenterObservationSnapshot:
    values = {
        "intellicenter.system_mode": "auto",
        "pool.active": True,
        "spa.active": False,
        "pool.raw_heater_id": "H0002",
        "solar.active": solar,
        "heater.active": False,
        POOL_PUMP_CIRCUIT_CONFIGURED_MODE_CONCEPT: "gpm",
        POOL_PUMP_CIRCUIT_CONFIGURED_FLOW_CONCEPT: configured,
    }
    return NativeIntelliCenterObservationSnapshot(
        generated_at=at,
        status=NativeIntelliCenterStatus.AVAILABLE,
        source_id="native",
        observations=tuple(
            _observation(concept, value, at=at) for concept, value in values.items()
        ),
        missing_concepts=(),
    )


def _gpm_transport(
    *,
    at: datetime = NOW,
    configured: int = 42,
) -> NativeIntelliCenterTransportSnapshot:
    raw = NativeRawObject(
        native_id="p0102",
        object_type="PMPCIRC",
        subtype=None,
        name="Pool",
        parent_id="PMP01",
        observed_at=at,
        attributes=(
            NativeRawAttribute("CIRCUIT", "C0006"),
            NativeRawAttribute("SELECT", "GPM"),
            NativeRawAttribute("PARENT", "PMP01"),
            NativeRawAttribute("SPEED", str(configured)),
        ),
    )
    return NativeIntelliCenterTransportSnapshot(
        source_id="native",
        observed_at=at,
        connected=True,
        temperature_unit="°F",
        pumps=(
            NativePumpState(
                "PMP01",
                "Pump",
                True,
                2100.0,
                float(configured),
                None,
                450.0,
                3450.0,
                15.0,
                140.0,
            ),
        ),
        raw_inventory=(raw,),
    )


def _gpm_event(*, at: datetime, before: int, after: int) -> ExternalChangeEvent:
    return ExternalChangeEvent(
        concept=POOL_PUMP_CIRCUIT_CONFIGURED_FLOW_CONCEPT,
        semantic_event_type=ExternalSemanticEventType.NATIVE_VALUE_CHANGED,
        native_object_id="p0102",
        previous_value=float(before),
        new_value=float(after),
        observed_at=at,
        external_policy=ExternalChangePolicy.ACCEPT,
        action_taken="accepted_native_value",
        notification_recommended=False,
        reconciliation_required=False,
        positive_operator_evidence=PositiveOperatorEvidence(
            request_id="native-operator:gpm",
            authority_generation=8,
            body_session_id="pool-session-8",
            domain=OwnershipDomain.PUMP,
            equipment_id="pump.gpm",
            requested_at=at,
        ),
    )


def _event(*, at: datetime, before: int, after: int) -> ExternalChangeEvent:
    return ExternalChangeEvent(
        concept=POOL_PUMP_CIRCUIT_CONFIGURED_SPEED_CONCEPT,
        semantic_event_type=ExternalSemanticEventType.NATIVE_VALUE_CHANGED,
        native_object_id="p0102",
        previous_value=float(before),
        new_value=float(after),
        observed_at=at,
        external_policy=ExternalChangePolicy.ACCEPT,
        action_taken="accepted_native_value",
        notification_recommended=False,
        reconciliation_required=False,
    )


def _spa_native(*, at: datetime = NOW, configured: int = 2600) -> NativeIntelliCenterObservationSnapshot:
    values = {
        "intellicenter.system_mode": "auto",
        "pool.active": False,
        "spa.active": True,
        "spa.raw_heater_id": "00000",
        "solar.active": False,
        "heater.active": False,
        "spa.heating_demand_active": False,
        SPA_PUMP_CIRCUIT_CONFIGURED_SPEED_CONCEPT: configured,
    }
    return NativeIntelliCenterObservationSnapshot(
        generated_at=at,
        status=NativeIntelliCenterStatus.AVAILABLE,
        source_id="native",
        observations=tuple(
            _observation(concept, value, at=at) for concept, value in values.items()
        ),
        missing_concepts=(),
    )


def _spa_transport(*, at: datetime = NOW, configured: int = 2600) -> NativeIntelliCenterTransportSnapshot:
    raw = NativeRawObject(
        native_id="p0198",
        object_type="PMPCIRC",
        subtype=None,
        name="Spa",
        parent_id="PMP01",
        observed_at=at,
        attributes=(
            NativeRawAttribute("CIRCUIT", "C0001"),
            NativeRawAttribute("SELECT", "RPM"),
            NativeRawAttribute("PARENT", "PMP01"),
            NativeRawAttribute("SPEED", str(configured)),
        ),
    )
    return replace(_transport(at=at, configured=configured), raw_inventory=(raw,))


def test_gpm_policy_uses_unit_aware_session_and_retires_legacy_rpm_binding() -> None:
    baselines = PumpOperatingBaselines()
    authority = PoolOSPhysicalCommandAuthority(baselines=baselines)
    target_session = PumpTargetSessionRuntime(_gpm_policy())
    runtime = PoolOSPumpSpeedSessionRuntime(
        PumpSpeedSessionRuntime(baselines),
        authority,
        target_session,
    )

    runtime.synchronize(_gpm_native(), _gpm_transport(), connection_generation=1)

    target_state = target_session.snapshot
    assert target_state.active
    assert target_state.purpose is PumpSpeedSessionPurpose.ORDINARY
    assert target_state.effective_target == PumpOperatingTarget(PumpTargetUnit.GPM, 42)
    assert runtime.session.snapshot.active is False
    assert authority._pump_session_binding is None
    assert authority.diagnostics(now=NOW)["pump_target_session_binding"] == {
        "session_id": target_state.session_id,
        "body": "pool",
        "purpose": "ordinary_circulation",
        "pump_circuit_id": "p0102",
        "unit": "gpm",
        "value": 42,
    }


def test_gpm_configured_flow_change_is_session_scoped_operator_override() -> None:
    baselines = PumpOperatingBaselines()
    authority = PoolOSPhysicalCommandAuthority(baselines=baselines)
    target_session = PumpTargetSessionRuntime(_gpm_policy())
    runtime = PoolOSPumpSpeedSessionRuntime(
        PumpSpeedSessionRuntime(baselines),
        authority,
        target_session,
    )
    runtime.synchronize(_gpm_native(), _gpm_transport(), connection_generation=1)

    at = NOW + timedelta(seconds=1)
    changed = _gpm_native(at=at, configured=50)
    runtime.synchronize(
        changed,
        _gpm_transport(at=at, configured=50),
        connection_generation=1,
    )
    runtime.apply_external_changes(
        ExternalChangeBatch((_gpm_event(at=at, before=42, after=50),)),
        changed,
    )

    state = target_session.snapshot
    assert state.override_state is PumpSpeedOverrideState.VERIFIED
    assert state.override_source is PumpSpeedOverrideSource.EXTERNAL_UNATTRIBUTED
    assert state.effective_target == PumpOperatingTarget(PumpTargetUnit.GPM, 50)


def test_all_rpm_policy_keeps_existing_ha_session_and_authority_path() -> None:
    baselines = PumpOperatingBaselines(filtration_rpm=2650)
    authority = PoolOSPhysicalCommandAuthority(baselines=baselines)
    target_session = PumpTargetSessionRuntime(
        PumpOperatingTargetPolicy.from_rpm_baselines(baselines)
    )
    runtime = PoolOSPumpSpeedSessionRuntime(
        PumpSpeedSessionRuntime(baselines),
        authority,
        target_session,
    )

    runtime.synchronize(
        _native(configured=2650),
        _transport(configured=2650),
        connection_generation=1,
    )

    assert runtime.session.snapshot.active
    assert runtime.session.snapshot.effective_rpm == 2650
    assert authority._pump_session_binding is not None
    assert authority._pump_session_binding[4] == 2650
    assert authority.diagnostics(now=NOW)["pump_target_session_binding"]["unit"] == "rpm"


def test_ha_adapter_established_configured_speed_transition_is_manual_override() -> None:
    baselines = PumpOperatingBaselines(filtration_rpm=2650)
    authority = PoolOSPhysicalCommandAuthority(baselines=baselines)
    runtime = PoolOSPumpSpeedSessionRuntime(
        PumpSpeedSessionRuntime(baselines), authority
    )
    runtime.synchronize(_native(), _transport(), connection_generation=1)
    assert runtime.session.snapshot.purpose is PumpSpeedSessionPurpose.ORDINARY
    assert runtime.session.snapshot.override_state is PumpSpeedOverrideState.NONE
    assert runtime.session.snapshot.effective_rpm == 2650

    at = NOW + timedelta(seconds=1)
    changed = _native(at=at, configured=3200)
    runtime.synchronize(changed, _transport(at=at, configured=3200), connection_generation=1)
    runtime.apply_external_changes(
        ExternalChangeBatch((_event(at=at, before=2900, after=3200),)),
        changed,
    )
    assert runtime.session.snapshot.override_state is PumpSpeedOverrideState.VERIFIED
    assert (
        runtime.session.snapshot.override_source
        is PumpSpeedOverrideSource.EXTERNAL_UNATTRIBUTED
    )
    assert runtime.session.snapshot.effective_rpm == 3200
    assert runtime.session.snapshot.last_override_transition_reason == (
        "external_configured_speed_override_verified"
    )

    handback_at = NOW + timedelta(seconds=2)
    baseline = _native(at=handback_at, configured=2650)
    runtime.synchronize(
        baseline,
        _transport(at=handback_at, configured=2650),
        connection_generation=1,
    )
    runtime.apply_external_changes(
        ExternalChangeBatch(
            (_event(at=handback_at, before=3200, after=2650),)
        ),
        baseline,
    )
    assert runtime.session.snapshot.override_state is PumpSpeedOverrideState.NONE
    assert runtime.session.snapshot.effective_rpm == 2650
    assert runtime.session.snapshot.last_override_transition_reason == (
        "external_configured_speed_returned_to_baseline"
    )


def test_hot_tub_session_uses_only_exact_spa_pump_circuit() -> None:
    baselines = PumpOperatingBaselines(filtration_rpm=2650)
    authority = PoolOSPhysicalCommandAuthority(baselines=baselines)
    runtime = PoolOSPumpSpeedSessionRuntime(PumpSpeedSessionRuntime(baselines), authority)
    runtime.synchronize(_spa_native(), _spa_transport(), connection_generation=1)

    state = runtime.session.snapshot
    assert state.body is PumpSpeedSessionBody.HOT_TUB
    assert state.purpose is PumpSpeedSessionPurpose.ORDINARY
    assert state.pump_circuit_id == "p0198"
    assert state.effective_rpm == 2650

    wrong = ExternalChangeEvent(
        concept=SPA_PUMP_CIRCUIT_CONFIGURED_SPEED_CONCEPT,
        semantic_event_type=ExternalSemanticEventType.NATIVE_VALUE_CHANGED,
        native_object_id="p0102",
        previous_value=2600,
        new_value=3200,
        observed_at=NOW + timedelta(seconds=1),
        external_policy=ExternalChangePolicy.ACCEPT,
        action_taken="accepted_native_value",
        notification_recommended=False,
        reconciliation_required=False,
    )
    runtime.apply_external_changes(
        ExternalChangeBatch((wrong,)),
        _spa_native(at=NOW + timedelta(seconds=1), configured=3200),
    )
    assert runtime.session.snapshot.override_state is PumpSpeedOverrideState.NONE


def test_hot_tub_dynamic_pmpcirc_reassignment_preserves_fresh_operator_override() -> None:
    baselines = PumpOperatingBaselines(filtration_rpm=2600, solar_heating_rpm=2900)
    authority = PoolOSPhysicalCommandAuthority(baselines=baselines)
    runtime = PoolOSPumpSpeedSessionRuntime(PumpSpeedSessionRuntime(baselines), authority)

    initial = replace(
        _spa_native(configured=2900),
        observations=tuple(
            replace(item, value=True)
            if item.observation_id == "solar.active"
            else replace(item, value="H0002")
            if item.observation_id == "spa.raw_heater_id"
            else item
            for item in _spa_native(configured=2900).observations
        ),
    )
    runtime.synchronize(initial, _spa_transport(configured=2900), connection_generation=1)
    assert runtime.session.snapshot.pump_circuit_id == "p0198"
    assert runtime.session.snapshot.purpose is PumpSpeedSessionPurpose.SOLAR

    at = NOW + timedelta(seconds=1)
    reassigned_raw = NativeRawObject(
        native_id="p0101",
        object_type="PMPCIRC",
        subtype=None,
        name="Spa",
        parent_id="PMP01",
        observed_at=at,
        attributes=(
            NativeRawAttribute("CIRCUIT", "C0001"),
            NativeRawAttribute("SELECT", "RPM"),
            NativeRawAttribute("PARENT", "PMP01"),
            NativeRawAttribute("SPEED", "3200"),
        ),
    )
    changed_transport = replace(
        _transport(at=at, configured=3200),
        raw_inventory=(reassigned_raw,),
    )
    changed = replace(
        _spa_native(at=at, configured=3200),
        observations=tuple(
            replace(item, value=True)
            if item.observation_id == "solar.active"
            else replace(item, value="H0002")
            if item.observation_id == "spa.raw_heater_id"
            else item
            for item in _spa_native(at=at, configured=3200).observations
        ),
    )

    runtime.synchronize(changed, changed_transport, connection_generation=1)
    assert runtime.session.snapshot.pump_circuit_id == "p0101"
    assert runtime.session.snapshot.override_state is PumpSpeedOverrideState.NONE

    event = ExternalChangeEvent(
        concept=SPA_PUMP_CIRCUIT_CONFIGURED_SPEED_CONCEPT,
        semantic_event_type=ExternalSemanticEventType.NATIVE_VALUE_CHANGED,
        native_object_id="p0101",
        previous_value=2900,
        new_value=3200,
        observed_at=at,
        external_policy=ExternalChangePolicy.ACCEPT,
        action_taken="accepted_native_value",
        notification_recommended=False,
        reconciliation_required=False,
        positive_operator_evidence=PositiveOperatorEvidence(
            request_id="native-operator:test",
            authority_generation=7,
            body_session_id="spa-session-7",
            domain=OwnershipDomain.PUMP,
            equipment_id="pump.rpm",
            requested_at=at,
        ),
    )
    runtime.apply_external_changes(ExternalChangeBatch((event,)), changed)

    state = runtime.session.snapshot
    assert state.pump_circuit_id == "p0101"
    assert state.override_state is PumpSpeedOverrideState.VERIFIED
    assert state.override_source is PumpSpeedOverrideSource.EXTERNAL_UNATTRIBUTED
    assert state.effective_rpm == 3200


def test_same_frame_actual_purpose_transition_wins_over_rpm_transition() -> None:
    baselines = PumpOperatingBaselines(filtration_rpm=2650, solar_heating_rpm=2950)
    authority = PoolOSPhysicalCommandAuthority(baselines=baselines)
    runtime = PoolOSPumpSpeedSessionRuntime(PumpSpeedSessionRuntime(baselines), authority)
    runtime.synchronize(_native(), _transport(), connection_generation=1)

    at = NOW + timedelta(seconds=1)
    solar = _native(at=at, configured=3200, solar=True)
    runtime.synchronize(solar, _transport(at=at, configured=3200), connection_generation=1)
    runtime.apply_external_changes(
        ExternalChangeBatch((_event(at=at, before=2900, after=3200),)),
        solar,
    )
    state = runtime.session.snapshot
    assert state.purpose is PumpSpeedSessionPurpose.SOLAR
    assert state.override_state is PumpSpeedOverrideState.NONE
    assert state.effective_rpm == 2950


def test_poolos_expected_consequence_verifies_pending_without_external_adoption() -> None:
    baselines = PumpOperatingBaselines(filtration_rpm=2650)
    authority = PoolOSPhysicalCommandAuthority(baselines=baselines)
    runtime = PoolOSPumpSpeedSessionRuntime(PumpSpeedSessionRuntime(baselines), authority)
    runtime.synchronize(_native(configured=2650), _transport(configured=2650), connection_generation=1)
    request = runtime.session.begin_manual_request(
        body=PumpSpeedSessionBody.POOL,
        pump_circuit_id="p0102",
        requested_rpm=3200,
        requested_at=NOW + timedelta(milliseconds=100),
        request_id="manual-request",
    )
    runtime.session.manual_delivery_accepted(
        request, accepted_at=NOW + timedelta(milliseconds=200)
    )
    at = NOW + timedelta(seconds=1)
    changed = _native(at=at, configured=3200)
    runtime.synchronize(changed, _transport(at=at, configured=3200), connection_generation=1)
    runtime.apply_external_changes(
        ExternalChangeBatch(
            (),
            (
                NativeConsequenceAttribution(
                    "expectation",
                    "manual-request",
                    PhysicalRequestSource.MANUAL,
                    "pump_circuit_speed",
                    "p0102",
                ),
            ),
        ),
        changed,
    )
    assert runtime.session.snapshot.override_state is PumpSpeedOverrideState.VERIFIED
    assert runtime.session.snapshot.override_source is PumpSpeedOverrideSource.POOLOS_MANUAL


def test_reconnect_generation_reanchors_matching_hardware_without_override() -> None:
    baselines = PumpOperatingBaselines(filtration_rpm=2650)
    authority = PoolOSPhysicalCommandAuthority(baselines=baselines)
    runtime = PoolOSPumpSpeedSessionRuntime(PumpSpeedSessionRuntime(baselines), authority)
    runtime.synchronize(_native(configured=3200), _transport(configured=3200), connection_generation=1)
    at = NOW + timedelta(seconds=1)
    runtime.apply_external_changes(
        ExternalChangeBatch((_event(at=at, before=3200, after=3300),)),
        _native(at=at, configured=3300),
    )
    assert runtime.session.snapshot.effective_rpm == 3300

    later = NOW + timedelta(seconds=2)
    runtime.synchronize(
        _native(at=later, configured=3300),
        _transport(at=later, configured=3300),
        connection_generation=2,
    )
    assert runtime.session.snapshot.override_state is PumpSpeedOverrideState.NONE
    assert runtime.session.snapshot.effective_rpm == 2650


def test_stale_native_frame_cannot_establish_or_verify_session_override() -> None:
    baselines = PumpOperatingBaselines(filtration_rpm=2650)
    authority = PoolOSPhysicalCommandAuthority(baselines=baselines)
    runtime = PoolOSPumpSpeedSessionRuntime(PumpSpeedSessionRuntime(baselines), authority)
    stale = replace(_native(configured=3200), generated_at=NOW + timedelta(seconds=31))
    runtime.synchronize(
        stale,
        _transport(configured=3200),
        connection_generation=1,
    )
    assert runtime.session.snapshot.active is False
    assert runtime.session.snapshot.override_state is PumpSpeedOverrideState.NONE


def test_unusable_frame_preserves_session_but_clears_physical_binding() -> None:
    baselines = PumpOperatingBaselines(filtration_rpm=2650)
    authority = PoolOSPhysicalCommandAuthority(baselines=baselines)
    runtime = PoolOSPumpSpeedSessionRuntime(PumpSpeedSessionRuntime(baselines), authority)
    runtime.synchronize(
        _native(configured=2650),
        _transport(configured=2650),
        connection_generation=1,
    )
    session_id = runtime.session.snapshot.session_id
    assert session_id is not None
    later = NOW + timedelta(seconds=31)
    stale = replace(
        _native(at=later, configured=2650),
        observations=tuple(
            replace(item, observed_at=NOW)
            if item.observation_id == "pool.active"
            else item
            for item in _native(at=later, configured=2650).observations
        ),
    )

    runtime.synchronize(
        stale,
        _transport(at=later, configured=2650),
        connection_generation=1,
    )

    assert runtime.session.snapshot.session_id == session_id
    assert runtime.session.snapshot.evidence_usable is False
    assert authority._pump_session_binding is None


def test_controller_mode_loss_clears_pending_intent_before_auto_returns() -> None:
    baselines = PumpOperatingBaselines(filtration_rpm=2650)
    authority = PoolOSPhysicalCommandAuthority(baselines=baselines)
    runtime = PoolOSPumpSpeedSessionRuntime(PumpSpeedSessionRuntime(baselines), authority)
    runtime.synchronize(_native(configured=2650), _transport(configured=2650), connection_generation=1)
    runtime.session.begin_manual_request(
        body=PumpSpeedSessionBody.POOL,
        pump_circuit_id="p0102",
        requested_rpm=3200,
        requested_at=NOW + timedelta(milliseconds=100),
        request_id="stale-mode-request",
    )

    service = replace(
        _native(at=NOW + timedelta(seconds=1), configured=3200),
        observations=tuple(
            replace(item, value="service")
            if item.observation_id == "intellicenter.system_mode"
            else item
            for item in _native(at=NOW + timedelta(seconds=1), configured=3200).observations
        ),
    )
    runtime.synchronize(
        service,
        _transport(at=NOW + timedelta(seconds=1), configured=3200),
        connection_generation=1,
    )
    assert runtime.session.snapshot.active is False

    runtime.synchronize(
        _native(at=NOW + timedelta(seconds=2), configured=3200),
        _transport(at=NOW + timedelta(seconds=2), configured=3200),
        connection_generation=1,
    )
    assert runtime.session.snapshot.override_state is PumpSpeedOverrideState.NONE
    assert runtime.session.snapshot.effective_rpm == 2650
