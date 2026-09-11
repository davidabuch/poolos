from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import pytest

from poolos.external_change import (
    ExternalChangeBatch,
    ExternalChangeEvent,
    ExternalChangePolicy,
    ExternalSemanticEventType,
)
from poolos.grid_outage_confirmation import GridOutageDisposition
from poolos.integration import PhysicalHeatMode, ThermalBody
from poolos.observations import ObservationQuality, ObservationSourceKind, PoolObservation
from poolos.thermal_live_execution import (
    ThermalLiveExecutionContext,
    ThermalLiveExecutionOwnership,
)
from poolos.thermal_runtime_assessment import ThermalRequestedMode
from poolos.thermal_runtime_orchestration import (
    ThermalOrchestrationLifecycle,
    ThermalRuntimeOrchestrator,
    assess_pool_temperature_probe_continuity,
)
from poolos.thermal_runtime_ownership import ThermalRuntimeOwnershipStatus


NOW = datetime(2026, 9, 4, 12, 0, tzinfo=UTC)
ROOT = Path(__file__).resolve().parents[1]


def _observation(
    concept: str,
    value: object,
    *,
    at: datetime,
    quality: ObservationQuality = ObservationQuality.GOOD,
    confidence: float = 1.0,
    source_kind: ObservationSourceKind = ObservationSourceKind.LIVE,
) -> PoolObservation:
    source = (
        "home_assistant:binary_sensor.1_powerwall_grid_status"
        if concept == "grid.outage_active"
        else f"native:{concept}"
    )
    return PoolObservation(
        observation_id=concept,
        value=value,
        observed_at=at,
        source_kind=source_kind,
        source_id=source,
        quality=quality,
        confidence=confidence,
    )


def _observations(
    at: datetime,
    *,
    pool_active: object = True,
    spa_active: object = False,
    pump_rpm: object = 2900,
    configured_rpm: object = 2900,
    pool_heater: object = "H0002",
    spa_heater: object = "00000",
    outage: object = False,
    waterfall: object = False,
    jets: object = False,
    slide: object = False,
    omit: frozenset[str] = frozenset(),
) -> tuple[PoolObservation, ...]:
    values = {
        "pool.active": pool_active,
        "spa.active": spa_active,
        "pump.rpm": pump_rpm,
        "pool.pump_circuit.configured_speed_rpm": configured_rpm,
        "pool.raw_heater_id": pool_heater,
        "spa.raw_heater_id": spa_heater,
        "grid.outage_active": outage,
        "waterfall.active": waterfall,
        "jets.active": jets,
        "slide.active": slide,
    }
    return tuple(
        _observation(concept, value, at=at)
        for concept, value in values.items()
        if concept not in omit
    )


def _body(
    body: ThermalBody,
    *,
    evaluation_id: str,
    plan_id: str,
    mode: ThermalRequestedMode,
    authorized: bool,
):
    return SimpleNamespace(
        body=body,
        evaluation_id=evaluation_id,
        plan=SimpleNamespace(plan_id=plan_id),
        requested_mode=mode,
        actual_authorization=SimpleNamespace(authorized=authorized),
    )


def _thermal(
    at: datetime,
    *,
    pool_evaluation: str = "pool-eval-1",
    pool_plan: str = "pool-plan-1",
    pool_mode: ThermalRequestedMode = ThermalRequestedMode.SOLAR,
    pool_authorized: bool = True,
    spa_evaluation: str = "spa-eval-1",
    spa_plan: str = "spa-plan-1",
    spa_mode: ThermalRequestedMode = ThermalRequestedMode.SOLAR_PREFERRED,
    spa_authorized: bool = False,
):
    return SimpleNamespace(
        generated_at=at,
        pool=_body(
            ThermalBody.POOL,
            evaluation_id=pool_evaluation,
            plan_id=pool_plan,
            mode=pool_mode,
            authorized=pool_authorized,
        ),
        hot_tub=_body(
            ThermalBody.HOT_TUB,
            evaluation_id=spa_evaluation,
            plan_id=spa_plan,
            mode=spa_mode,
            authorized=spa_authorized,
        ),
    )


def _refresh(
    orchestrator: ThermalRuntimeOrchestrator,
    at: datetime,
    *,
    thermal=None,
    observations: tuple[PoolObservation, ...] | None = None,
):
    return orchestrator.refresh(
        generated_at=at,
        observations=_observations(at) if observations is None else observations,
        thermal=_thermal(at) if thermal is None else thermal,
    )


def _establish_pool_pump_ownership(
    orchestrator: ThermalRuntimeOrchestrator,
    *,
    at: datetime,
) -> None:
    provenance = ThermalLiveExecutionOwnership(
        evaluation_id="pool-eval-1",
        thermal_plan_id="pool-plan-1",
        execution_plan_id="execution-plan-1",
        target_body=ThermalBody.POOL,
        pump_operation_id="pump-operation-1",
        pump_receipt_id="pump-receipt-1",
        pump_correlation_id="pump-correlation-1",
        commanded_pump_rpm=2900,
    )
    decision = orchestrator.ownership.establish(
        provenance,
        established_at=at,
        requested_mode=ThermalRequestedMode.SOLAR.value,
        current_context=ThermalLiveExecutionContext(
            evaluation_id="pool-eval-1",
            plan_id="pool-plan-1",
        ),
    )
    assert decision.current_state.status is ThermalRuntimeOwnershipStatus.OWNED


def _establish_pool_full_ownership(
    orchestrator: ThermalRuntimeOrchestrator,
    *,
    at: datetime,
) -> None:
    provenance = ThermalLiveExecutionOwnership(
        evaluation_id="pool-eval-1",
        thermal_plan_id="pool-plan-1",
        execution_plan_id="execution-plan-1",
        target_body=ThermalBody.POOL,
        body_activation_operation_id="body-operation-1",
        body_activation_receipt_id="body-receipt-1",
        body_activation_correlation_id="body-correlation-1",
        pump_operation_id="pump-operation-1",
        pump_receipt_id="pump-receipt-1",
        pump_correlation_id="pump-correlation-1",
        commanded_pump_rpm=2900,
        heat_source_operation_id="source-operation-1",
        heat_source_receipt_id="source-receipt-1",
        heat_source_correlation_id="source-correlation-1",
        commanded_heat_source=PhysicalHeatMode.SOLAR,
    )
    decision = orchestrator.ownership.establish(
        provenance,
        established_at=at,
        requested_mode=ThermalRequestedMode.SOLAR.value,
        current_context=ThermalLiveExecutionContext(
            evaluation_id="pool-eval-1",
            plan_id="pool-plan-1",
        ),
    )
    assert decision.current_state.status is ThermalRuntimeOwnershipStatus.OWNED


def test_valid_current_assessment_creates_command_free_candidate() -> None:
    result = _refresh(ThermalRuntimeOrchestrator(), NOW)

    assert result.lifecycle is ThermalOrchestrationLifecycle.CANDIDATE_READY
    assert result.candidate_body is ThermalBody.POOL
    assert result.candidate_id is not None
    assert result.ownership_status is ThermalRuntimeOwnershipStatus.UNOWNED
    assert result.automatic_execution_driver_enabled is False
    assert result.command_delivery_performed is False


def test_owned_unchanged_native_state_remains_current_through_source_cadence() -> None:
    orchestrator = ThermalRuntimeOrchestrator()
    _establish_pool_full_ownership(orchestrator, at=NOW)

    result = _refresh(
        orchestrator,
        NOW + timedelta(seconds=120),
        observations=_observations(NOW),
    )

    assert result.lifecycle is ThermalOrchestrationLifecycle.OWNED
    assert result.ownership_status is ThermalRuntimeOwnershipStatus.OWNED


def test_owned_solar_accepts_asynchronous_per_concept_native_refreshes() -> None:
    orchestrator = ThermalRuntimeOrchestrator()
    _establish_pool_full_ownership(orchestrator, at=NOW)

    def observations_at(offsets: dict[str, int], evaluated_second: int):
        return tuple(
            _observation(
                item.observation_id,
                item.value,
                at=NOW
                + timedelta(seconds=offsets.get(item.observation_id, evaluated_second)),
            )
            for item in _observations(NOW + timedelta(seconds=evaluated_second))
        )

    first = _refresh(
        orchestrator,
        NOW + timedelta(seconds=100),
        observations=observations_at(
            {
                "pool.active": 100,
                "spa.active": 20,
                "pump.rpm": 1,
                "pool.pump_circuit.configured_speed_rpm": 10,
                "pool.raw_heater_id": 100,
            },
            100,
        ),
    )
    assert first.lifecycle is ThermalOrchestrationLifecycle.OWNED

    second = _refresh(
        orchestrator,
        NOW + timedelta(seconds=180),
        observations=observations_at(
            {
                "pool.active": 81,
                "spa.active": 100,
                "pump.rpm": 180,
                "pool.pump_circuit.configured_speed_rpm": 100,
                "pool.raw_heater_id": 150,
                "waterfall.active": 100,
                "jets.active": 100,
                "slide.active": 100,
            },
            180,
        ),
    )
    assert second.lifecycle is ThermalOrchestrationLifecycle.OWNED
    assert second.ownership_status is ThermalRuntimeOwnershipStatus.OWNED


@pytest.mark.parametrize(
    ("concept", "reason"),
    (
        ("pool.active", "runtime_ownership_preempted:pool_activity_stale"),
        ("spa.active", "runtime_ownership_preempted:spa_activity_stale"),
        ("pump.rpm", "runtime_ownership_preempted:pump_evidence_stale"),
        (
            "pool.pump_circuit.configured_speed_rpm",
            "runtime_ownership_preempted:pump_setpoint_evidence_stale",
        ),
        ("pool.raw_heater_id", "runtime_ownership_preempted:source_evidence_stale"),
    ),
)
def test_owned_native_state_beyond_source_cadence_margin_still_fails_closed(
    concept: str,
    reason: str,
) -> None:
    orchestrator = ThermalRuntimeOrchestrator()
    _establish_pool_full_ownership(orchestrator, at=NOW)
    observations = tuple(
        _observation(
            item.observation_id,
            item.value,
            at=(NOW if item.observation_id == concept else NOW + timedelta(seconds=121)),
        )
        for item in _observations(NOW)
    )

    result = _refresh(
        orchestrator,
        NOW + timedelta(seconds=121),
        observations=observations,
    )

    assert result.lifecycle is ThermalOrchestrationLifecycle.PREEMPTED
    assert result.blocking_reason == reason


def test_target_inactive_with_other_body_inactive_remains_cold_start_candidate() -> None:
    result = _refresh(
        ThermalRuntimeOrchestrator(),
        NOW,
        observations=_observations(NOW, pool_active=False, spa_active=False),
    )

    assert result.lifecycle is ThermalOrchestrationLifecycle.CANDIDATE_READY
    assert result.candidate_body is ThermalBody.POOL


def test_live_native_cadence_does_not_expire_complete_off_hydraulic_inventory() -> None:
    """Reproduce the v0.10.6 commissioning boundary at 30.94 seconds."""

    evaluated_at = NOW + timedelta(seconds=30, milliseconds=940)
    result = _refresh(
        ThermalRuntimeOrchestrator(),
        evaluated_at,
        thermal=_thermal(evaluated_at),
        observations=_observations(
            NOW,
            pool_active=False,
            spa_active=False,
            pump_rpm=0,
            configured_rpm=1500,
        ),
    )

    assert result.lifecycle is ThermalOrchestrationLifecycle.CANDIDATE_READY
    assert result.candidate_body is ThermalBody.POOL
    assert result.blocking_reason == "thermal_orchestration_candidate_ready_command_free"


def test_candidate_freshness_boundary_is_bounded_and_inclusive() -> None:
    at_boundary = NOW + timedelta(seconds=120)
    just_stale = at_boundary + timedelta(microseconds=1)

    accepted = _refresh(
        ThermalRuntimeOrchestrator(),
        at_boundary,
        thermal=_thermal(at_boundary),
        observations=_observations(NOW, pool_active=False, spa_active=False),
    )
    rejected = _refresh(
        ThermalRuntimeOrchestrator(),
        just_stale,
        thermal=_thermal(just_stale),
        observations=_observations(NOW, pool_active=False, spa_active=False),
    )

    assert accepted.lifecycle is ThermalOrchestrationLifecycle.CANDIDATE_READY
    assert rejected.lifecycle is ThermalOrchestrationLifecycle.BLOCKED
    assert (
        rejected.blocking_reason
        == "thermal_orchestration_shared_hydraulic_inventory_incomplete"
    )


def test_active_pool_light_is_not_a_shared_hydraulic_conflict() -> None:
    observations = (*_observations(NOW), _observation("pool_light.active", True, at=NOW))

    result = _refresh(ThermalRuntimeOrchestrator(), NOW, observations=observations)

    assert result.lifecycle is ThermalOrchestrationLifecycle.CANDIDATE_READY


def test_duplicate_snapshot_is_idempotent() -> None:
    orchestrator = ThermalRuntimeOrchestrator()
    first = _refresh(orchestrator, NOW)
    duplicate = _refresh(
        orchestrator,
        NOW,
        thermal=_thermal(NOW),
    )

    assert duplicate is first


@pytest.mark.parametrize(
    ("changed", "value"),
    [
        ("grid.outage_active", True),
        ("pool.active", False),
        ("spa.active", True),
    ],
)
def test_same_timestamp_changed_observation_fails_closed(
    changed: str,
    value: object,
) -> None:
    orchestrator = ThermalRuntimeOrchestrator()
    first = _refresh(orchestrator, NOW)
    conflicting = tuple(
        _observation(item.observation_id, value if item.observation_id == changed else item.value, at=NOW)
        for item in _observations(NOW)
    )

    result = _refresh(orchestrator, NOW, observations=conflicting)

    assert result.lifecycle is ThermalOrchestrationLifecycle.BLOCKED
    assert result.blocking_reason == "thermal_orchestration_snapshot_conflict"
    assert result.snapshot_identity != first.snapshot_identity
    assert result.candidate_id is None


def test_same_timestamp_changed_plan_identity_fails_closed() -> None:
    orchestrator = ThermalRuntimeOrchestrator()
    first = _refresh(orchestrator, NOW)

    result = _refresh(
        orchestrator,
        NOW,
        thermal=_thermal(NOW, pool_evaluation="other-eval", pool_plan="other-plan"),
    )

    assert result.lifecycle is ThermalOrchestrationLifecycle.BLOCKED
    assert result.blocking_reason == "thermal_orchestration_snapshot_conflict"
    assert result.snapshot_identity != first.snapshot_identity


def test_same_timestamp_changed_external_batch_fails_closed() -> None:
    orchestrator = ThermalRuntimeOrchestrator()
    first = _refresh(orchestrator, NOW)
    batch = ExternalChangeBatch(
        (
            ExternalChangeEvent(
                concept="pump.rpm",
                semantic_event_type=ExternalSemanticEventType.NATIVE_VALUE_CHANGED,
                native_object_id="p0102",
                previous_value=2900,
                new_value=2600,
                observed_at=NOW,
                external_policy=ExternalChangePolicy.RECONCILE,
                action_taken="reconciliation_required",
                notification_recommended=True,
                reconciliation_required=True,
            ),
        )
    )

    result = orchestrator.refresh(
        generated_at=NOW,
        observations=_observations(NOW),
        thermal=_thermal(NOW),
        external_changes=batch,
    )

    assert result.lifecycle is ThermalOrchestrationLifecycle.BLOCKED
    assert result.blocking_reason == "thermal_orchestration_snapshot_conflict"
    assert result.snapshot_identity != first.snapshot_identity


def test_older_snapshot_cannot_regress_current_truth() -> None:
    orchestrator = ThermalRuntimeOrchestrator()
    current = _refresh(orchestrator, NOW)
    older = _refresh(orchestrator, NOW - timedelta(seconds=1))

    assert older is current


def test_two_rapid_newer_snapshots_converge_on_latest_identity() -> None:
    orchestrator = ThermalRuntimeOrchestrator()
    first = _refresh(orchestrator, NOW)
    second_at = NOW + timedelta(milliseconds=1)
    second = _refresh(
        orchestrator,
        second_at,
        thermal=_thermal(
            second_at,
            pool_evaluation="pool-eval-2",
            pool_plan="pool-plan-2",
        ),
    )

    assert second.evaluated_at == second_at
    assert second.pool_plan_id == "pool-plan-2"
    assert second.superseded_candidate_id == first.candidate_id


def test_assessment_from_another_snapshot_cannot_become_candidate() -> None:
    result = _refresh(
        ThermalRuntimeOrchestrator(),
        NOW,
        thermal=_thermal(NOW - timedelta(seconds=1)),
    )

    assert result.lifecycle is ThermalOrchestrationLifecycle.BLOCKED
    assert result.blocking_reason == "thermal_orchestration_assessment_snapshot_mismatch"
    assert result.candidate_id is None


@pytest.mark.parametrize(
    ("mode", "next_mode"),
    [
        (ThermalRequestedMode.SOLAR, ThermalRequestedMode.OFF),
        (ThermalRequestedMode.SOLAR, ThermalRequestedMode.GAS),
        (ThermalRequestedMode.GAS, ThermalRequestedMode.SOLAR),
        (ThermalRequestedMode.GAS, ThermalRequestedMode.OFF),
    ],
)
def test_pool_mode_change_supersedes_candidate(
    mode: ThermalRequestedMode,
    next_mode: ThermalRequestedMode,
) -> None:
    orchestrator = ThermalRuntimeOrchestrator()
    first = _refresh(orchestrator, NOW, thermal=_thermal(NOW, pool_mode=mode))
    later = NOW + timedelta(seconds=1)
    second = _refresh(
        orchestrator,
        later,
        thermal=_thermal(
            later,
            pool_evaluation="pool-eval-2",
            pool_plan="pool-plan-2",
            pool_mode=next_mode,
            pool_authorized=next_mode is not ThermalRequestedMode.OFF,
        ),
    )

    assert second.superseded_candidate_id == first.candidate_id
    assert second.command_delivery_performed is False


@pytest.mark.parametrize(
    ("mode", "next_mode"),
    [
        (ThermalRequestedMode.SOLAR_PREFERRED, ThermalRequestedMode.OFF),
        (ThermalRequestedMode.SOLAR_PREFERRED, ThermalRequestedMode.GAS),
        (ThermalRequestedMode.GAS, ThermalRequestedMode.SOLAR_PREFERRED),
        (ThermalRequestedMode.GAS, ThermalRequestedMode.OFF),
    ],
)
def test_hot_tub_mode_change_uses_fresh_candidate_only(
    mode: ThermalRequestedMode,
    next_mode: ThermalRequestedMode,
) -> None:
    orchestrator = ThermalRuntimeOrchestrator()
    first = _refresh(
        orchestrator,
        NOW,
        thermal=_thermal(
            NOW, pool_authorized=False, spa_authorized=True, spa_mode=mode
        ),
        observations=_observations(
            NOW,
            pool_active=False,
            spa_active=True,
            pump_rpm=3000,
            configured_rpm=3000,
        ),
    )
    later = NOW + timedelta(seconds=1)
    second = _refresh(
        orchestrator,
        later,
        thermal=_thermal(
            later,
            pool_authorized=False,
            spa_authorized=next_mode is not ThermalRequestedMode.OFF,
            spa_evaluation="spa-eval-2",
            spa_plan="spa-plan-2",
            spa_mode=next_mode,
        ),
        observations=_observations(
            later,
            pool_active=False,
            spa_active=True,
            pump_rpm=3000,
            configured_rpm=3000,
        ),
    )

    assert second.superseded_candidate_id == first.candidate_id


@pytest.mark.parametrize(
    "observations",
    [
        _observations(NOW, pool_active=True, spa_active=True),
        _observations(NOW, omit=frozenset({"pool.active"})),
        _observations(NOW, omit=frozenset({"spa.active"})),
        _observations(NOW, waterfall=True),
        _observations(NOW, jets=True),
        _observations(NOW, slide=True),
        _observations(NOW, omit=frozenset({"waterfall.active"})),
        _observations(NOW, omit=frozenset({"jets.active"})),
        _observations(NOW, omit=frozenset({"slide.active"})),
    ],
)
def test_ambiguous_or_conflicting_hydraulics_fail_closed(
    observations: tuple[PoolObservation, ...],
) -> None:
    result = _refresh(
        ThermalRuntimeOrchestrator(),
        NOW,
        observations=observations,
    )

    assert result.lifecycle is ThermalOrchestrationLifecycle.BLOCKED
    assert result.candidate_id is None


@pytest.mark.parametrize("concept", ["pool.active", "spa.active"])
def test_stale_body_activity_fails_closed(concept: str) -> None:
    observations = tuple(
        _observation(
            item.observation_id,
            item.value,
            at=(NOW - timedelta(seconds=121) if item.observation_id == concept else NOW),
        )
        for item in _observations(NOW)
    )

    result = _refresh(ThermalRuntimeOrchestrator(), NOW, observations=observations)

    assert result.lifecycle is ThermalOrchestrationLifecycle.BLOCKED
    assert result.candidate_id is None


@pytest.mark.parametrize("concept", ["waterfall.active", "jets.active", "slide.active"])
def test_unusable_shared_hydraulic_evidence_fails_closed(concept: str) -> None:
    observations = tuple(
        _observation(
            item.observation_id,
            item.value,
            at=NOW,
            quality=(
                ObservationQuality.SUSPECT
                if item.observation_id == concept
                else ObservationQuality.GOOD
            ),
        )
        for item in _observations(NOW)
    )

    result = _refresh(ThermalRuntimeOrchestrator(), NOW, observations=observations)

    assert result.lifecycle is ThermalOrchestrationLifecycle.BLOCKED
    assert (
        result.blocking_reason
        == "thermal_orchestration_shared_hydraulic_inventory_incomplete"
    )


@pytest.mark.parametrize("concept", ["pool.active", "spa.active"])
def test_unusable_body_activity_fails_closed(concept: str) -> None:
    observations = tuple(
        _observation(
            item.observation_id,
            item.value,
            at=NOW,
            quality=(
                ObservationQuality.SUSPECT
                if item.observation_id == concept
                else ObservationQuality.GOOD
            ),
        )
        for item in _observations(NOW)
    )

    result = _refresh(ThermalRuntimeOrchestrator(), NOW, observations=observations)

    assert result.lifecycle is ThermalOrchestrationLifecycle.BLOCKED
    assert result.candidate_id is None


@pytest.mark.parametrize(
    "concept",
    [
        "pool.active",
        "spa.active",
        "waterfall.active",
        "jets.active",
        "slide.active",
    ],
)
def test_low_confidence_candidate_evidence_fails_closed(concept: str) -> None:
    observations = tuple(
        _observation(
            item.observation_id,
            item.value,
            at=NOW,
            confidence=0.49 if item.observation_id == concept else 1.0,
        )
        for item in _observations(NOW)
    )

    result = _refresh(ThermalRuntimeOrchestrator(), NOW, observations=observations)

    assert result.lifecycle is ThermalOrchestrationLifecycle.BLOCKED
    assert result.candidate_id is None


@pytest.mark.parametrize(
    "concept",
    [
        "pool.active",
        "spa.active",
        "waterfall.active",
        "jets.active",
        "slide.active",
    ],
)
def test_non_live_candidate_evidence_fails_closed(concept: str) -> None:
    observations = tuple(
        _observation(
            item.observation_id,
            item.value,
            at=NOW,
            source_kind=(
                ObservationSourceKind.DERIVED
                if item.observation_id == concept
                else ObservationSourceKind.LIVE
            ),
        )
        for item in _observations(NOW)
    )

    result = _refresh(ThermalRuntimeOrchestrator(), NOW, observations=observations)

    assert result.lifecycle is ThermalOrchestrationLifecycle.BLOCKED
    assert result.candidate_id is None


@pytest.mark.parametrize("quality", [ObservationQuality.GOOD, ObservationQuality.DEGRADED])
@pytest.mark.parametrize("confidence", [0.5, 1.0])
def test_live_verification_quality_and_confidence_boundary_is_accepted(
    quality: ObservationQuality,
    confidence: float,
) -> None:
    observations = tuple(
        _observation(
            item.observation_id,
            item.value,
            at=NOW,
            quality=(
                ObservationQuality.GOOD
                if item.observation_id == "grid.outage_active"
                else quality
            ),
            confidence=confidence,
        )
        for item in _observations(NOW)
    )

    result = _refresh(ThermalRuntimeOrchestrator(), NOW, observations=observations)

    assert result.lifecycle is ThermalOrchestrationLifecycle.CANDIDATE_READY


@pytest.mark.parametrize(
    "concept",
    [
        "pool.active",
        "spa.active",
        "pump.rpm",
        "pool.pump_circuit.configured_speed_rpm",
        "pool.raw_heater_id",
        "waterfall.active",
        "jets.active",
        "slide.active",
    ],
)
@pytest.mark.parametrize("failure", ["low_confidence", "non_live"])
def test_unusable_live_evidence_cannot_retain_runtime_ownership(
    concept: str,
    failure: str,
) -> None:
    orchestrator = ThermalRuntimeOrchestrator()
    _establish_pool_full_ownership(orchestrator, at=NOW)
    later = NOW + timedelta(seconds=1)
    observations = tuple(
        _observation(
            item.observation_id,
            item.value,
            at=later,
            confidence=(
                0.49
                if failure == "low_confidence" and item.observation_id == concept
                else 1.0
            ),
            source_kind=(
                ObservationSourceKind.DERIVED
                if failure == "non_live" and item.observation_id == concept
                else ObservationSourceKind.LIVE
            ),
        )
        for item in _observations(later)
    )

    result = _refresh(orchestrator, later, observations=observations)

    assert result.ownership_status is ThermalRuntimeOwnershipStatus.PREEMPTED
    assert result.command_delivery_performed is False


def test_zero_or_multiple_authorized_candidates_fail_closed() -> None:
    no_candidate = _refresh(
        ThermalRuntimeOrchestrator(),
        NOW,
        thermal=_thermal(NOW, pool_authorized=False, spa_authorized=False),
    )
    multiple = _refresh(
        ThermalRuntimeOrchestrator(),
        NOW,
        thermal=_thermal(NOW, pool_authorized=True, spa_authorized=True),
    )

    assert no_candidate.blocking_reason == "thermal_orchestration_no_authorized_candidate"
    assert multiple.blocking_reason == (
        "thermal_orchestration_multiple_authorized_candidates"
    )


def test_grid_lifecycle_is_typed_and_command_free() -> None:
    orchestrator = ThermalRuntimeOrchestrator()
    pending = _refresh(
        orchestrator, NOW, observations=_observations(NOW, outage=True)
    )
    unknown_at = NOW + timedelta(seconds=1)
    unknown = _refresh(
        orchestrator,
        unknown_at,
        observations=_observations(unknown_at, outage="unknown"),
    )
    restarted_at = NOW + timedelta(seconds=2)
    restarted = _refresh(
        orchestrator,
        restarted_at,
        observations=_observations(restarted_at, outage=True),
    )
    confirmed_at = restarted_at + timedelta(seconds=2)
    confirmed = _refresh(
        orchestrator,
        confirmed_at,
        observations=_observations(confirmed_at, outage=True),
    )
    unresolved_at = confirmed_at + timedelta(seconds=1)
    unresolved = _refresh(
        orchestrator,
        unresolved_at,
        observations=_observations(unresolved_at, outage="unknown"),
    )
    returned_at = unresolved_at + timedelta(seconds=1)
    returned = _refresh(
        orchestrator,
        returned_at,
        observations=_observations(returned_at, outage=False),
    )
    second_outage_at = returned_at + timedelta(seconds=1)
    second_outage = _refresh(
        orchestrator,
        second_outage_at,
        observations=_observations(second_outage_at, outage=True),
    )

    assert pending.outage.disposition is GridOutageDisposition.OFF_GRID_PENDING
    assert unknown.outage.disposition is GridOutageDisposition.UNKNOWN
    assert restarted.outage.disposition is GridOutageDisposition.OFF_GRID_PENDING
    assert confirmed.outage.disposition is GridOutageDisposition.CONFIRMED_OUTAGE
    assert unresolved.outage.disposition is GridOutageDisposition.UNKNOWN
    assert unresolved.lifecycle is ThermalOrchestrationLifecycle.BLOCKED
    assert returned.outage.disposition is GridOutageDisposition.ON_GRID
    assert second_outage.outage.disposition is GridOutageDisposition.OFF_GRID_PENDING
    assert all(
        not item.command_delivery_performed
        for item in (
            pending,
            unknown,
            restarted,
            confirmed,
            unresolved,
            returned,
            second_outage,
        )
    )


def test_grid_uncertainty_relinquishes_existing_ownership_without_cleanup() -> None:
    orchestrator = ThermalRuntimeOrchestrator()
    _establish_pool_pump_ownership(orchestrator, at=NOW)
    result = _refresh(
        orchestrator,
        NOW,
        observations=_observations(NOW, outage=True),
    )

    assert result.ownership_status is ThermalRuntimeOwnershipStatus.RELINQUISHED
    assert result.command_delivery_performed is False


def test_stale_latest_batch_cannot_preempt_new_orchestrator_lease() -> None:
    orchestrator = ThermalRuntimeOrchestrator()
    _establish_pool_pump_ownership(orchestrator, at=NOW)
    stale_event = ExternalChangeEvent(
        concept="pump.rpm",
        semantic_event_type=ExternalSemanticEventType.NATIVE_VALUE_CHANGED,
        native_object_id="p0102",
        previous_value=2600,
        new_value=2900,
        observed_at=NOW - timedelta(seconds=1),
        external_policy=ExternalChangePolicy.RECONCILE,
        action_taken="reconciliation_required",
        notification_recommended=True,
        reconciliation_required=True,
    )
    batch = ExternalChangeBatch((stale_event,))
    first_at = NOW + timedelta(seconds=1)
    first = orchestrator.refresh(
        generated_at=first_at,
        observations=_observations(first_at),
        thermal=_thermal(first_at),
        external_changes=batch,
    )
    second_at = NOW + timedelta(seconds=2)
    second = orchestrator.refresh(
        generated_at=second_at,
        observations=_observations(second_at),
        thermal=_thermal(second_at),
        external_changes=batch,
    )

    assert first.ownership_status is ThermalRuntimeOwnershipStatus.OWNED
    assert second.ownership_status is ThermalRuntimeOwnershipStatus.OWNED


def test_postlease_external_batch_still_preempts_orchestrator_lease() -> None:
    orchestrator = ThermalRuntimeOrchestrator()
    _establish_pool_pump_ownership(orchestrator, at=NOW)
    later = NOW + timedelta(seconds=1)
    batch = ExternalChangeBatch(
        (
            ExternalChangeEvent(
                concept="pump.rpm",
                semantic_event_type=ExternalSemanticEventType.NATIVE_VALUE_CHANGED,
                native_object_id="p0102",
                previous_value=2900,
                new_value=2800,
                observed_at=later,
                external_policy=ExternalChangePolicy.RECONCILE,
                action_taken="reconciliation_required",
                notification_recommended=True,
                reconciliation_required=True,
            ),
        )
    )

    result = orchestrator.refresh(
        generated_at=later,
        observations=_observations(later),
        thermal=_thermal(later),
        external_changes=batch,
    )

    assert result.ownership_status is ThermalRuntimeOwnershipStatus.PREEMPTED
    assert result.lifecycle is ThermalOrchestrationLifecycle.PREEMPTED


def test_new_plan_supersedes_existing_runtime_ownership() -> None:
    orchestrator = ThermalRuntimeOrchestrator()
    _establish_pool_pump_ownership(orchestrator, at=NOW)
    later = NOW + timedelta(seconds=1)
    result = _refresh(
        orchestrator,
        later,
        thermal=_thermal(
            later,
            pool_evaluation="pool-eval-2",
            pool_plan="pool-plan-2",
        ),
        observations=_observations(later),
    )

    assert result.ownership_status is ThermalRuntimeOwnershipStatus.SUPERSEDED
    assert result.lifecycle is ThermalOrchestrationLifecycle.SUPERSEDED


@pytest.mark.parametrize(
    "observations",
    [
        _observations(NOW, pool_active=False),
        _observations(NOW, pool_active=False, spa_active=True),
        _observations(NOW, pump_rpm=2600),
        _observations(NOW, configured_rpm=2600),
    ],
)
def test_current_native_divergence_preempts_owned_lifecycle(
    observations: tuple[PoolObservation, ...],
) -> None:
    orchestrator = ThermalRuntimeOrchestrator()
    _establish_pool_pump_ownership(orchestrator, at=NOW)
    later = NOW + timedelta(seconds=1)
    shifted = tuple(
        _observation(item.observation_id, item.value, at=later)
        for item in observations
    )

    result = _refresh(orchestrator, later, observations=shifted)

    assert result.ownership_status is ThermalRuntimeOwnershipStatus.PREEMPTED
    assert result.command_delivery_performed is False


@pytest.mark.parametrize(
    ("pool_active", "spa_active", "rpm", "heater"),
    [
        (True, False, 2600, "00000"),
        (True, False, 1500, "00000"),
        (True, False, 2900, "H0002"),
        (True, False, 3000, "H0001"),
        (False, True, 3000, "H0001"),
    ],
)
def test_restart_matching_native_state_never_manufactures_ownership(
    pool_active: bool,
    spa_active: bool,
    rpm: int,
    heater: str,
) -> None:
    orchestrator = ThermalRuntimeOrchestrator()
    result = _refresh(
        orchestrator,
        NOW,
        observations=_observations(
            NOW,
            pool_active=pool_active,
            spa_active=spa_active,
            pump_rpm=rpm,
            configured_rpm=rpm,
            pool_heater=heater,
        ),
    )

    assert result.ownership_status is ThermalRuntimeOwnershipStatus.UNOWNED
    assert result.command_delivery_performed is False


def test_unload_discards_state_and_late_callback_is_noop() -> None:
    orchestrator = ThermalRuntimeOrchestrator()
    _refresh(orchestrator, NOW)
    unloaded_at = NOW + timedelta(seconds=1)
    unloaded = orchestrator.unload(unloaded_at=unloaded_at)
    late = _refresh(orchestrator, unloaded_at + timedelta(seconds=1))

    assert unloaded.lifecycle is ThermalOrchestrationLifecycle.UNLOADED
    assert unloaded.ownership_status is ThermalRuntimeOwnershipStatus.UNOWNED
    assert late is unloaded
    assert late.command_delivery_performed is False


def test_fail_closed_invalidates_candidate_and_newer_frame_recovers() -> None:
    orchestrator = ThermalRuntimeOrchestrator()
    candidate = _refresh(orchestrator, NOW)

    failed = orchestrator.fail_closed(
        failed_at=NOW + timedelta(seconds=1),
        reason_code="thermal_orchestration_processing_failed:RuntimeError",
    )
    recovered_at = NOW + timedelta(seconds=2)
    recovered = _refresh(orchestrator, recovered_at)

    assert candidate.lifecycle is ThermalOrchestrationLifecycle.CANDIDATE_READY
    assert failed.lifecycle is ThermalOrchestrationLifecycle.BLOCKED
    assert failed.candidate_id is None
    assert failed.command_delivery_performed is False
    assert failed.automatic_execution_driver_enabled is False
    assert recovered.lifecycle is ThermalOrchestrationLifecycle.CANDIDATE_READY


def test_fail_closed_relinquishes_owned_lifecycle_and_bounds_reason() -> None:
    orchestrator = ThermalRuntimeOrchestrator()
    _establish_pool_pump_ownership(orchestrator, at=NOW)

    failed = orchestrator.fail_closed(
        failed_at=NOW + timedelta(seconds=1),
        reason_code="unsafe\nreason " + "x" * 1000,
    )

    assert failed.lifecycle is ThermalOrchestrationLifecycle.BLOCKED
    assert failed.ownership_status is ThermalRuntimeOwnershipStatus.RELINQUISHED
    assert failed.candidate_id is None
    assert "\n" not in failed.blocking_reason
    assert len(failed.blocking_reason) <= 256
    assert failed.command_delivery_performed is False


def test_high_level_lifecycle_sequence_has_zero_delivery_surface() -> None:
    orchestrator = ThermalRuntimeOrchestrator()
    sequence = [
        (NOW, _thermal(NOW), _observations(NOW)),
        (
            NOW + timedelta(seconds=1),
            _thermal(
                NOW + timedelta(seconds=1),
                pool_evaluation="gas-eval",
                pool_plan="gas-plan",
                pool_mode=ThermalRequestedMode.GAS,
            ),
            _observations(NOW + timedelta(seconds=1), pump_rpm=3000),
        ),
        (
            NOW + timedelta(seconds=2),
            _thermal(
                NOW + timedelta(seconds=2),
                pool_evaluation="off-eval",
                pool_plan="off-plan",
                pool_mode=ThermalRequestedMode.OFF,
                pool_authorized=False,
            ),
            _observations(NOW + timedelta(seconds=2), pool_active=False),
        ),
        (
            NOW + timedelta(seconds=3),
            _thermal(
                NOW + timedelta(seconds=3),
                pool_authorized=False,
                spa_authorized=True,
            ),
            _observations(
                NOW + timedelta(seconds=3),
                pool_active=False,
                spa_active=True,
                pump_rpm=3000,
            ),
        ),
        (
            NOW + timedelta(seconds=4),
            _thermal(NOW + timedelta(seconds=4)),
            _observations(NOW + timedelta(seconds=4), outage=True),
        ),
        (
            NOW + timedelta(seconds=6),
            _thermal(NOW + timedelta(seconds=6)),
            _observations(NOW + timedelta(seconds=6), outage=True),
        ),
        (
            NOW + timedelta(seconds=7),
            _thermal(NOW + timedelta(seconds=7)),
            _observations(NOW + timedelta(seconds=7), outage=False),
        ),
    ]

    with patch(
        "poolos.thermal_live_execution.ThermalLiveExecutionEngine.deliver_current_step"
    ) as delivery:
        results = [
            orchestrator.refresh(
                generated_at=at,
                observations=observations,
                thermal=thermal,
            )
            for at, thermal, observations in sequence
        ]

    assert all(result.command_delivery_performed is False for result in results)
    delivery.assert_not_called()
    assert not hasattr(orchestrator, "deliver")
    assert not hasattr(orchestrator, "deliver_current_step")


def test_production_module_contains_no_delivery_or_filtration_dependency() -> None:
    source = (
        ROOT / "poolos" / "thermal_runtime_orchestration.py"
    ).read_text(encoding="utf-8")

    assert "deliver_current_step(" not in source
    assert "ManualIntelliCenterThermalLiveDelivery" not in source
    assert "manual_intellicenter" not in source
    assert "filtration" not in source
    assert "1500" not in source
    assert "StopPump" not in source
    assert "SetBodyActive" not in source


def test_probe_continuity_requires_current_pool_routed_circulation() -> None:
    valid = assess_pool_temperature_probe_continuity(
        generated_at=NOW,
        observations=_observations(NOW, pump_rpm=1500, configured_rpm=1500),
        prior_grid_disposition=GridOutageDisposition.ON_GRID,
    )
    different_positive_rpm = assess_pool_temperature_probe_continuity(
        generated_at=NOW,
        observations=_observations(NOW, pump_rpm=1526, configured_rpm=1500),
        prior_grid_disposition=GridOutageDisposition.ON_GRID,
    )
    stopped = assess_pool_temperature_probe_continuity(
        generated_at=NOW,
        observations=_observations(NOW, pump_rpm=0, configured_rpm=1500),
        prior_grid_disposition=GridOutageDisposition.ON_GRID,
    )
    shared = assess_pool_temperature_probe_continuity(
        generated_at=NOW,
        observations=_observations(
            NOW,
            pump_rpm=1500,
            configured_rpm=1500,
            jets=True,
        ),
        prior_grid_disposition=GridOutageDisposition.ON_GRID,
    )
    unusable_temperature = assess_pool_temperature_probe_continuity(
        generated_at=NOW,
        observations=(
            *_observations(NOW, pump_rpm=1500, configured_rpm=1500),
            _observation(
                "pool.temperature",
                86.0,
                at=NOW,
                quality=ObservationQuality.INVALID,
            ),
        ),
        prior_grid_disposition=GridOutageDisposition.ON_GRID,
    )

    assert valid.valid
    assert (
        different_positive_rpm.blocker
        == "temperature_probe_pool_circulation_not_proven"
    )
    assert stopped.blocker == "temperature_probe_pool_circulation_not_proven"
    assert shared.blocker == "thermal_orchestration_shared_hydraulic_conflict:jets.active"
    assert unusable_temperature.valid
    assert not unusable_temperature.temperature_sample_usable


def test_probe_continuity_fails_closed_for_grid_or_external_takeover() -> None:
    observations = _observations(NOW, pump_rpm=1500, configured_rpm=1500)

    stale_grid_state = assess_pool_temperature_probe_continuity(
        generated_at=NOW,
        observations=observations,
        prior_grid_disposition=GridOutageDisposition.CONFIRMED_OUTAGE,
    )
    external = assess_pool_temperature_probe_continuity(
        generated_at=NOW,
        observations=observations,
        prior_grid_disposition=GridOutageDisposition.ON_GRID,
        external_preemption_reason="runtime_ownership_preempted:pump_external_change",
    )
    disabled = assess_pool_temperature_probe_continuity(
        generated_at=NOW,
        observations=observations,
        prior_grid_disposition=GridOutageDisposition.ON_GRID,
        lifecycle_blocker="temperature_probe_thermal_live_disabled",
    )

    assert stale_grid_state.blocker == "temperature_probe_grid_not_authoritatively_on"
    assert external.blocker == "runtime_ownership_preempted:pump_external_change"
    assert disabled.blocker == "temperature_probe_thermal_live_disabled"
