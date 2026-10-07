from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from poolos.operating_baselines import PumpOperatingBaselines
from poolos.pump_operating_target import (
    PumpOperatingTarget,
    PumpOperatingTargetPolicy,
    PumpTargetUnit,
)
from poolos.pump_speed_session import (
    PumpSpeedOverrideSource,
    PumpSpeedOverrideState,
    PumpSpeedSessionBody,
    PumpSpeedSessionPurpose,
)
from poolos.pump_target_session import (
    PumpTargetNativeTransition,
    PumpTargetSessionEvidence,
    PumpTargetSessionRuntime,
)


NOW = datetime(2026, 9, 30, 12, 0, tzinfo=timezone.utc)
RPM = PumpTargetUnit.RPM
GPM = PumpTargetUnit.GPM


def policy() -> PumpOperatingTargetPolicy:
    legacy = PumpOperatingTargetPolicy.from_rpm_baselines(PumpOperatingBaselines())
    return PumpOperatingTargetPolicy(
        filtration=PumpOperatingTarget(GPM, 42),
        solar_heating=PumpOperatingTarget(GPM, 48),
        gas_heating=PumpOperatingTarget(GPM, 55),
        temperature_probe=legacy.temperature_probe,
        priming=legacy.priming,
        grid_outage=legacy.grid_outage,
        sanitation=legacy.sanitation,
        spillway=legacy.spillway,
    )


def evidence(
    at: datetime,
    target: PumpOperatingTarget,
    *,
    purpose: PumpSpeedSessionPurpose = PumpSpeedSessionPurpose.ORDINARY,
    generation: int = 1,
) -> PumpTargetSessionEvidence:
    return PumpTargetSessionEvidence(
        observed_at=at,
        body=PumpSpeedSessionBody.POOL,
        purpose=purpose,
        pump_circuit_id="p0102",
        configured_target=target,
        connection_generation=generation,
        evidence_usable=True,
    )


def test_gpm_baseline_is_exact_configured_target() -> None:
    runtime = PumpTargetSessionRuntime(policy())
    runtime.observe(evidence(NOW, PumpOperatingTarget(GPM, 42)))

    assert runtime.snapshot.configured_baseline_target == PumpOperatingTarget(GPM, 42)
    assert runtime.snapshot.effective_target == PumpOperatingTarget(GPM, 42)
    assert runtime.snapshot.override_state is PumpSpeedOverrideState.NONE


def test_unit_change_is_a_true_session_boundary_and_clears_override() -> None:
    runtime = PumpTargetSessionRuntime(policy())
    runtime.observe(evidence(NOW, PumpOperatingTarget(GPM, 42)))
    runtime.apply_transition(
        PumpTargetNativeTransition(
            concept="pool.pump_circuit.configured_flow_gpm",
            native_object_id="p0102",
            previous_target=PumpOperatingTarget(GPM, 42),
            new_target=PumpOperatingTarget(GPM, 50),
            observed_at=NOW + timedelta(seconds=1),
            positive_operator_intent=True,
        )
    )
    assert runtime.snapshot.override_state is PumpSpeedOverrideState.VERIFIED
    assert runtime.snapshot.override_source is PumpSpeedOverrideSource.EXTERNAL_UNATTRIBUTED

    runtime.observe(
        evidence(
            NOW + timedelta(seconds=2),
            PumpOperatingTarget(RPM, 2600),
        )
    )
    assert runtime.snapshot.override_state is PumpSpeedOverrideState.NONE
    assert runtime.snapshot.last_session_transition_reason == (
        "semantic_body_purpose_or_unit_changed"
    )


def test_same_unit_external_gpm_change_is_session_scoped_override() -> None:
    runtime = PumpTargetSessionRuntime(policy())
    runtime.observe(evidence(NOW, PumpOperatingTarget(GPM, 42)))

    runtime.apply_transition(
        PumpTargetNativeTransition(
            concept="pool.pump_circuit.configured_flow_gpm",
            native_object_id="p0102",
            previous_target=PumpOperatingTarget(GPM, 42),
            new_target=PumpOperatingTarget(GPM, 50),
            observed_at=NOW + timedelta(seconds=1),
            positive_operator_intent=True,
        )
    )
    assert runtime.snapshot.effective_target == PumpOperatingTarget(GPM, 50)

    runtime.apply_transition(
        PumpTargetNativeTransition(
            concept="pool.pump_circuit.configured_flow_gpm",
            native_object_id="p0102",
            previous_target=PumpOperatingTarget(GPM, 50),
            new_target=PumpOperatingTarget(GPM, 42),
            observed_at=NOW + timedelta(seconds=2),
            positive_operator_intent=True,
        )
    )
    assert runtime.snapshot.override_state is PumpSpeedOverrideState.NONE
    assert runtime.snapshot.effective_target == PumpOperatingTarget(GPM, 42)


def test_manual_request_cannot_cross_active_policy_unit() -> None:
    runtime = PumpTargetSessionRuntime(policy())
    runtime.observe(evidence(NOW, PumpOperatingTarget(GPM, 42)))

    with pytest.raises(ValueError, match="unit must match"):
        runtime.begin_manual_request(
            body=PumpSpeedSessionBody.POOL,
            pump_circuit_id="p0102",
            requested_target=PumpOperatingTarget(RPM, 2600),
            requested_at=NOW + timedelta(seconds=1),
        )


def test_purpose_change_selects_new_unit_aware_baseline() -> None:
    runtime = PumpTargetSessionRuntime(policy())
    runtime.observe(evidence(NOW, PumpOperatingTarget(GPM, 42)))
    runtime.observe(
        evidence(
            NOW + timedelta(seconds=1),
            PumpOperatingTarget(GPM, 48),
            purpose=PumpSpeedSessionPurpose.SOLAR,
        )
    )
    assert runtime.snapshot.effective_target == PumpOperatingTarget(GPM, 48)
    assert runtime.snapshot.last_session_transition_reason == (
        "semantic_body_purpose_or_unit_changed"
    )


def test_all_rpm_policy_matches_legacy_baselines_exactly() -> None:
    baselines = PumpOperatingBaselines()
    runtime = PumpTargetSessionRuntime(
        PumpOperatingTargetPolicy.from_rpm_baselines(baselines)
    )
    runtime.observe(evidence(NOW, PumpOperatingTarget(RPM, 2600)))
    assert runtime.snapshot.effective_target == PumpOperatingTarget(
        RPM, baselines.filtration_rpm
    )
