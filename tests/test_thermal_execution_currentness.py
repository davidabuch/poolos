from __future__ import annotations

from dataclasses import replace
from datetime import datetime, timedelta, timezone

import pytest

from poolos.integration import PhysicalHeatMode, ThermalBody
from poolos.thermal_execution_currentness import (
    ThermalExecutionCompatibilityDisposition,
    ThermalExecutionCurrentness,
    ThermalExecutionProgress,
    ThermalExecutionPurpose,
    ThermalExecutionPurposeKind,
    ThermalOperationSignature,
    assess_execution_compatibility,
    operation_signature,
)
from poolos.thermal_execution_planning import (
    ThermalCurrentState,
    ThermalDesiredState,
    ThermalExecutionPlanAssessment,
    ThermalExecutionPlanBuilder,
)


NOW = datetime(2026, 9, 4, 12, 0, tzinfo=timezone.utc)


def _assessment(
    *,
    evaluated_at: datetime = NOW,
    requested_mode: str = "solar",
    source: PhysicalHeatMode = PhysicalHeatMode.SOLAR,
    rpm: int | None = 2900,
    target_f: float = 90.0,
    reason: str = "solar_only_physical_solar",
    current_source: PhysicalHeatMode = PhysicalHeatMode.OFF,
    current_rpm: int | None = 2600,
    body_active: bool | None = True,
    body: ThermalBody = ThermalBody.POOL,
) -> ThermalExecutionPlanAssessment:
    desired = ThermalDesiredState(
        evaluated_at=evaluated_at,
        body=body,
        requested_mode=requested_mode,
        selected_source=source,
        required_pump_rpm=rpm,
        reason_code=reason,
        rpm_reason_code=None if rpm is None else f"baseline:{rpm}",
        rationale=("Current policy result.",),
        criteria=("authoritative_evidence",),
        evidence={
            "pool_target_f" if body is ThermalBody.POOL else "spa_target_f": target_f
        },
    )
    current = ThermalCurrentState(
        observed_at=evaluated_at,
        body=body,
        selected_source=current_source,
        pump_rpm=current_rpm,
        body_active=body_active,
    )
    return ThermalExecutionPlanBuilder().build(desired, current)


def _currentness(
    assessment: ThermalExecutionPlanAssessment,
    evaluation_id: str,
) -> ThermalExecutionCurrentness:
    return ThermalExecutionCurrentness.from_assessment(
        assessment,
        evaluation_id=evaluation_id,
    )


def _signature(
    assessment: ThermalExecutionPlanAssessment,
    index: int,
) -> ThermalOperationSignature:
    return operation_signature(
        assessment.operations[index],
        assessment.step_specifications[index].metadata,
    )


def test_same_semantic_purpose_is_stable_across_evaluation_epochs() -> None:
    first = _currentness(_assessment(), "evaluation-1")
    second = _currentness(
        _assessment(evaluated_at=NOW + timedelta(seconds=1)),
        "evaluation-2",
    )

    assert first.evaluation_id != second.evaluation_id
    assert first.plan_id != second.plan_id
    assert first.purpose == second.purpose
    assert first.purpose.purpose_id == second.purpose.purpose_id
    assert (
        assess_execution_compatibility(first, second).disposition
        is ThermalExecutionCompatibilityDisposition.SAME_PURPOSE
    )


@pytest.mark.parametrize(
    ("body", "requested_mode", "source", "rpm"),
    (
        (ThermalBody.POOL, "solar", PhysicalHeatMode.SOLAR, 2900),
        (ThermalBody.POOL, "gas", PhysicalHeatMode.GAS, 3000),
        (ThermalBody.HOT_TUB, "gas", PhysicalHeatMode.GAS, 3000),
    ),
)
@pytest.mark.parametrize("elapsed", (timedelta(seconds=1), timedelta(seconds=30)))
def test_supported_body_purposes_survive_normal_epoch_churn(
    body: ThermalBody,
    requested_mode: str,
    source: PhysicalHeatMode,
    rpm: int,
    elapsed: timedelta,
) -> None:
    first = _currentness(
        _assessment(
            body=body,
            requested_mode=requested_mode,
            source=source,
            rpm=rpm,
        ),
        "evaluation-1",
    )
    second = _currentness(
        _assessment(
            evaluated_at=NOW + elapsed,
            body=body,
            requested_mode=requested_mode,
            source=source,
            rpm=rpm,
        ),
        "evaluation-2",
    )

    assert first.purpose == second.purpose
    assert (
        assess_execution_compatibility(first, second).disposition
        is ThermalExecutionCompatibilityDisposition.SAME_PURPOSE
    )


def test_pool_and_hot_tub_never_share_an_execution_purpose() -> None:
    pool = _currentness(_assessment(), "pool-evaluation")
    hot_tub = _currentness(
        _assessment(body=ThermalBody.HOT_TUB),
        "hot-tub-evaluation",
    )

    assert pool.purpose.purpose_id != hot_tub.purpose.purpose_id
    assert (
        assess_execution_compatibility(pool, hot_tub).disposition
        is ThermalExecutionCompatibilityDisposition.SUPERSEDED
    )


@pytest.mark.parametrize(
    "changed",
    (
        _assessment(requested_mode="gas", source=PhysicalHeatMode.GAS, rpm=3000),
        _assessment(requested_mode="solar_preferred"),
        _assessment(target_f=91.0),
        _assessment(requested_mode="off", source=PhysicalHeatMode.OFF, rpm=None),
    ),
)
def test_material_purpose_change_supersedes(changed: ThermalExecutionPlanAssessment) -> None:
    originating = _currentness(_assessment(), "evaluation-1")
    current = _currentness(changed, "evaluation-2")

    decision = assess_execution_compatibility(originating, current)

    assert (
        decision.disposition
        is ThermalExecutionCompatibilityDisposition.SUPERSEDED
    )
    assert decision.execution_purpose_id is None


def test_requested_solar_selected_off_is_distinct_from_explicit_off() -> None:
    solar_unavailable = _currentness(
        _assessment(
            requested_mode="solar",
            source=PhysicalHeatMode.OFF,
            rpm=None,
            reason="solar_not_eligible",
            current_source=PhysicalHeatMode.SOLAR,
            current_rpm=2600,
        ),
        "evaluation-solar",
    )
    explicit_off = _currentness(
        _assessment(
            requested_mode="off",
            source=PhysicalHeatMode.OFF,
            rpm=None,
            reason="requested_heat_mode_off",
            current_source=PhysicalHeatMode.SOLAR,
            current_rpm=2600,
        ),
        "evaluation-off",
    )

    assert solar_unavailable.purpose.kind is ThermalExecutionPurposeKind.THERMAL_CONTROL
    assert explicit_off.purpose.kind is ThermalExecutionPurposeKind.EXPLICIT_OFF
    assert solar_unavailable.purpose != explicit_off.purpose


def test_probe_purpose_cannot_be_confused_with_arbitrary_off_source_circulation() -> None:
    probe = _currentness(
        _assessment(
            requested_mode="solar",
            source=PhysicalHeatMode.OFF,
            rpm=1500,
            reason="pool_temperature_probe_required",
            current_rpm=0,
            body_active=False,
        ),
        "evaluation-probe",
    )
    non_probe = _currentness(
        _assessment(
            requested_mode="solar",
            source=PhysicalHeatMode.OFF,
            rpm=None,
            reason="solar_not_eligible",
            current_source=PhysicalHeatMode.SOLAR,
            current_rpm=2600,
        ),
        "evaluation-other",
    )

    assert probe.purpose.kind is ThermalExecutionPurposeKind.POOL_TEMPERATURE_PROBE
    assert probe.purpose != non_probe.purpose


def test_residual_plan_may_advance_only_from_poolos_verified_progress() -> None:
    original_assessment = _assessment(current_rpm=0, body_active=False)
    after_activation = _assessment(current_rpm=0, body_active=True)
    originating = _currentness(original_assessment, "evaluation-1")
    current = _currentness(after_activation, "evaluation-2")
    progress = ThermalExecutionProgress(
        verified_prefix=(_signature(original_assessment, 0),),
    )

    decision = assess_execution_compatibility(
        originating,
        current,
        progress=progress,
    )

    assert (
        decision.disposition
        is ThermalExecutionCompatibilityDisposition.PROGRESS_COMPATIBLE
    )


def test_accepted_priming_explains_residual_plan_before_verification() -> None:
    original_assessment = _assessment(current_rpm=0, body_active=False)
    after_priming_effect = _assessment(current_rpm=3000, body_active=True)
    originating = _currentness(original_assessment, "evaluation-1")
    current = _currentness(after_priming_effect, "evaluation-2")
    progress = ThermalExecutionProgress(
        verified_prefix=(_signature(original_assessment, 0),),
        accepted_current=_signature(original_assessment, 1),
    )

    decision = assess_execution_compatibility(
        originating,
        current,
        progress=progress,
    )

    assert (
        decision.disposition
        is ThermalExecutionCompatibilityDisposition.PROGRESS_COMPATIBLE
    )
    assert tuple(item.role for item in current.residual_plan.operations) == (
        "thermal_pump_target",
        "heat_source",
    )


@pytest.mark.parametrize(
    ("body", "requested_mode", "source", "rpm"),
    (
        (ThermalBody.POOL, "solar", PhysicalHeatMode.SOLAR, 2900),
        (ThermalBody.POOL, "gas", PhysicalHeatMode.GAS, 3000),
        (ThermalBody.HOT_TUB, "gas", PhysicalHeatMode.GAS, 3000),
    ),
)
def test_cold_start_progress_and_convergence_keep_one_purpose(
    body: ThermalBody,
    requested_mode: str,
    source: PhysicalHeatMode,
    rpm: int,
) -> None:
    original_assessment = _assessment(
        body=body,
        requested_mode=requested_mode,
        source=source,
        rpm=rpm,
        current_rpm=0,
        body_active=False,
    )
    originating = _currentness(original_assessment, "evaluation-origin")
    after_activation_assessment = _assessment(
        evaluated_at=NOW + timedelta(seconds=1),
        body=body,
        requested_mode=requested_mode,
        source=source,
        rpm=rpm,
        current_rpm=0,
        body_active=True,
    )
    after_activation = _currentness(
        after_activation_assessment,
        "evaluation-after-activation",
    )
    after_priming_assessment = _assessment(
        evaluated_at=NOW + timedelta(seconds=62),
        body=body,
        requested_mode=requested_mode,
        source=source,
        rpm=rpm,
        current_rpm=3000,
        body_active=True,
    )
    after_priming = _currentness(
        after_priming_assessment,
        "evaluation-after-priming",
    )
    converged = _currentness(
        _assessment(
            evaluated_at=NOW + timedelta(seconds=63),
            body=body,
            requested_mode=requested_mode,
            source=source,
            rpm=rpm,
            current_source=source,
            current_rpm=rpm,
            body_active=True,
        ),
        "evaluation-converged",
    )
    signatures = tuple(
        _signature(original_assessment, index)
        for index in range(len(original_assessment.operations))
    )

    activation_decision = assess_execution_compatibility(
        originating,
        after_activation,
        progress=ThermalExecutionProgress(verified_prefix=signatures[:1]),
    )
    priming_decision = assess_execution_compatibility(
        originating,
        after_priming,
        progress=ThermalExecutionProgress(verified_prefix=signatures[:2]),
    )
    converged_decision = assess_execution_compatibility(
        originating,
        converged,
        progress=ThermalExecutionProgress(verified_prefix=signatures),
    )

    assert activation_decision.continuation_allowed
    assert priming_decision.continuation_allowed
    assert (
        converged_decision.disposition
        is ThermalExecutionCompatibilityDisposition.CONVERGED
    )
    assert originating.purpose == converged.purpose


def test_manual_matching_prefix_removal_does_not_manufacture_progress() -> None:
    original = _currentness(
        _assessment(current_rpm=0, body_active=False),
        "evaluation-origin",
    )
    manually_activated = _currentness(
        _assessment(
            evaluated_at=NOW + timedelta(seconds=1),
            current_rpm=0,
            body_active=True,
        ),
        "evaluation-manual",
    )

    decision = assess_execution_compatibility(original, manually_activated)

    assert decision.disposition is ThermalExecutionCompatibilityDisposition.UNKNOWN
    assert decision.reason_code == "thermal_execution_residual_plan_incompatible"


def test_reordered_or_unexpectedly_grown_residual_plan_fails_closed() -> None:
    original = _currentness(_assessment(), "evaluation-origin")
    reversed_residual = replace(
        original,
        evaluation_id="evaluation-reordered",
        plan_id="plan-reordered",
        residual_plan=replace(
            original.residual_plan,
            operations=tuple(reversed(original.residual_plan.operations)),
        ),
    )
    shortened_origin = _currentness(
        _assessment(current_rpm=2900),
        "evaluation-short-origin",
    )
    grown = _currentness(
        _assessment(
            evaluated_at=NOW + timedelta(seconds=1),
            current_rpm=2600,
        ),
        "evaluation-grown",
    )

    assert (
        assess_execution_compatibility(original, reversed_residual).disposition
        is ThermalExecutionCompatibilityDisposition.UNKNOWN
    )
    assert (
        assess_execution_compatibility(shortened_origin, grown).disposition
        is ThermalExecutionCompatibilityDisposition.UNKNOWN
    )


def test_blocked_same_purpose_plan_fails_closed() -> None:
    original_assessment = _assessment()
    originating = _currentness(original_assessment, "evaluation-origin")
    blocked_assessment = ThermalExecutionPlanBuilder().build(
        replace(
            original_assessment.desired,
            evaluated_at=NOW + timedelta(seconds=1),
            blockers=("required_evidence_unusable",),
        ),
        ThermalCurrentState(
            observed_at=NOW + timedelta(seconds=1),
            body=ThermalBody.POOL,
            selected_source=PhysicalHeatMode.OFF,
            pump_rpm=2600,
            body_active=True,
        ),
    )
    current = _currentness(blocked_assessment, "evaluation-blocked")

    decision = assess_execution_compatibility(originating, current)

    assert decision.disposition is ThermalExecutionCompatibilityDisposition.UNKNOWN
    assert decision.reason_code == "thermal_execution_current_plan_blocked"


def test_external_lookalike_convergence_without_progress_fails_closed() -> None:
    originating = _currentness(_assessment(), "evaluation-1")
    converged = _currentness(
        _assessment(
            evaluated_at=NOW + timedelta(seconds=1),
            current_source=PhysicalHeatMode.SOLAR,
            current_rpm=2900,
        ),
        "evaluation-2",
    )

    decision = assess_execution_compatibility(originating, converged)

    assert decision.disposition is ThermalExecutionCompatibilityDisposition.UNKNOWN
    assert decision.reason_code == "thermal_execution_convergence_not_attributed"


def test_malformed_or_unsupported_purpose_identity_is_rejected() -> None:
    purpose = _currentness(_assessment(), "evaluation-1").purpose

    with pytest.raises(ValueError, match="malformed"):
        replace(purpose, purpose_id="not-canonical")
    with pytest.raises(ValueError, match="unsupported"):
        ThermalExecutionPurpose(
            purpose_id=purpose.purpose_id,
            body=purpose.body,
            requested_mode=purpose.requested_mode,
            selected_source=purpose.selected_source,
            required_pump_rpm=purpose.required_pump_rpm,
            target_temperature_f=purpose.target_temperature_f,
            kind=purpose.kind,
            schema_version=2,
        )
