from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from poolos.operating_baselines import PumpOperatingBaselines
from poolos.pump_speed_session import (
    PumpSpeedNativeTransition,
    PumpSpeedOverrideSource,
    PumpSpeedOverrideState,
    PumpSpeedSessionBody,
    PumpSpeedSessionEvidence,
    PumpSpeedSessionPurpose,
    PumpSpeedSessionRuntime,
)


NOW = datetime(2026, 9, 10, 16, 0, tzinfo=UTC)
BASELINES = PumpOperatingBaselines(
    filtration_rpm=2650,
    solar_heating_rpm=2950,
    gas_heating_rpm=3050,
    temperature_probe_rpm=1550,
    priming_rpm=3100,
    grid_outage_rpm=1600,
)


def evidence(
    *,
    at: datetime = NOW,
    body: PumpSpeedSessionBody | None = PumpSpeedSessionBody.POOL,
    purpose: PumpSpeedSessionPurpose | None = PumpSpeedSessionPurpose.ORDINARY,
    pump: str | None = "p0102",
    rpm: int | None = 2650,
    generation: int = 1,
    usable: bool = True,
) -> PumpSpeedSessionEvidence:
    return PumpSpeedSessionEvidence(
        observed_at=at,
        body=body,
        purpose=purpose,
        pump_circuit_id=pump,
        configured_speed_rpm=rpm,
        connection_generation=generation,
        evidence_usable=usable,
    )


def verified_manual(
    runtime: PumpSpeedSessionRuntime,
    rpm: int = 3200,
    *,
    at: datetime = NOW + timedelta(seconds=1),
) -> None:
    request = runtime.begin_manual_request(
        body=PumpSpeedSessionBody.POOL,
        pump_circuit_id="p0102",
        requested_rpm=rpm,
        requested_at=at,
        request_id=f"request-{rpm}",
    )
    runtime.manual_delivery_accepted(request, accepted_at=at)
    runtime.apply_transition(
        PumpSpeedNativeTransition(
            concept="pool.pump_circuit.configured_speed_rpm",
            native_object_id="p0102",
            previous_rpm=2650,
            new_rpm=rpm,
            observed_at=at + timedelta(seconds=1),
            correlated_request_id=request.request_id,
        )
    )


def test_manual_override_persists_across_same_semantic_session_churn() -> None:
    runtime = PumpSpeedSessionRuntime(BASELINES)
    original = runtime.observe(evidence())
    verified_manual(runtime)

    for offset in (5, 10, 30, 60):
        current = runtime.observe(
            evidence(at=NOW + timedelta(seconds=offset), rpm=3200)
        )
        assert current.session_id == original.session_id
        assert current.override_state is PumpSpeedOverrideState.VERIFIED
        assert current.effective_rpm == 3200
    assert runtime.baselines.filtration_rpm == 2650


@pytest.mark.parametrize(
    ("purpose", "baseline"),
    [
        (PumpSpeedSessionPurpose.ORDINARY, 2650),
        (PumpSpeedSessionPurpose.SOLAR, 2950),
        (PumpSpeedSessionPurpose.GAS, 3050),
        (PumpSpeedSessionPurpose.TEMPERATURE_PROBE, 1550),
        (PumpSpeedSessionPurpose.PRIMING, 3100),
        (PumpSpeedSessionPurpose.GRID_OUTAGE, 1600),
    ],
)
def test_each_semantic_session_uses_configured_baseline(
    purpose: PumpSpeedSessionPurpose,
    baseline: int,
) -> None:
    runtime = PumpSpeedSessionRuntime(BASELINES)
    assert runtime.observe(evidence(purpose=purpose, rpm=baseline)).effective_rpm == baseline


def test_true_purpose_body_and_off_boundaries_clear_override() -> None:
    runtime = PumpSpeedSessionRuntime(BASELINES)
    first = runtime.observe(evidence())
    verified_manual(runtime)

    solar = runtime.observe(
        evidence(
            at=NOW + timedelta(minutes=1),
            purpose=PumpSpeedSessionPurpose.SOLAR,
            rpm=2950,
        )
    )
    assert solar.session_id != first.session_id
    assert solar.override_state is PumpSpeedOverrideState.NONE
    assert solar.effective_rpm == 2950

    hot_tub = runtime.observe(
        evidence(
            at=NOW + timedelta(minutes=2),
            body=PumpSpeedSessionBody.HOT_TUB,
            purpose=PumpSpeedSessionPurpose.SOLAR,
            pump="p0198",
            rpm=2950,
        )
    )
    assert hot_tub.session_id != solar.session_id
    assert hot_tub.override_state is PumpSpeedOverrideState.NONE

    inactive = runtime.observe(
        evidence(
            at=NOW + timedelta(minutes=3),
            body=None,
            purpose=None,
            pump=None,
            rpm=None,
        )
    )
    assert not inactive.active
    assert inactive.override_state is PumpSpeedOverrideState.NONE


@pytest.mark.parametrize(
    ("special_purpose", "special_baseline"),
    (
        (PumpSpeedSessionPurpose.TEMPERATURE_PROBE, 1550),
        (PumpSpeedSessionPurpose.PRIMING, 3100),
        (PumpSpeedSessionPurpose.GRID_OUTAGE, 1600),
    ),
)
def test_special_purpose_entry_and_exit_are_hard_override_boundaries(
    special_purpose: PumpSpeedSessionPurpose,
    special_baseline: int,
) -> None:
    runtime = PumpSpeedSessionRuntime(BASELINES)
    ordinary = runtime.observe(evidence())
    verified_manual(runtime)

    special = runtime.observe(
        evidence(
            at=NOW + timedelta(minutes=1),
            purpose=special_purpose,
            rpm=special_baseline,
        )
    )
    assert special.session_id != ordinary.session_id
    assert special.override_state is PumpSpeedOverrideState.NONE
    assert special.effective_rpm == special_baseline
    special_request = runtime.begin_manual_request(
        body=PumpSpeedSessionBody.POOL,
        pump_circuit_id="p0102",
        requested_rpm=special_baseline + 100,
        requested_at=NOW + timedelta(minutes=1, seconds=1),
    )
    runtime.manual_delivery_accepted(
        special_request,
        accepted_at=NOW + timedelta(minutes=1, seconds=1),
    )

    ordinary_again = runtime.observe(
        evidence(
            at=NOW + timedelta(minutes=2),
            purpose=PumpSpeedSessionPurpose.ORDINARY,
            rpm=2650,
        )
    )
    assert ordinary_again.session_id != special.session_id
    assert ordinary_again.override_state is PumpSpeedOverrideState.NONE
    assert ordinary_again.effective_rpm == 2650


def test_requested_source_without_actual_purpose_change_does_not_clear_override() -> None:
    runtime = PumpSpeedSessionRuntime(BASELINES)
    session = runtime.observe(evidence())
    verified_manual(runtime)

    # Requested/selected source does not appear in evidence. Only the actual
    # operating-purpose transition changes this semantic session.
    same = runtime.observe(evidence(at=NOW + timedelta(minutes=1), rpm=3200))
    assert same.session_id == session.session_id
    assert same.effective_rpm == 3200


def test_same_timestamp_conflict_cannot_change_session_or_override() -> None:
    runtime = PumpSpeedSessionRuntime(BASELINES)
    original = runtime.observe(evidence())
    verified_manual(runtime)

    conflict = runtime.observe(
        evidence(
            purpose=PumpSpeedSessionPurpose.SOLAR,
            rpm=2950,
        )
    )
    assert conflict.session_id == original.session_id
    assert conflict.purpose is PumpSpeedSessionPurpose.ORDINARY
    assert conflict.effective_rpm == 3200


def test_startup_mismatch_is_anchor_not_override_and_repetition_does_not_adopt() -> None:
    runtime = PumpSpeedSessionRuntime(BASELINES)
    first = runtime.observe(evidence(rpm=2900))
    second = runtime.observe(evidence(at=NOW + timedelta(seconds=10), rpm=2900))

    assert first.override_state is PumpSpeedOverrideState.NONE
    assert second.override_state is PumpSpeedOverrideState.NONE
    assert second.effective_rpm == 2650


def test_new_external_transition_is_adopted_only_after_session_establishment() -> None:
    runtime = PumpSpeedSessionRuntime(BASELINES)
    runtime.observe(evidence())
    runtime.apply_transition(
        PumpSpeedNativeTransition(
            concept="pool.pump_circuit.configured_speed_rpm",
            native_object_id="p0102",
            previous_rpm=2650,
            new_rpm=3200,
            observed_at=NOW + timedelta(seconds=1),
        )
    )

    state = runtime.snapshot
    assert state.override_state is PumpSpeedOverrideState.VERIFIED
    assert state.override_source is PumpSpeedOverrideSource.EXTERNAL_UNATTRIBUTED
    assert state.effective_rpm == 3200


def test_external_return_to_baseline_cancels_override_without_mutating_policy() -> None:
    runtime = PumpSpeedSessionRuntime(BASELINES)
    runtime.observe(evidence())
    runtime.apply_transition(
        PumpSpeedNativeTransition(
            "pool.pump_circuit.configured_speed_rpm",
            "p0102",
            2650,
            3200,
            NOW + timedelta(seconds=1),
        )
    )
    runtime.apply_transition(
        PumpSpeedNativeTransition(
            "pool.pump_circuit.configured_speed_rpm",
            "p0102",
            3200,
            2650,
            NOW + timedelta(seconds=2),
        )
    )

    assert runtime.snapshot.override_state is PumpSpeedOverrideState.NONE
    assert runtime.snapshot.effective_rpm == 2650
    assert runtime.baselines is BASELINES


def test_explicit_baseline_request_hands_back_governance_even_if_delivery_fails() -> None:
    runtime = PumpSpeedSessionRuntime(BASELINES)
    runtime.observe(evidence())
    verified_manual(runtime, 3200)

    cancellation = runtime.begin_manual_request(
        body=PumpSpeedSessionBody.POOL,
        pump_circuit_id="p0102",
        requested_rpm=2650,
        requested_at=NOW + timedelta(seconds=5),
        request_id="return-to-baseline",
    )
    assert runtime.snapshot.override_state is PumpSpeedOverrideState.NONE
    assert runtime.snapshot.effective_rpm == 2650

    runtime.manual_delivery_failed(cancellation)
    assert runtime.snapshot.override_state is PumpSpeedOverrideState.NONE
    assert runtime.snapshot.effective_rpm == 2650
    assert runtime.baselines.filtration_rpm == 2650


def test_pending_is_not_verified_by_acceptance_and_failure_restores_prior() -> None:
    runtime = PumpSpeedSessionRuntime(BASELINES)
    runtime.observe(evidence())
    verified_manual(runtime, 3200)
    request = runtime.begin_manual_request(
        body=PumpSpeedSessionBody.POOL,
        pump_circuit_id="p0102",
        requested_rpm=3100,
        requested_at=NOW + timedelta(seconds=5),
        request_id="new-request",
    )
    runtime.manual_delivery_accepted(request, accepted_at=NOW + timedelta(seconds=5))
    assert runtime.snapshot.override_state is PumpSpeedOverrideState.PENDING

    runtime.manual_delivery_failed(request)
    assert runtime.snapshot.override_state is PumpSpeedOverrideState.VERIFIED
    assert runtime.snapshot.effective_rpm == 3200


def test_superseded_request_cannot_be_resurrected_by_late_correlation() -> None:
    runtime = PumpSpeedSessionRuntime(BASELINES)
    runtime.observe(evidence())
    old = runtime.begin_manual_request(
        body=PumpSpeedSessionBody.POOL,
        pump_circuit_id="p0102",
        requested_rpm=3200,
        requested_at=NOW + timedelta(seconds=1),
        request_id="old",
    )
    runtime.manual_delivery_accepted(old, accepted_at=NOW + timedelta(seconds=1))
    new = runtime.begin_manual_request(
        body=PumpSpeedSessionBody.POOL,
        pump_circuit_id="p0102",
        requested_rpm=3100,
        requested_at=NOW + timedelta(seconds=2),
        request_id="new",
    )
    runtime.manual_delivery_accepted(new, accepted_at=NOW + timedelta(seconds=2))
    runtime.apply_transition(
        PumpSpeedNativeTransition(
            "pool.pump_circuit.configured_speed_rpm",
            "p0102",
            2650,
            3200,
            NOW + timedelta(seconds=3),
            correlated_request_id="old",
        )
    )
    assert runtime.snapshot.override_state is PumpSpeedOverrideState.PENDING
    assert runtime.snapshot.pending_requested_rpm == 3100

    runtime.apply_transition(
        PumpSpeedNativeTransition(
            "pool.pump_circuit.configured_speed_rpm",
            "p0102",
            3200,
            3100,
            NOW + timedelta(seconds=4),
            correlated_request_id="new",
        )
    )
    assert runtime.snapshot.override_state is PumpSpeedOverrideState.VERIFIED
    assert runtime.snapshot.effective_rpm == 3100


def test_failed_replacement_does_not_resurrect_superseded_pending_request() -> None:
    runtime = PumpSpeedSessionRuntime(BASELINES)
    runtime.observe(evidence())
    old = runtime.begin_manual_request(
        body=PumpSpeedSessionBody.POOL,
        pump_circuit_id="p0102",
        requested_rpm=3200,
        requested_at=NOW + timedelta(seconds=1),
        request_id="old-pending",
    )
    runtime.manual_delivery_accepted(old, accepted_at=NOW + timedelta(seconds=1))
    replacement = runtime.begin_manual_request(
        body=PumpSpeedSessionBody.POOL,
        pump_circuit_id="p0102",
        requested_rpm=3100,
        requested_at=NOW + timedelta(seconds=2),
        request_id="replacement",
    )

    runtime.manual_delivery_failed(replacement)

    assert runtime.snapshot.override_state is PumpSpeedOverrideState.NONE
    assert runtime.snapshot.effective_rpm == 2650
    runtime.apply_transition(
        PumpSpeedNativeTransition(
            "pool.pump_circuit.configured_speed_rpm",
            "p0102",
            2650,
            3200,
            NOW + timedelta(seconds=3),
            correlated_request_id="old-pending",
        )
    )
    assert runtime.snapshot.override_state is PumpSpeedOverrideState.NONE


def test_different_external_transition_supersedes_pending_manual_request() -> None:
    runtime = PumpSpeedSessionRuntime(BASELINES)
    runtime.observe(evidence())
    request = runtime.begin_manual_request(
        body=PumpSpeedSessionBody.POOL,
        pump_circuit_id="p0102",
        requested_rpm=3200,
        requested_at=NOW + timedelta(seconds=1),
        request_id="pending",
    )
    runtime.manual_delivery_accepted(request, accepted_at=NOW + timedelta(seconds=1))
    runtime.apply_transition(
        PumpSpeedNativeTransition(
            "pool.pump_circuit.configured_speed_rpm",
            "p0102",
            2650,
            3100,
            NOW + timedelta(seconds=2),
        )
    )
    assert runtime.snapshot.override_source is PumpSpeedOverrideSource.EXTERNAL_UNATTRIBUTED
    assert runtime.snapshot.effective_rpm == 3100


def test_noop_manual_nonbaseline_uses_fresh_configured_truth_after_acceptance() -> None:
    runtime = PumpSpeedSessionRuntime(BASELINES)
    runtime.observe(evidence(rpm=3200))
    request = runtime.begin_manual_request(
        body=PumpSpeedSessionBody.POOL,
        pump_circuit_id="p0102",
        requested_rpm=3200,
        requested_at=NOW + timedelta(seconds=1),
        request_id="noop",
    )
    assert runtime.snapshot.override_state is PumpSpeedOverrideState.PENDING
    runtime.manual_delivery_accepted(request, accepted_at=NOW + timedelta(seconds=1))
    assert runtime.snapshot.override_state is PumpSpeedOverrideState.VERIFIED
    assert runtime.snapshot.effective_rpm == 3200


def test_stale_matching_configured_speed_cannot_verify_noop_request() -> None:
    runtime = PumpSpeedSessionRuntime(BASELINES)
    runtime.observe(evidence(rpm=3200))
    request = runtime.begin_manual_request(
        body=PumpSpeedSessionBody.POOL,
        pump_circuit_id="p0102",
        requested_rpm=3200,
        requested_at=NOW + timedelta(seconds=31),
        request_id="stale-noop",
    )
    runtime.manual_delivery_accepted(
        request,
        accepted_at=NOW + timedelta(seconds=31),
    )

    assert runtime.snapshot.override_state is PumpSpeedOverrideState.PENDING
    assert runtime.snapshot.effective_rpm == 3200


def test_correlated_callback_before_delivery_return_verifies_only_after_acceptance() -> None:
    runtime = PumpSpeedSessionRuntime(BASELINES)
    runtime.observe(evidence())
    request = runtime.begin_manual_request(
        body=PumpSpeedSessionBody.POOL,
        pump_circuit_id="p0102",
        requested_rpm=3200,
        requested_at=NOW + timedelta(seconds=1),
        request_id="callback-race",
    )
    runtime.apply_transition(
        PumpSpeedNativeTransition(
            "pool.pump_circuit.configured_speed_rpm",
            "p0102",
            2650,
            3200,
            NOW + timedelta(seconds=2),
            correlated_request_id=request.request_id,
        )
    )
    assert runtime.snapshot.override_state is PumpSpeedOverrideState.PENDING

    runtime.manual_delivery_accepted(
        request,
        accepted_at=NOW + timedelta(seconds=3),
    )
    assert runtime.snapshot.override_state is PumpSpeedOverrideState.VERIFIED
    assert runtime.snapshot.override_source is PumpSpeedOverrideSource.POOLOS_MANUAL
    assert runtime.snapshot.effective_rpm == 3200


def test_unusable_current_evidence_blocks_new_manual_transaction() -> None:
    runtime = PumpSpeedSessionRuntime(BASELINES)
    runtime.observe(evidence())
    runtime.observe(evidence(at=NOW + timedelta(seconds=1), usable=False))

    with pytest.raises(ValueError, match="does not match an active session"):
        runtime.begin_manual_request(
            body=PumpSpeedSessionBody.POOL,
            pump_circuit_id="p0102",
            requested_rpm=3200,
            requested_at=NOW + timedelta(seconds=2),
        )


def test_pending_expires_without_losing_prior_verified_override() -> None:
    runtime = PumpSpeedSessionRuntime(BASELINES, pending_ttl=timedelta(seconds=5))
    runtime.observe(evidence())
    verified_manual(runtime, 3200)
    request = runtime.begin_manual_request(
        body=PumpSpeedSessionBody.POOL,
        pump_circuit_id="p0102",
        requested_rpm=3100,
        requested_at=NOW + timedelta(seconds=3),
    )
    runtime.manual_delivery_accepted(request, accepted_at=NOW + timedelta(seconds=3))
    runtime.observe(evidence(at=NOW + timedelta(seconds=9), rpm=3200))
    assert runtime.snapshot.override_state is PumpSpeedOverrideState.VERIFIED
    assert runtime.snapshot.effective_rpm == 3200


def test_wrong_pump_regressive_duplicate_and_boundary_transition_are_ignored() -> None:
    runtime = PumpSpeedSessionRuntime(BASELINES)
    runtime.observe(evidence())
    for native_id, at in (
        ("p0198", NOW + timedelta(seconds=1)),
        ("p0102", NOW),
    ):
        runtime.apply_transition(
            PumpSpeedNativeTransition(
                "pool.pump_circuit.configured_speed_rpm",
                native_id,
                2650,
                3200,
                at,
            )
        )
    assert runtime.snapshot.override_state is PumpSpeedOverrideState.NONE


def test_connection_generation_change_clears_and_does_not_reconstruct_override() -> None:
    runtime = PumpSpeedSessionRuntime(BASELINES)
    runtime.observe(evidence(rpm=3200))
    runtime.apply_transition(
        PumpSpeedNativeTransition(
            "pool.pump_circuit.configured_speed_rpm",
            "p0102",
            3200,
            3300,
            NOW + timedelta(seconds=1),
        )
    )
    restored = runtime.observe(
        evidence(
            at=NOW + timedelta(seconds=2),
            rpm=3300,
            generation=2,
        )
    )
    assert restored.override_state is PumpSpeedOverrideState.NONE
    assert restored.effective_rpm == 2650


def test_new_runtime_never_reconstructs_override_from_matching_hardware() -> None:
    first = PumpSpeedSessionRuntime(BASELINES)
    first.observe(evidence())
    verified_manual(first)
    second = PumpSpeedSessionRuntime(BASELINES)
    state = second.observe(evidence(rpm=3200))
    assert state.override_state is PumpSpeedOverrideState.NONE
    assert state.effective_rpm == 2650


def test_unusable_evidence_preserves_but_cannot_change_session() -> None:
    runtime = PumpSpeedSessionRuntime(BASELINES)
    original = runtime.observe(evidence())
    verified_manual(runtime)
    unusable = runtime.observe(
        evidence(
            at=NOW + timedelta(minutes=1),
            purpose=PumpSpeedSessionPurpose.SOLAR,
            rpm=2950,
            usable=False,
        )
    )
    assert unusable.session_id == original.session_id
    assert unusable.evidence_usable is False
    assert unusable.effective_rpm == 3200
    assert unusable.last_session_transition_reason == "session_evidence_unusable_preserved"


def test_older_frame_after_unusable_frame_cannot_change_session() -> None:
    runtime = PumpSpeedSessionRuntime(BASELINES)
    original = runtime.observe(evidence())
    verified_manual(runtime)
    runtime.observe(
        evidence(
            at=NOW + timedelta(minutes=1),
            purpose=PumpSpeedSessionPurpose.SOLAR,
            rpm=2950,
            usable=False,
        )
    )

    regressive = runtime.observe(
        evidence(
            at=NOW + timedelta(seconds=30),
            purpose=PumpSpeedSessionPurpose.SOLAR,
            rpm=2950,
        )
    )

    assert regressive.session_id == original.session_id
    assert regressive.evidence_usable is False
    assert regressive.purpose is PumpSpeedSessionPurpose.ORDINARY
    assert regressive.override_state is PumpSpeedOverrideState.VERIFIED
    assert regressive.effective_rpm == 3200


def test_exact_context_lookup_prevents_cross_body_or_stale_purpose_use() -> None:
    runtime = PumpSpeedSessionRuntime(BASELINES)
    runtime.observe(evidence())
    verified_manual(runtime)
    assert runtime.effective_rpm_for(
        body=PumpSpeedSessionBody.POOL,
        purpose=PumpSpeedSessionPurpose.ORDINARY,
        pump_circuit_id="p0102",
    ) == 3200
    assert runtime.effective_rpm_for(
        body=PumpSpeedSessionBody.HOT_TUB,
        purpose=PumpSpeedSessionPurpose.ORDINARY,
        pump_circuit_id="p0102",
    ) is None
    assert runtime.effective_rpm_for(
        body=PumpSpeedSessionBody.POOL,
        purpose=PumpSpeedSessionPurpose.SOLAR,
        pump_circuit_id="p0102",
    ) is None


def test_diagnostics_are_bounded_non_authorizing_and_contain_no_history() -> None:
    runtime = PumpSpeedSessionRuntime(BASELINES)
    runtime.observe(evidence())
    diagnostics = runtime.diagnostics()
    assert diagnostics["authority"] == "none"
    assert diagnostics["command_delivery_enabled"] is False
    assert diagnostics["persistent_override_storage_enabled"] is False
    assert "history" not in diagnostics

def test_outcome_unknown_late_correlated_speed_verifies_replacement() -> None:
    runtime = PumpSpeedSessionRuntime(BASELINES, pending_ttl=timedelta(seconds=5))
    runtime.observe(evidence())
    verified_manual(runtime, 3200)

    request = runtime.begin_manual_request(
        body=PumpSpeedSessionBody.POOL,
        pump_circuit_id="p0102",
        requested_rpm=3100,
        requested_at=NOW + timedelta(seconds=5),
        request_id="outcome-unknown",
    )
    runtime.manual_delivery_outcome_unknown(
        request,
        outcome_unknown_at=NOW + timedelta(seconds=6),
    )

    assert runtime.snapshot.override_state is PumpSpeedOverrideState.PENDING
    assert runtime.snapshot.effective_rpm == 3100

    runtime.apply_transition(
        PumpSpeedNativeTransition(
            "pool.pump_circuit.configured_speed_rpm",
            "p0102",
            3200,
            3100,
            NOW + timedelta(seconds=7),
            correlated_request_id=request.request_id,
        )
    )

    assert runtime.snapshot.override_state is PumpSpeedOverrideState.VERIFIED
    assert runtime.snapshot.override_source is PumpSpeedOverrideSource.POOLOS_MANUAL
    assert runtime.snapshot.effective_rpm == 3100


def test_correlation_before_outcome_unknown_verifies_when_uncertainty_recorded() -> None:
    runtime = PumpSpeedSessionRuntime(BASELINES)
    runtime.observe(evidence())

    request = runtime.begin_manual_request(
        body=PumpSpeedSessionBody.POOL,
        pump_circuit_id="p0102",
        requested_rpm=3200,
        requested_at=NOW + timedelta(seconds=1),
        request_id="callback-before-error",
    )

    runtime.apply_transition(
        PumpSpeedNativeTransition(
            "pool.pump_circuit.configured_speed_rpm",
            "p0102",
            2650,
            3200,
            NOW + timedelta(seconds=2),
            correlated_request_id=request.request_id,
        )
    )
    assert runtime.snapshot.override_state is PumpSpeedOverrideState.PENDING

    runtime.manual_delivery_outcome_unknown(
        request,
        outcome_unknown_at=NOW + timedelta(seconds=3),
    )

    assert runtime.snapshot.override_state is PumpSpeedOverrideState.VERIFIED
    assert runtime.snapshot.override_source is PumpSpeedOverrideSource.POOLOS_MANUAL
    assert runtime.snapshot.effective_rpm == 3200


def test_outcome_unknown_without_native_confirmation_expires_to_prior_verified() -> None:
    runtime = PumpSpeedSessionRuntime(BASELINES, pending_ttl=timedelta(seconds=5))
    runtime.observe(evidence())
    verified_manual(runtime, 3200)

    request = runtime.begin_manual_request(
        body=PumpSpeedSessionBody.POOL,
        pump_circuit_id="p0102",
        requested_rpm=3100,
        requested_at=NOW + timedelta(seconds=5),
        request_id="outcome-unknown-expiry",
    )
    runtime.manual_delivery_outcome_unknown(
        request,
        outcome_unknown_at=NOW + timedelta(seconds=6),
    )

    runtime.observe(
        evidence(
            at=NOW + timedelta(seconds=11),
            rpm=3200,
        )
    )

    assert runtime.snapshot.override_state is PumpSpeedOverrideState.VERIFIED
    assert runtime.snapshot.effective_rpm == 3200
