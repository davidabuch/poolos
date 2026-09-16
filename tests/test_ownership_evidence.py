"""Fixed episodes and operator evidence never grant historical origin."""

from dataclasses import replace
from datetime import UTC, datetime, timedelta

import pytest

from poolos.ownership_evidence import (
    DomainOwnershipState,
    OwnershipAuthority,
    OwnershipDomain,
    OwnershipEvidenceKind,
    OwnershipHealth,
    PositiveOperatorEvidence,
)

NOW = datetime(2026, 9, 16, tzinfo=UTC)


def observe(state: DomainOwnershipState, *, seconds: int = 0,
            matches: bool = False, operator: PositiveOperatorEvidence | None = None,
            expected: bool = False) -> DomainOwnershipState:
    at = NOW + timedelta(seconds=seconds)
    return state.observe(
        at=at, observed_at=at, usable=True, matches=matches,
        expected_transition=expected, generation=1, session_id="body-session",
        equipment_id="pump", policy_identity="solar", origin_id="accepted-rpm",
        intended_value=2900, operator=operator,
    )


def owned() -> DomainOwnershipState:
    return DomainOwnershipState(OwnershipDomain.PUMP, OwnershipAuthority.POOLOS)


def operator_evidence() -> PositiveOperatorEvidence:
    return PositiveOperatorEvidence("manual-request", 1, "body-session",
                                    OwnershipDomain.PUMP, "pump", NOW)


def test_unowned_matching_state_cannot_create_authority() -> None:
    initial = DomainOwnershipState(OwnershipDomain.PUMP)
    observed = observe(initial, matches=True)
    assert observed.authority is OwnershipAuthority.NONE
    assert observed.episode is None
    assert observed.command_blocker == initial.command_blocker


def test_unexplained_drift_retains_authority_with_fixed_episode() -> None:
    first = observe(owned())
    assert first.authority is OwnershipAuthority.POOLOS
    assert first.evidence_kind is OwnershipEvidenceKind.UNEXPLAINED_DRIFT
    assert first.health is OwnershipHealth.RECONCILING
    assert first.episode is not None
    for second in range(120):
        refreshed = observe(first, seconds=second)
        assert refreshed.episode == first.episode
    expired = observe(first, seconds=120)
    assert expired.health is OwnershipHealth.FAULTED
    assert expired.authority is OwnershipAuthority.POOLOS
    assert expired.evidence_kind is OwnershipEvidenceKind.COMMAND_OR_CONTROL_FAILURE
    late = observe(expired, seconds=121, matches=True)
    assert late.health is OwnershipHealth.FAULTED
    assert late.episode == expired.episode
    assert late.authority is OwnershipAuthority.POOLOS


def test_convergence_match_does_not_reacquire_yielded_authority() -> None:
    state = observe(owned(), expected=True, operator=operator_evidence())
    assert state.authority is OwnershipAuthority.OPERATOR
    assert state.evidence_kind is OwnershipEvidenceKind.POSITIVE_OPERATOR_INTERVENTION
    late = observe(state, seconds=1, matches=True)
    assert late.authority is OwnershipAuthority.OPERATOR
    assert late.positive_operator_evidence == state.positive_operator_evidence
    assert late.command_blocker == state.command_blocker


@pytest.mark.parametrize("field,value", [
    ("authority_generation", 2), ("body_session_id", "old-body"),
    ("domain", OwnershipDomain.THERMAL), ("equipment_id", "other-pump"),
    ("requested_at", NOW + timedelta(seconds=1)),
])
def test_unrelated_or_future_operator_record_cannot_steal_authority(field: str, value: object) -> None:
    evidence = replace(operator_evidence(), **{field: value})
    state = observe(owned(), operator=evidence)
    assert state.authority is OwnershipAuthority.POOLOS


def test_correction_reservation_is_finite_and_idempotent() -> None:
    state = observe(owned())
    assert state.episode is not None
    episode = state.episode.reserve_correction("first", at=NOW)
    assert episode.reserve_correction("first", at=NOW) == episode
    episode = episode.reserve_correction("second", at=NOW + timedelta(seconds=1))
    with pytest.raises(ValueError, match="not permitted"):
        episode.reserve_correction("third", at=NOW + timedelta(seconds=2))
    assert episode.deadline == state.episode.deadline


def test_verified_episode_remains_stable_after_original_deadline() -> None:
    state = observe(observe(owned(), expected=True), seconds=2, matches=True)
    assert state.health is OwnershipHealth.STABLE
    assert observe(state, seconds=121, matches=True).health is OwnershipHealth.STABLE


def test_same_timestamp_matching_evidence_cannot_close_episode() -> None:
    state = observe(observe(owned()), matches=True)
    assert state.health is OwnershipHealth.RECONCILING
    assert state.episode is not None and state.episode.verified_at is None


@pytest.mark.parametrize("offset", [None, 1])
def test_missing_or_future_observation_cannot_verify_convergence(offset: int | None) -> None:
    state = observe(owned())
    at = NOW + timedelta(seconds=2)
    result = state.observe(
        at=at, observed_at=None if offset is None else at + timedelta(seconds=offset),
        usable=True, matches=True, expected_transition=True,
        generation=1, session_id="body-session", equipment_id="pump",
        policy_identity="solar", origin_id="accepted-rpm", intended_value=2900,
    )
    assert result.health is not OwnershipHealth.STABLE
    assert result.episode is not None and result.episode.verified_at is None
    assert result.command_blocker == "ownership_evidence_unusable"
    assert result.episode.deadline == state.episode.deadline


def test_regressive_observation_cannot_open_new_drift_episode() -> None:
    stable = observe(owned(), seconds=10, matches=True)
    result = stable.observe(
        at=NOW + timedelta(seconds=11), observed_at=NOW,
        usable=True, matches=False, expected_transition=False,
        generation=1, session_id="body-session", equipment_id="pump",
        policy_identity="solar", origin_id="accepted-rpm", intended_value=2900,
    )
    assert result.authority is OwnershipAuthority.POOLOS
    assert result.episode is None
    assert result.observed_at == stable.observed_at
    assert result.evidence_kind is OwnershipEvidenceKind.STALE_OR_OLD_GENERATION_CONSEQUENCE
    assert result.command_blocker == "ownership_evidence_unusable"
