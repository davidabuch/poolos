from __future__ import annotations

from datetime import UTC, datetime

import pytest

from poolos.spa_temperature_policy import (
    SpaTemperatureDisposition,
    SpaTemperatureEvidence,
    current_spa_temperature_evidence,
)


NOW = datetime(2026, 9, 8, 18, 0, tzinfo=UTC)


def test_fresh_inactive_spa_temperature_is_not_bulk_water_truth() -> None:
    result = current_spa_temperature_evidence(
        evaluated_at=NOW,
        spa_active=False,
        pool_active=False,
        pump_rpm=0,
        observed_temperature_f=90.0,
        temperature_observed_at=NOW,
        observation_usable=True,
    )

    assert result.disposition is SpaTemperatureDisposition.INACTIVE_BODY_UNTRUSTED
    assert result.trusted_temperature_f is None


def test_active_exclusively_routed_spa_temperature_is_trusted() -> None:
    result = current_spa_temperature_evidence(
        evaluated_at=NOW,
        spa_active=True,
        pool_active=False,
        pump_rpm=2600,
        observed_temperature_f=90.0,
        temperature_observed_at=NOW,
        observation_usable=True,
    )

    assert result.disposition is SpaTemperatureDisposition.TRUSTED
    assert result.trusted_temperature_f == 90.0


@pytest.mark.parametrize(
    ("pool_active", "pump_rpm"),
    ((True, 2600), (None, 2600), (False, 0)),
)
def test_spa_temperature_fails_closed_without_exclusive_circulation(
    pool_active: bool | None,
    pump_rpm: int,
) -> None:
    result = current_spa_temperature_evidence(
        evaluated_at=NOW,
        spa_active=True,
        pool_active=pool_active,
        pump_rpm=pump_rpm,
        observed_temperature_f=90.0,
        temperature_observed_at=NOW,
        observation_usable=True,
    )

    assert result.disposition is SpaTemperatureDisposition.INACTIVE_BODY_UNTRUSTED


def test_trusted_evidence_requires_positive_typed_value_and_timestamp() -> None:
    with pytest.raises(ValueError, match="requires value and timestamp"):
        SpaTemperatureEvidence(
            evaluated_at=NOW,
            disposition=SpaTemperatureDisposition.TRUSTED,
        )
    with pytest.raises(ValueError, match="must be finite"):
        SpaTemperatureEvidence(
            evaluated_at=NOW,
            disposition=SpaTemperatureDisposition.TRUSTED,
            trusted_temperature_f=float("nan"),
            trusted_at=NOW,
        )
