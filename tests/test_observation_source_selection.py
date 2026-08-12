from __future__ import annotations

from datetime import UTC, datetime

import pytest

from poolos.observation_source_selection import (
    ObservationSource,
    ObservationSourceRead,
    ObservationSourceSelection,
    ObservationSourceSelectionReason,
    select_non_authoritative_candidate_source,
    select_production_observation_source,
)


def test_production_home_assistant_is_authoritative_when_available() -> None:
    result = select_production_observation_source(
        requested_source=ObservationSource.HOME_ASSISTANT,
        home_assistant_available=True,
        native_intellicenter_available=True,
    )

    assert result.effective_source is ObservationSource.HOME_ASSISTANT
    assert result.authoritative_observation_source is True
    assert result.fallback_used is False
    assert result.reason is ObservationSourceSelectionReason.HOME_ASSISTANT_SELECTED
    assert result.command_authority == "none"
    assert result.command_delivery_enabled is False
    assert result.physical_delivery_enabled is False


def test_production_native_request_falls_back_to_home_assistant() -> None:
    result = select_production_observation_source(
        requested_source=ObservationSource.NATIVE_INTELLICENTER,
        home_assistant_available=True,
        native_intellicenter_available=True,
    )

    assert result.effective_source is ObservationSource.HOME_ASSISTANT
    assert result.authoritative_observation_source is True
    assert result.fallback_used is True
    assert result.reason is ObservationSourceSelectionReason.NATIVE_PRODUCTION_SELECTION_DISABLED
    assert result.production_native_selection_enabled is False


def test_native_health_cannot_elevate_production_authority_without_ha() -> None:
    result = select_production_observation_source(
        requested_source=ObservationSource.NATIVE_INTELLICENTER,
        home_assistant_available=False,
        native_intellicenter_available=True,
    )

    assert result.selected is False
    assert result.effective_source is None
    assert result.authoritative_observation_source is False
    assert result.reason is ObservationSourceSelectionReason.NO_AUTHORIZED_SOURCE_AVAILABLE


def test_production_ha_request_fails_closed_when_ha_unavailable() -> None:
    result = select_production_observation_source(
        requested_source=ObservationSource.HOME_ASSISTANT,
        home_assistant_available=False,
        native_intellicenter_available=True,
    )

    assert result.selected is False
    assert result.effective_source is None
    assert result.reason is ObservationSourceSelectionReason.HOME_ASSISTANT_UNAVAILABLE


def test_native_can_be_selected_only_as_non_authoritative_candidate() -> None:
    result = select_non_authoritative_candidate_source(
        requested_source=ObservationSource.NATIVE_INTELLICENTER,
        available_sources={ObservationSource.NATIVE_INTELLICENTER: True},
    )

    assert result.selected is True
    assert result.effective_source is ObservationSource.NATIVE_INTELLICENTER
    assert result.authoritative_observation_source is False
    assert result.reason is ObservationSourceSelectionReason.NATIVE_CANDIDATE_SELECTED
    assert result.command_authority == "none"


def test_unavailable_candidate_is_not_selected() -> None:
    result = select_non_authoritative_candidate_source(
        requested_source=ObservationSource.NATIVE_INTELLICENTER,
        available_sources={ObservationSource.NATIVE_INTELLICENTER: False},
    )

    assert result.selected is False
    assert result.effective_source is None
    assert result.reason is ObservationSourceSelectionReason.REQUESTED_SOURCE_UNAVAILABLE


def test_source_read_requires_timezone_aware_timestamp() -> None:
    with pytest.raises(ValueError, match="timezone-aware"):
        ObservationSourceRead(
            source=ObservationSource.HOME_ASSISTANT,
            generated_at=datetime(2026, 8, 12, 12, 0),
            available=True,
            payload=object(),
        )


def test_available_source_read_requires_payload() -> None:
    with pytest.raises(ValueError, match="must contain a payload"):
        ObservationSourceRead[object](
            source=ObservationSource.HOME_ASSISTANT,
            generated_at=datetime(2026, 8, 12, 12, 0, tzinfo=UTC),
            available=True,
            payload=None,
        )


def test_unavailable_source_read_rejects_payload() -> None:
    with pytest.raises(ValueError, match="must not contain a payload"):
        ObservationSourceRead(
            source=ObservationSource.NATIVE_INTELLICENTER,
            generated_at=datetime(2026, 8, 12, 12, 0, tzinfo=UTC),
            available=False,
            payload=object(),
            failure_reason_code="offline",
        )


def test_source_read_normalizes_failure_reason() -> None:
    read = ObservationSourceRead[object](
        source=ObservationSource.NATIVE_INTELLICENTER,
        generated_at=datetime(2026, 8, 12, 12, 0, tzinfo=UTC),
        available=False,
        payload=None,
        failure_reason_code="transport_unavailable",
    )

    assert read.failure_reason_code == "TRANSPORT_UNAVAILABLE"


def test_selection_diagnostics_are_explicit_about_safety() -> None:
    result = select_production_observation_source(
        requested_source=ObservationSource.NATIVE_INTELLICENTER,
        home_assistant_available=True,
        native_intellicenter_available=True,
    )

    diagnostics = dict(result.diagnostics())
    assert diagnostics == {
        "requested_source": "native_intellicenter",
        "effective_source": "home_assistant",
        "selected": True,
        "authoritative_observation_source": True,
        "fallback_used": True,
        "reason": "NATIVE_PRODUCTION_SELECTION_DISABLED",
        "production_native_selection_enabled": False,
        "command_authority": "none",
        "command_delivery_enabled": False,
        "physical_delivery_enabled": False,
    }


def test_selection_model_rejects_native_authoritative_source() -> None:
    with pytest.raises(ValueError, match="authoritative observations must remain Home Assistant"):
        ObservationSourceSelection(
            requested_source=ObservationSource.NATIVE_INTELLICENTER,
            effective_source=ObservationSource.NATIVE_INTELLICENTER,
            selected=True,
            authoritative_observation_source=True,
            fallback_used=False,
            reason=ObservationSourceSelectionReason.NATIVE_CANDIDATE_SELECTED,
        )
