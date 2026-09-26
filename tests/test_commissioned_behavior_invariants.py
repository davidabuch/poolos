"""Permanent regressions for owner-accepted physically commissioned behavior.

These tests intentionally assert user-visible contract behavior rather than a
particular ownership-lease shape. Internal BODY/PUMP/THERMAL refactors may
change provenance representation, but they may not silently change these
accepted outcomes.
"""

from poolos.spa_thermal_policy import (
    SpaSessionKind,
    spa_manual_off_requires_autonomy_suppression,
)


def test_own_049a_user_hot_tub_off_preserves_future_autonomy_after_body_adoption_retires() -> None:
    """OWN-049A: user Spa OFF ends this session, not future Spa autonomy."""

    # Original v0.11.64-v0.11.66 proof shape: BODY adoption still present.
    assert not spa_manual_off_requires_autonomy_suppression(
        ownership_session_kind=SpaSessionKind.EXTERNAL_USER,
        assessed_session_kind=None,
        assessed_spa_active=True,
    )

    # Sep 26 v0.11.70 regression shape: BODY adoption already retired while
    # the same authoritative Spa epoch still identifies an active user session.
    assert not spa_manual_off_requires_autonomy_suppression(
        ownership_session_kind=None,
        assessed_session_kind=SpaSessionKind.EXTERNAL_USER,
        assessed_spa_active=True,
    )


def test_own_049a_stale_or_opportunistic_evidence_does_not_bypass_restraint() -> None:
    """OWN-049A negative controls preserve same-opportunity suppression."""

    # Stale external-user classification after Spa is already inactive cannot
    # exempt a later command from the opportunistic restraint.
    assert spa_manual_off_requires_autonomy_suppression(
        ownership_session_kind=None,
        assessed_session_kind=SpaSessionKind.EXTERNAL_USER,
        assessed_spa_active=False,
    )

    # A PoolOS-started opportunistic Spa remains suppressible so explicit user
    # OFF cannot immediately recreate the same opportunity.
    assert spa_manual_off_requires_autonomy_suppression(
        ownership_session_kind=SpaSessionKind.POOLOS_OPPORTUNISTIC,
        assessed_session_kind=SpaSessionKind.POOLOS_OPPORTUNISTIC,
        assessed_spa_active=True,
    )
