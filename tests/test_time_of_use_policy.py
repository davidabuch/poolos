from datetime import datetime
from zoneinfo import ZoneInfo

import pytest

from poolos.time_of_use_policy import (
    LADWP_INITIAL_PROFILE,
    TimeOfUsePeriod,
    TimeOfUseProfile,
    TimeOfUseTier,
)


LOCAL = ZoneInfo("America/Los_Angeles")


@pytest.mark.parametrize(
    ("when", "tier"),
    (
        (datetime(2026, 8, 26, 14, 0, tzinfo=LOCAL), TimeOfUseTier.HIGH_PEAK),
        (datetime(2026, 8, 26, 11, 0, tzinfo=LOCAL), TimeOfUseTier.LOW_PEAK),
        (datetime(2026, 8, 26, 18, 0, tzinfo=LOCAL), TimeOfUseTier.LOW_PEAK),
        (datetime(2026, 8, 26, 21, 0, tzinfo=LOCAL), TimeOfUseTier.BASE),
        (datetime(2026, 8, 29, 14, 0, tzinfo=LOCAL), TimeOfUseTier.BASE),
        (datetime(2026, 8, 30, 14, 0, tzinfo=LOCAL), TimeOfUseTier.BASE),
    ),
)
def test_ladwp_profile_classifies_supplied_schedule(
    when: datetime,
    tier: TimeOfUseTier,
) -> None:
    assert LADWP_INITIAL_PROFILE.classify(when) is tier


def test_high_peak_next_suitable_boundary_is_low_peak() -> None:
    at = datetime(2026, 8, 26, 14, 0, tzinfo=LOCAL)

    assert LADWP_INITIAL_PROFILE.next_at_or_below(
        at,
        maximum_tier=TimeOfUseTier.LOW_PEAK,
    ) == datetime(2026, 8, 26, 17, 0, tzinfo=LOCAL)


def test_profile_is_generic_versionable_tariff_data() -> None:
    profile = TimeOfUseProfile(
        name="future-season",
        timezone_name="America/Los_Angeles",
        periods=(
            TimeOfUsePeriod(frozenset({0}), 60, 120, TimeOfUseTier.HIGH_PEAK),
        ),
    )

    assert profile.name == "future-season"


def test_naive_time_fails_closed() -> None:
    with pytest.raises(ValueError, match="timezone-aware"):
        LADWP_INITIAL_PROFILE.classify(datetime(2026, 8, 26, 14, 0))
