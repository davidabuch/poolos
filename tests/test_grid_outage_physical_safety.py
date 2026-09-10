"""Safety tests for confirmed-grid-outage reduction-only supervision."""

from __future__ import annotations

from datetime import UTC, date, datetime, time, timedelta
from fractions import Fraction
from types import SimpleNamespace
from typing import cast

import pytest

from poolos.external_change import (
    ExternalChangeBatch,
    ExternalChangeEvent,
    ExternalChangePolicy,
    ExternalSemanticEventType,
)
from poolos.filtration_policy import (
    FiltrationAccountingSnapshot,
    FiltrationCreditBand,
    FiltrationDisposition,
    PoolTemperatureValidationState,
)
from poolos.grid_outage_confirmation import (
    GridAvailability,
    GridOutageAssessment,
    GridOutageDisposition,
    GridOutageEvidenceStatus,
    GridOutageReasonCode,
)
from poolos.grid_outage_physical_safety import (
    GridOutagePhysicalSafetyEngine,
    GridOutageReductionKind,
    GridOutageSafetyFrame,
    GridOutageSafetyLifecycle,
    OutageCirculationDisposition,
    assess_outage_circulation_requirement,
    grid_outage_external_preemption_reason,
)
from poolos.observations import (
    ObservationQuality,
    ObservationSourceKind,
    PoolObservation,
)
from poolos.operating_baselines import PumpOperatingBaselines
from poolos.physical_command_authority import (
    NativeConsequenceAttribution,
    PhysicalRequestSource,
)


NOW = datetime(2026, 9, 6, 12, 0, tzinfo=UTC)

_NATIVE_OBJECT_BY_CONCEPT = {
    "pool.active": "B1101",
    "spa.active": "B1202",
    "pool.raw_heater_id": "B1101",
    "spa.raw_heater_id": "B1202",
    "pool_light.active": "C0002",
    "jets.active": "C0003",
    "slide.active": "C0004",
    "waterfall.active": "FTR01",
    "freeze.active": "FRE01",
    "pool.pump_circuit.configured_speed_rpm": "p0102",
    "pump.rpm": "PUMP01",
}


def observation(
    concept: str,
    value: object,
    *,
    at: datetime = NOW,
    source_kind: ObservationSourceKind = ObservationSourceKind.LIVE,
    quality: ObservationQuality = ObservationQuality.GOOD,
    confidence: float = 1.0,
    native_object_id: str | None = None,
) -> PoolObservation:
    return PoolObservation(
        concept,
        value,
        observed_at=at,
        source_kind=source_kind,
        source_id=(
            f"intellicenter_native:test:{native_object_id}"
            if native_object_id is not None
            else f"intellicenter_native:test:{_NATIVE_OBJECT_BY_CONCEPT.get(concept, 'UNKNOWN')}"
        ),
        quality=quality,
        confidence=confidence,
    )


def confirmed(
    at: datetime = NOW,
    *,
    epoch_started_at: datetime | None = None,
    confirmed_at: datetime | None = None,
) -> GridOutageAssessment:
    epoch_started_at = epoch_started_at or NOW - timedelta(seconds=2)
    confirmed_at = confirmed_at or NOW
    return GridOutageAssessment(
        raw_availability=GridAvailability.OFF_GRID,
        disposition=GridOutageDisposition.CONFIRMED_OUTAGE,
        evidence_status=GridOutageEvidenceStatus.USABLE,
        evaluated_at=at,
        observed_at=at,
        source_id="native",
        pending_since=epoch_started_at,
        threshold_reached_at=confirmed_at,
        outage_epoch_started_at=epoch_started_at,
        confirmed_at=confirmed_at,
        unresolved_confirmed_outage_since=None,
        grid_returned_at=None,
        reason_code=GridOutageReasonCode.OUTAGE_CONFIRMED,
    )


def outage_assessment(
    disposition: GridOutageDisposition,
    *,
    at: datetime,
    unresolved_since: datetime | None = None,
) -> GridOutageAssessment:
    return GridOutageAssessment(
        raw_availability=(
            GridAvailability.ON_GRID
            if disposition is GridOutageDisposition.ON_GRID
            else GridAvailability.UNKNOWN
        ),
        disposition=disposition,
        evidence_status=GridOutageEvidenceStatus.USABLE,
        evaluated_at=at,
        observed_at=at,
        source_id="native",
        pending_since=None,
        threshold_reached_at=None,
        outage_epoch_started_at=None,
        confirmed_at=None,
        unresolved_confirmed_outage_since=unresolved_since,
        grid_returned_at=(at if disposition is GridOutageDisposition.ON_GRID else None),
        reason_code=(
            GridOutageReasonCode.GRID_AVAILABLE_AUTHORITATIVE
            if disposition is GridOutageDisposition.ON_GRID
            else GridOutageReasonCode.EVIDENCE_UNUSABLE
        ),
    )


def filtration(
    disposition: FiltrationDisposition,
    *,
    at: datetime = NOW,
) -> FiltrationAccountingSnapshot:
    remaining = timedelta(0) if disposition is FiltrationDisposition.SATISFIED else timedelta(hours=1)
    return FiltrationAccountingSnapshot(
        evaluated_at=at,
        obligation_day=date(2026, 9, 6),
        required_runtime=timedelta(hours=6),
        credited_runtime=timedelta(hours=5) if remaining else timedelta(hours=6),
        remaining_runtime=remaining,
        carried_prior_day_debt=timedelta(0),
        total_remaining_runtime=remaining,
        disposition=disposition,
        independent_disposition=(
            FiltrationDisposition.RUN_NOW
            if disposition is FiltrationDisposition.CREDITING
            else disposition
        ),
        tou_tier=SimpleNamespace(name="OFF_PEAK"),
        next_suitable_at=None,
        ordinary_filtration_rpm=2600,
        reason_code="test",
        rationale=(),
        debt_days=(date(2026, 9, 6),),
        currently_earning_credit=disposition is FiltrationDisposition.CREDITING,
        restored_from_history=False,
        temporal_regressions_ignored=0,
        highest_validated_pool_temperature_f=80.0,
        temperature_validation_state=PoolTemperatureValidationState.VALIDATED,
        pool_temperature_stabilization_started_at=None,
        pool_temperature_stabilization_remaining=None,
        operational_day_started_at=datetime.combine(date(2026, 9, 6), time(8), tzinfo=UTC),
        next_operational_day_boundary=datetime.combine(date(2026, 9, 7), time(8), tzinfo=UTC),
        observed_pump_rpm=2600.0,
        filtration_credit_factor=Fraction(1),
        filtration_credit_band=FiltrationCreditBand.FULL,
    )


def safe_observations(
    *,
    at: datetime = NOW,
    pool: bool = True,
    spa: bool = False,
    pool_source: str = "00000",
    spa_source: str = "00000",
    light: bool = False,
    jets: bool = False,
    slide: bool = False,
    waterfall: bool = False,
    freeze: bool = False,
    configured: int = 2600,
    rpm: int = 2600,
) -> tuple[PoolObservation, ...]:
    values = {
        "pool.active": pool,
        "spa.active": spa,
        "pool.raw_heater_id": pool_source,
        "spa.raw_heater_id": spa_source,
        "pool_light.active": light,
        "jets.active": jets,
        "slide.active": slide,
        "waterfall.active": waterfall,
        "freeze.active": freeze,
        "pool.pump_circuit.configured_speed_rpm": configured,
        "pump.rpm": rpm,
    }
    return tuple(observation(key, value, at=at) for key, value in values.items())


def frame(
    *,
    at: datetime = NOW,
    identity: str = "frame-1",
    observations: tuple[PoolObservation, ...] | None = None,
    filtration_state: FiltrationDisposition = FiltrationDisposition.CREDITING,
    authority: bool = True,
    transport: bool = True,
    external_preemption_reason: str | None = None,
    pump_circuit_id: str | None = "p0102",
) -> GridOutageSafetyFrame:
    return GridOutageSafetyFrame(
        frame_identity=identity,
        observed_at=at,
        observations=safe_observations(at=at) if observations is None else observations,
        outage=confirmed(at),
        filtration=filtration(filtration_state, at=at),
        physical_authority_ready=authority,
        transport_ready=transport,
        pool_pump_circuit_id=pump_circuit_id,
        external_preemption_reason=external_preemption_reason,
    )


def enabled_engine() -> GridOutagePhysicalSafetyEngine:
    engine = GridOutagePhysicalSafetyEngine()
    engine.set_enabled(True, changed_at=NOW - timedelta(seconds=1))
    return engine


def external_event(concept: str, *, at: datetime = NOW) -> ExternalChangeEvent:
    return ExternalChangeEvent(
        concept=concept,
        semantic_event_type=ExternalSemanticEventType.NATIVE_VALUE_CHANGED,
        native_object_id="native",
        previous_value=False,
        new_value=True,
        observed_at=at,
        external_policy=ExternalChangePolicy.ACCEPT,
        action_taken="accepted_native_value",
        notification_recommended=False,
        reconciliation_required=False,
    )


def test_gate_defaults_off_and_enable_requires_a_later_frame() -> None:
    engine = GridOutagePhysicalSafetyEngine()
    disabled = engine.evaluate(
        frame(observations=safe_observations(pool_source="H0001"))
    )
    assert disabled.lifecycle is GridOutageSafetyLifecycle.GATE_DISABLED
    assert disabled.candidate is None

    engine.set_enabled(True, changed_at=NOW)
    assert engine.assessment is not None
    assert engine.assessment.lifecycle is GridOutageSafetyLifecycle.BLOCKED
    assert engine.assessment.candidate is None
    assert not engine.assessment.command_delivery_enabled
    same = engine.evaluate(frame(observations=safe_observations(pool_source="H0001")))
    assert same.lifecycle is GridOutageSafetyLifecycle.BLOCKED
    assert same.reason_code == "grid_outage_fresh_frame_required_after_enable"


def test_disabling_gate_immediately_clears_candidate_readiness_diagnostics() -> None:
    engine = enabled_engine()
    ready = engine.evaluate(
        frame(observations=safe_observations(pool_source="H0001"))
    )
    assert ready.lifecycle is GridOutageSafetyLifecycle.CANDIDATE_READY

    engine.set_enabled(False, changed_at=NOW + timedelta(milliseconds=1))
    assert engine.assessment is not None
    assert engine.assessment.lifecycle is GridOutageSafetyLifecycle.GATE_DISABLED
    assert engine.assessment.candidate is None
    assert not engine.assessment.command_delivery_enabled


def test_diagnostics_are_bounded_observational_and_idempotent() -> None:
    engine = enabled_engine()
    assessment = engine.evaluate(
        frame(observations=safe_observations(pool_source="H0001"))
    )

    first = dict(assessment.diagnostics())
    second = dict(assessment.diagnostics())

    assert first == second
    assert engine.assessment is assessment
    assert len(str(first)) < 4096


@pytest.mark.parametrize(
    ("changes", "kind"),
    (
        ({"spa": True, "pool": False, "spa_source": "H0001"}, GridOutageReductionKind.SPA_SOURCE_OFF),
        ({"pool_source": "H0002"}, GridOutageReductionKind.POOL_SOURCE_OFF),
        ({"light": True}, GridOutageReductionKind.POOL_LIGHT_OFF),
        ({"jets": True}, GridOutageReductionKind.JETS_OFF),
        ({"slide": True}, GridOutageReductionKind.SLIDE_OFF),
        ({"waterfall": True}, GridOutageReductionKind.WATERFALL_OFF),
        ({"spa": True, "pool": False}, GridOutageReductionKind.SPA_BODY_OFF),
    ),
)
def test_exact_reduction_priority_shapes(
    changes: dict[str, object], kind: GridOutageReductionKind
) -> None:
    engine = enabled_engine()
    result = engine.evaluate(
        frame(observations=safe_observations(**changes))  # type: ignore[arg-type]
    )
    assert result.lifecycle is GridOutageSafetyLifecycle.CANDIDATE_READY
    assert result.candidate is not None
    assert result.candidate.kind is kind


def test_spa_source_precedes_pool_source_and_light() -> None:
    result = enabled_engine().evaluate(
        frame(
            observations=safe_observations(
                pool=True,
                spa=True,
                pool_source="H0001",
                spa_source="H0002",
                light=True,
            )
        )
    )
    assert result.candidate is not None
    assert result.candidate.kind is GridOutageReductionKind.SPA_SOURCE_OFF


@pytest.mark.parametrize(
    ("changes", "kind"),
    (
        (
            {"pool": False, "spa": True, "jets": True, "slide": True, "waterfall": True},
            GridOutageReductionKind.JETS_OFF,
        ),
        (
            {"pool": False, "spa": True, "slide": True, "waterfall": True},
            GridOutageReductionKind.SLIDE_OFF,
        ),
        (
            {"pool": False, "spa": True, "waterfall": True},
            GridOutageReductionKind.WATERFALL_OFF,
        ),
        (
            {"pool": False, "spa": True},
            GridOutageReductionKind.SPA_BODY_OFF,
        ),
    ),
)
def test_hydraulic_priority_precedes_spa_body_shutdown(
    changes: dict[str, object], kind: GridOutageReductionKind
) -> None:
    result = enabled_engine().evaluate(
        frame(observations=safe_observations(**changes))  # type: ignore[arg-type]
    )
    assert result.candidate is not None
    assert result.candidate.kind is kind


def test_freeze_allows_light_but_blocks_hydraulic_reductions() -> None:
    light = enabled_engine().evaluate(
        frame(observations=safe_observations(freeze=True, light=True, jets=True))
    )
    assert light.candidate is not None
    assert light.candidate.kind is GridOutageReductionKind.POOL_LIGHT_OFF

    hydraulic = enabled_engine().evaluate(
        frame(observations=safe_observations(freeze=True, jets=True))
    )
    assert hydraulic.candidate is None
    assert hydraulic.reason_code == "grid_outage_freeze_blocks_hydraulic_reduction"


@pytest.mark.parametrize(
    ("configured", "rpm", "candidate", "reason"),
    (
        (2600, 2600, True, "grid_outage_pump_reduction_ready"),
        (1500, 1500, False, "grid_outage_pump_already_at_or_below_ceiling"),
        (1200, 1200, False, "grid_outage_pump_already_at_or_below_ceiling"),
        (2600, 0, False, "required_circulation_not_established"),
        (
            2600,
            1000,
            False,
            "grid_outage_configured_actual_pump_evidence_contradictory",
        ),
    ),
)
def test_outage_pump_is_reduction_only_and_never_starts_circulation(
    configured: int, rpm: int, candidate: bool, reason: str
) -> None:
    result = enabled_engine().evaluate(
        frame(observations=safe_observations(configured=configured, rpm=rpm))
    )
    assert (result.candidate is not None) is candidate
    assert result.reason_code == reason
    if result.candidate is not None:
        assert result.candidate.kind is GridOutageReductionKind.POOL_PUMP_REDUCTION
        assert result.candidate.requested_value == 1500


def test_configured_outage_rpm_drives_candidate_and_verification() -> None:
    baselines = PumpOperatingBaselines(grid_outage_rpm=1600)
    engine = GridOutagePhysicalSafetyEngine(baselines=baselines)
    engine.set_enabled(True, changed_at=NOW - timedelta(seconds=1))
    result = engine.evaluate(
        frame(observations=safe_observations(configured=2600, rpm=2600))
    )

    assert result.candidate is not None
    assert result.candidate.kind is GridOutageReductionKind.POOL_PUMP_REDUCTION
    assert result.candidate.requested_value == 1600
    assert result.candidate.policy_fingerprint == baselines.fingerprint


def test_outage_pump_candidate_binds_exact_current_recycled_pmpcirc() -> None:
    observations = tuple(
        observation(
            item.observation_id,
            item.value,
            native_object_id=(
                "p0199"
                if item.observation_id
                == "pool.pump_circuit.configured_speed_rpm"
                else None
            ),
        )
        for item in safe_observations(configured=2600, rpm=2600)
    )

    current = enabled_engine().evaluate(
        frame(observations=observations, pump_circuit_id="p0199")
    )
    stale = enabled_engine().evaluate(
        frame(observations=observations, pump_circuit_id="p0102")
    )
    unresolved = enabled_engine().evaluate(
        frame(observations=observations, pump_circuit_id=None)
    )

    assert current.candidate is not None
    assert current.candidate.target == "p0199"
    assert current.candidate.expected_native_object_id == "p0199"
    assert stale.candidate is None
    assert stale.reason_code == "grid_outage_pool_pump_identity_stale"
    assert unresolved.candidate is None
    assert unresolved.reason_code == "grid_outage_pool_pump_circuit_unresolved"


def test_debt_alone_does_not_require_circulation() -> None:
    deferred = frame(filtration_state=FiltrationDisposition.DEFERRED_TOU)
    assessment = assess_outage_circulation_requirement(deferred)
    assert assessment.disposition is OutageCirculationDisposition.NOT_REQUIRED


def test_required_without_established_circulation_is_explicitly_blocked() -> None:
    stopped = frame(observations=safe_observations(pool=False, rpm=0))
    assessment = assess_outage_circulation_requirement(stopped)
    assert assessment.disposition is OutageCirculationDisposition.BLOCKED
    assert assessment.reason_code == "required_circulation_not_established"
    assert enabled_engine().evaluate(stopped).candidate is None


def test_low_confidence_or_non_live_critical_evidence_fails_closed() -> None:
    items = list(safe_observations())
    items[0] = observation("pool.active", True, confidence=0.49)
    result = enabled_engine().evaluate(frame(observations=tuple(items)))
    assert result.candidate is None
    assert "unusable" in result.reason_code

    items[0] = observation(
        "pool.active", True, source_kind=ObservationSourceKind.DERIVED
    )
    assert enabled_engine().evaluate(frame(observations=tuple(items))).candidate is None


def test_native_safety_evidence_matches_live_execution_usability_boundary() -> None:
    items = list(safe_observations())
    items[0] = observation(
        "pool.active",
        True,
        quality=ObservationQuality.DEGRADED,
        confidence=0.5,
    )
    accepted = enabled_engine().evaluate(frame(observations=tuple(items)))
    assert accepted.candidate is not None

    stale_at = NOW - timedelta(seconds=31)
    items[0] = observation("pool.active", True, at=stale_at)
    stale = enabled_engine().evaluate(frame(observations=tuple(items)))
    assert stale.candidate is None
    assert "unusable" in stale.reason_code


def test_inactive_body_configured_source_is_preserved_and_active_unknown_blocks() -> None:
    inactive_spa = enabled_engine().evaluate(
        frame(observations=safe_observations(spa=False, spa_source="H0001"))
    )
    assert inactive_spa.candidate is not None
    assert inactive_spa.candidate.kind is GridOutageReductionKind.POOL_PUMP_REDUCTION

    unknown_pool = enabled_engine().evaluate(
        frame(observations=safe_observations(pool=True, pool_source="H9999"))
    )
    assert unknown_pool.candidate is None
    assert unknown_pool.reason_code == "grid_outage_pool_source_unresolved"


def test_gate_disable_during_attempt_blocks_replay_for_same_outage_epoch() -> None:
    engine = enabled_engine()
    first = engine.evaluate(
        frame(observations=safe_observations(pool_source="H0001"))
    )
    assert first.candidate is not None
    engine.record_accepted_delivery(first.candidate, accepted_at=NOW)
    engine.set_enabled(False, changed_at=NOW + timedelta(milliseconds=1))
    engine.set_enabled(True, changed_at=NOW + timedelta(milliseconds=2))
    later_at = NOW + timedelta(seconds=1)
    later = engine.evaluate(
        frame(
            at=later_at,
            identity="frame-2",
            observations=safe_observations(at=later_at, pool_source="H0001"),
        )
    )
    assert later.candidate is None
    assert later.reason_code == "grid_outage_attempt_invalidated_requires_new_outage_epoch"


def test_accepted_receipt_needs_strictly_later_authoritative_verification() -> None:
    engine = enabled_engine()
    first = engine.evaluate(
        frame(observations=safe_observations(pool_source="H0001"))
    )
    assert first.candidate is not None
    engine.record_accepted_delivery(first.candidate, accepted_at=NOW)

    same = engine.evaluate(
        frame(
            at=NOW,
            identity="frame-same-time",
            observations=safe_observations(at=NOW, pool_source="00000"),
        )
    )
    assert same.lifecycle is GridOutageSafetyLifecycle.AWAITING_VERIFICATION

    later_at = NOW + timedelta(seconds=1)
    later = engine.evaluate(
        frame(
            at=later_at,
            identity="frame-2",
            observations=safe_observations(at=later_at, pool_source="00000"),
        )
    )
    assert later.lifecycle is GridOutageSafetyLifecycle.PROGRESS
    assert later.last_verified_reduction is GridOutageReductionKind.POOL_SOURCE_OFF


def test_matching_value_from_wrong_native_object_cannot_verify() -> None:
    engine = enabled_engine()
    first = engine.evaluate(
        frame(observations=safe_observations(pool_source="H0001"))
    )
    assert first.candidate is not None
    engine.record_accepted_delivery(first.candidate, accepted_at=NOW)

    later_at = NOW + timedelta(seconds=1)
    observations = list(
        safe_observations(at=later_at, pool_source="00000")
    )
    for index, item in enumerate(observations):
        if item.observation_id == "pool.raw_heater_id":
            observations[index] = observation(
                "pool.raw_heater_id",
                "00000",
                at=later_at,
                native_object_id="B1202",
            )
            break
    else:
        raise AssertionError("pool.raw_heater_id observation missing")

    result = engine.evaluate(
        frame(
            at=later_at,
            identity="wrong-native-object",
            observations=tuple(observations),
        )
    )

    assert result.lifecycle is GridOutageSafetyLifecycle.FAILED
    assert result.last_verified_reduction is None
    assert result.attempt is None


def test_distinct_confirmed_outage_epoch_cannot_verify_prior_attempt() -> None:
    engine = enabled_engine()
    first = engine.evaluate(
        frame(observations=safe_observations(pool_source="H0001"))
    )
    assert first.candidate is not None
    engine.record_accepted_delivery(first.candidate, accepted_at=NOW)

    later_at = NOW + timedelta(seconds=10)
    epoch_b = confirmed(
        later_at,
        epoch_started_at=later_at - timedelta(seconds=2),
        confirmed_at=later_at,
    )
    result = engine.evaluate(
        GridOutageSafetyFrame(
            frame_identity="epoch-b-frame",
            observed_at=later_at,
            observations=safe_observations(at=later_at, pool_source="00000"),
            outage=epoch_b,
            filtration=filtration(FiltrationDisposition.CREDITING, at=later_at),
            physical_authority_ready=True,
            transport_ready=True,
        )
    )

    assert result.last_verified_reduction is None
    assert result.attempt is None
    assert result.candidate is None
    assert result.lifecycle is GridOutageSafetyLifecycle.BLOCKED
    assert result.reason_code == "grid_outage_prior_epoch_attempt_invalidated"


def test_external_takeover_after_delivery_invalidates_attempt_before_matching_verification() -> None:
    engine = enabled_engine()
    first = engine.evaluate(
        frame(observations=safe_observations(pool_source="H0001"))
    )
    assert first.candidate is not None
    engine.record_accepted_delivery(first.candidate, accepted_at=NOW)

    later_at = NOW + timedelta(seconds=1)
    result = engine.evaluate(
        frame(
            at=later_at,
            identity="external-takeover",
            observations=safe_observations(at=later_at, pool_source="00000"),
            external_preemption_reason="grid_outage_external_takeover:spa.active",
        )
    )

    assert result.lifecycle is GridOutageSafetyLifecycle.FAILED
    assert result.last_verified_reduction is None
    assert result.attempt is None
    assert result.reason_code == "grid_outage_external_takeover:spa.active"


def test_proven_zero_transport_rejection_allows_only_a_later_fresh_frame() -> None:
    engine = enabled_engine()
    first = engine.evaluate(
        frame(observations=safe_observations(pool_source="H0001"))
    )
    assert first.candidate is not None
    rejected = engine.record_pre_dispatch_rejection(
        first.candidate,
        rejected_at=NOW + timedelta(milliseconds=1),
        reason="grid_outage_context_stale",
    )
    assert rejected.lifecycle is GridOutageSafetyLifecycle.BLOCKED
    assert rejected.attempt is None
    assert not rejected.command_delivery_performed

    same = engine.evaluate(
        frame(observations=safe_observations(pool_source="H0001"))
    )
    assert same.candidate is None
    assert same.reason_code == "grid_outage_frame_already_dispatched"

    later_at = NOW + timedelta(seconds=1)
    later = engine.evaluate(
        frame(
            at=later_at,
            identity="fresh-after-rejection",
            observations=safe_observations(at=later_at, pool_source="H0001"),
        )
    )
    assert later.lifecycle is GridOutageSafetyLifecycle.CANDIDATE_READY


def test_external_preemption_uses_only_uncorrelated_relevant_post_authority_events() -> None:
    correlation = NativeConsequenceAttribution(
        expectation_id="expectation",
        request_id="request",
        request_source=PhysicalRequestSource.GRID_OUTAGE_SAFETY,
        operation="body_heat_source",
        target="B1101",
    )
    batch = ExternalChangeBatch(
        (
            external_event("spa.active"),
            external_event("unrelated.optional", at=NOW + timedelta(milliseconds=1)),
        ),
        (correlation,),
    )
    assert grid_outage_external_preemption_reason(
        batch,
        authority_not_before=NOW - timedelta(microseconds=1),
        evaluated_at=NOW + timedelta(seconds=1),
    ) == "grid_outage_external_takeover:spa.active"

    expected_only = ExternalChangeBatch((), (correlation,))
    assert grid_outage_external_preemption_reason(
        expected_only,
        authority_not_before=NOW,
        evaluated_at=NOW + timedelta(seconds=1),
    ) is None

    stale = ExternalChangeBatch(
        (external_event("spa.active", at=NOW - timedelta(seconds=1)),)
    )
    assert grid_outage_external_preemption_reason(
        stale,
        authority_not_before=NOW,
        evaluated_at=NOW + timedelta(seconds=1),
    ) is None


def test_external_takeover_invalidates_only_authority_formed_before_it() -> None:
    takeover_at = NOW + timedelta(seconds=1)
    retained = ExternalChangeBatch(
        (external_event("spa.active", at=takeover_at),)
    )

    assert grid_outage_external_preemption_reason(
        retained,
        authority_not_before=NOW,
        evaluated_at=NOW + timedelta(seconds=2),
    ) == "grid_outage_external_takeover:spa.active"

    assert grid_outage_external_preemption_reason(
        retained,
        authority_not_before=NOW + timedelta(seconds=2),
        evaluated_at=NOW + timedelta(seconds=3),
    ) is None

    newer_at = NOW + timedelta(seconds=3)
    newer = ExternalChangeBatch(
        (external_event("spa.active", at=newer_at),)
    )
    assert grid_outage_external_preemption_reason(
        newer,
        authority_not_before=NOW + timedelta(seconds=2),
        evaluated_at=NOW + timedelta(seconds=4),
    ) == "grid_outage_external_takeover:spa.active"


@pytest.mark.parametrize(
    ("before", "after", "kind"),
    (
        (
            {"pool": False, "spa": True, "spa_source": "H0001"},
            {"pool": False, "spa": True, "spa_source": "00000"},
            GridOutageReductionKind.SPA_SOURCE_OFF,
        ),
        (
            {"pool_source": "H0002"},
            {"pool_source": "00000"},
            GridOutageReductionKind.POOL_SOURCE_OFF,
        ),
        ({"light": True}, {"light": False}, GridOutageReductionKind.POOL_LIGHT_OFF),
        ({"jets": True}, {"jets": False}, GridOutageReductionKind.JETS_OFF),
        ({"slide": True}, {"slide": False}, GridOutageReductionKind.SLIDE_OFF),
        (
            {"waterfall": True},
            {"waterfall": False},
            GridOutageReductionKind.WATERFALL_OFF,
        ),
        (
            {"pool": False, "spa": True},
            {"pool": False, "spa": False},
            GridOutageReductionKind.SPA_BODY_OFF,
        ),
    ),
)
def test_each_nonpump_reduction_requires_later_exact_native_verification(
    before: dict[str, object],
    after: dict[str, object],
    kind: GridOutageReductionKind,
) -> None:
    engine = enabled_engine()
    first = engine.evaluate(
        frame(observations=safe_observations(**before))  # type: ignore[arg-type]
    )
    assert first.candidate is not None
    assert first.candidate.kind is kind
    engine.record_accepted_delivery(first.candidate, accepted_at=NOW)

    later_at = NOW + timedelta(seconds=1)
    verified = engine.evaluate(
        frame(
            at=later_at,
            identity=f"verified-{kind.value}",
            observations=safe_observations(at=later_at, **after),  # type: ignore[arg-type]
        )
    )
    assert verified.lifecycle is GridOutageSafetyLifecycle.PROGRESS
    assert verified.last_verified_reduction is kind


def test_pump_verification_requires_configured_and_actual_later_truth() -> None:
    engine = enabled_engine()
    first = engine.evaluate(frame())
    candidate = cast(object, first.candidate)
    assert first.candidate is not None
    engine.record_accepted_delivery(first.candidate, accepted_at=NOW)
    later_at = NOW + timedelta(seconds=1)
    wrong_actual = engine.evaluate(
        frame(
            at=later_at,
            identity="frame-2",
            observations=safe_observations(at=later_at, configured=1500, rpm=1600),
        )
    )
    assert candidate is not None
    assert wrong_actual.lifecycle is GridOutageSafetyLifecycle.FAILED


@pytest.mark.parametrize(("actual", "verified"), ((1475, True), (1525, True), (1474, False), (1526, False)))
def test_pump_verification_preserves_inclusive_25_rpm_tolerance(
    actual: int, verified: bool
) -> None:
    engine = enabled_engine()
    first = engine.evaluate(frame())
    assert first.candidate is not None
    engine.record_accepted_delivery(first.candidate, accepted_at=NOW)
    later_at = NOW + timedelta(seconds=1)
    result = engine.evaluate(
        frame(
            at=later_at,
            identity=f"frame-{actual}",
            observations=safe_observations(
                at=later_at,
                configured=1500,
                rpm=actual,
            ),
        )
    )
    assert (result.lifecycle is GridOutageSafetyLifecycle.PROGRESS) is verified


def test_unknown_after_confirmed_cannot_verify_or_authorize_new_reduction() -> None:
    engine = enabled_engine()
    first = engine.evaluate(
        frame(observations=safe_observations(pool_source="H0001"))
    )
    assert first.candidate is not None
    engine.record_accepted_delivery(first.candidate, accepted_at=NOW)

    later_at = NOW + timedelta(seconds=1)
    unresolved = frame(
        at=later_at,
        identity="unresolved-frame",
        observations=safe_observations(at=later_at, pool_source="00000"),
    )
    unresolved = GridOutageSafetyFrame(
        frame_identity=unresolved.frame_identity,
        observed_at=unresolved.observed_at,
        observations=unresolved.observations,
        outage=outage_assessment(
            GridOutageDisposition.UNKNOWN,
            at=later_at,
            unresolved_since=NOW,
        ),
        filtration=unresolved.filtration,
        physical_authority_ready=True,
        transport_ready=True,
    )
    result = engine.evaluate(unresolved)
    assert result.lifecycle is GridOutageSafetyLifecycle.UNRESOLVED_OUTAGE
    assert result.attempt is not None
    assert result.last_verified_reduction is None
    assert result.candidate is None
    assert not result.command_delivery_enabled

    expired_at = NOW + timedelta(seconds=45)
    expired = GridOutageSafetyFrame(
        frame_identity="unresolved-deadline",
        observed_at=expired_at,
        observations=safe_observations(at=expired_at, pool_source="00000"),
        outage=outage_assessment(
            GridOutageDisposition.UNKNOWN,
            at=expired_at,
            unresolved_since=NOW,
        ),
        filtration=filtration(FiltrationDisposition.CREDITING, at=expired_at),
        physical_authority_ready=True,
        transport_ready=True,
    )
    timed_out = engine.evaluate(expired)
    assert timed_out.lifecycle is GridOutageSafetyLifecycle.FAILED
    assert timed_out.attempt is None
    assert timed_out.reason_code == (
        "grid_outage_verification_timed_out_while_unresolved"
    )


def test_authoritative_grid_return_ends_without_restoration_or_replay() -> None:
    engine = enabled_engine()
    first = engine.evaluate(
        frame(observations=safe_observations(pool_source="H0001"))
    )
    assert first.candidate is not None
    engine.record_accepted_delivery(first.candidate, accepted_at=NOW)

    later_at = NOW + timedelta(seconds=1)
    returned = frame(at=later_at, identity="grid-return")
    returned = GridOutageSafetyFrame(
        frame_identity=returned.frame_identity,
        observed_at=returned.observed_at,
        observations=returned.observations,
        outage=outage_assessment(GridOutageDisposition.ON_GRID, at=later_at),
        filtration=returned.filtration,
        physical_authority_ready=True,
        transport_ready=True,
    )
    result = engine.evaluate(returned)
    assert result.lifecycle is GridOutageSafetyLifecycle.ENDED
    assert result.attempt is None
    assert result.candidate is None
    assert not result.command_delivery_enabled
    assert result.reason_code == "grid_returned_authoritatively_no_restore"


def test_unload_and_grid_return_never_restore_or_replay() -> None:
    engine = enabled_engine()
    first = engine.evaluate(
        frame(observations=safe_observations(pool_source="H0001"))
    )
    assert first.candidate is not None
    engine.unload(unloaded_at=NOW + timedelta(seconds=1))
    assert not engine.gate_requested
    assert engine.assessment is not None
    assert engine.assessment.lifecycle is GridOutageSafetyLifecycle.UNLOADED
    engine.record_delivery_failure(
        failed_at=NOW + timedelta(seconds=2),
        reason="late_delivery_callback",
    )
    assert engine.assessment.lifecycle is GridOutageSafetyLifecycle.UNLOADED
    late_receipt = engine.record_accepted_delivery(
        first.candidate,
        accepted_at=NOW + timedelta(seconds=3),
    )
    assert late_receipt.lifecycle is GridOutageSafetyLifecycle.UNLOADED
    assert late_receipt.attempt is None
