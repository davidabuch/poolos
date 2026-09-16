"""A restraint cancels an opportunity, never grants equipment ownership."""

from datetime import UTC, datetime, timedelta

from poolos.pool_automatic_control_suppression import (
    PoolAutomaticControlSuppression,
    PoolAutomaticControlSuppressionSource as Source,
)

NOW = datetime(2026, 9, 16, 19, tzinfo=UTC)


def test_manual_off_cancels_current_thermal_but_not_later_filtration_window() -> None:
    restraint = PoolAutomaticControlSuppression()
    thermal = restraint.observe_opportunity("thermal", eligible=True, observed_at=NOW)
    restraint.observe_opportunity("filtration", eligible=False, observed_at=NOW)
    restraint.suppress(source=Source.MANUAL_POOLOS_OFF_REQUEST,
                      suppressed_at=NOW, reason="manual_pool_off")
    for second in range(1, 10):
        assert restraint.observe_opportunity(
            "thermal", eligible=True, observed_at=NOW + timedelta(seconds=second)
        ) == thermal
        assert restraint.blocks_opportunity("thermal")
    restraint.observe_opportunity("filtration", eligible=True,
                                  observed_at=NOW + timedelta(hours=10))
    assert not restraint.blocks_opportunity("filtration")
    assert restraint.blocks_opportunity("thermal")
    assert restraint.state.suppressed


def test_unknown_or_regressive_evidence_cannot_create_handback() -> None:
    restraint = PoolAutomaticControlSuppression()
    original = restraint.observe_opportunity("filtration", eligible=True, observed_at=NOW)
    restraint.suppress(source=Source.MANUAL_POOLOS_OFF_REQUEST,
                      suppressed_at=NOW, reason="manual_pool_off")
    restraint.observe_opportunity("filtration", eligible=None,
                                  observed_at=NOW + timedelta(seconds=1))
    restraint.observe_opportunity("filtration", eligible=False,
                                  observed_at=NOW - timedelta(seconds=1))
    assert restraint.observe_opportunity(
        "filtration", eligible=True, observed_at=NOW + timedelta(seconds=2)
    ) == original
    assert restraint.blocks_opportunity("filtration")
    restraint.observe_opportunity("filtration", eligible=False,
                                  observed_at=NOW + timedelta(seconds=3))
    successor = restraint.observe_opportunity("filtration", eligible=True,
                                              observed_at=NOW + timedelta(seconds=4))
    assert successor != original
    assert not restraint.blocks_opportunity("filtration")


def test_persistent_operator_restraint_survives_new_opportunity() -> None:
    restraint = PoolAutomaticControlSuppression()
    restraint.observe_opportunity("filtration", eligible=False, observed_at=NOW)
    restraint.suppress(source=Source.OPERATOR_RESTRAINT,
                      suppressed_at=NOW, reason="operator_disabled")
    restraint.observe_opportunity("filtration", eligible=True,
                                  observed_at=NOW + timedelta(hours=10))
    assert restraint.blocks_opportunity("filtration")


def test_restored_transient_restraint_requires_observed_boundary() -> None:
    previous = PoolAutomaticControlSuppression()
    previous.suppress(source=Source.MANUAL_POOLOS_OFF_REQUEST,
                      suppressed_at=NOW, reason="manual_pool_off")
    restored = PoolAutomaticControlSuppression(state=previous.state)
    restored.observe_opportunity("filtration", eligible=True,
                                  observed_at=NOW + timedelta(seconds=1))
    assert restored.blocks_opportunity("filtration")
    restored.observe_opportunity("filtration", eligible=False,
                                  observed_at=NOW + timedelta(seconds=2))
    restored.observe_opportunity("filtration", eligible=True,
                                  observed_at=NOW + timedelta(seconds=3))
    assert not restored.blocks_opportunity("filtration")


def test_pre_cancellation_evidence_cannot_expire_a_newer_cancellation() -> None:
    restraint = PoolAutomaticControlSuppression()
    restraint.suppress(source=Source.MANUAL_POOLOS_OFF_REQUEST,
                      suppressed_at=NOW, reason="manual_pool_off")
    restraint.observe_opportunity("filtration", eligible=False,
                                  observed_at=NOW - timedelta(seconds=1))
    restraint.observe_opportunity("filtration", eligible=True,
                                  observed_at=NOW + timedelta(seconds=1))
    assert restraint.blocks_opportunity("filtration")
