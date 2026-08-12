from __future__ import annotations

from datetime import UTC, datetime

import pytest

from poolos.intellicenter_readonly import (
    NativeIntelliCenterObservationSnapshot,
    NativeIntelliCenterStatus,
)
from poolos.native_observation_provider import (
    NativeIntelliCenterObservationProvider,
    NativeObservationCandidateComposition,
    compose_native_observation_candidate,
)
from poolos.observation_source_selection import (
    ObservationSource,
    ObservationSourceSelection,
    ObservationSourceSelectionReason,
    select_production_observation_source,
)


NOW = datetime(2026, 8, 12, 13, 30, tzinfo=UTC)


def _snapshot(
    *,
    status: NativeIntelliCenterStatus,
    failure_reason_code: str | None = None,
) -> NativeIntelliCenterObservationSnapshot:
    return NativeIntelliCenterObservationSnapshot(
        generated_at=NOW,
        status=status,
        source_id=("native:test" if status is NativeIntelliCenterStatus.AVAILABLE else None),
        observations=(),
        missing_concepts=("pump.rpm",),
        failure_reason_code=failure_reason_code,
    )


def test_provider_has_fixed_native_source_identity() -> None:
    provider = NativeIntelliCenterObservationProvider(
        _snapshot(status=NativeIntelliCenterStatus.AVAILABLE)
    )

    assert provider.source is ObservationSource.NATIVE_INTELLICENTER


def test_available_native_snapshot_is_preserved_as_payload() -> None:
    snapshot = _snapshot(status=NativeIntelliCenterStatus.AVAILABLE)

    read = NativeIntelliCenterObservationProvider(snapshot).read()

    assert read.source is ObservationSource.NATIVE_INTELLICENTER
    assert read.generated_at == NOW
    assert read.available is True
    assert read.payload is snapshot
    assert read.failure_reason_code is None


def test_initializing_native_snapshot_is_unavailable_candidate_read() -> None:
    read = NativeIntelliCenterObservationProvider(
        _snapshot(status=NativeIntelliCenterStatus.INITIALIZING)
    ).read()

    assert read.available is False
    assert read.payload is None
    assert read.failure_reason_code == "NATIVE_SOURCE_INITIALIZING"


def test_unavailable_native_snapshot_preserves_failure_reason() -> None:
    read = NativeIntelliCenterObservationProvider(
        _snapshot(
            status=NativeIntelliCenterStatus.UNAVAILABLE,
            failure_reason_code="transport_unavailable",
        )
    ).read()

    assert read.available is False
    assert read.payload is None
    assert read.failure_reason_code == "TRANSPORT_UNAVAILABLE"


def test_unavailable_native_snapshot_without_reason_gets_stable_reason() -> None:
    read = NativeIntelliCenterObservationProvider(
        _snapshot(status=NativeIntelliCenterStatus.UNAVAILABLE)
    ).read()

    assert read.failure_reason_code == "NATIVE_SOURCE_UNAVAILABLE"


def test_available_native_snapshot_composes_as_non_authoritative_candidate() -> None:
    snapshot = _snapshot(status=NativeIntelliCenterStatus.AVAILABLE)

    composition = compose_native_observation_candidate(snapshot)

    assert composition.snapshot is snapshot
    assert composition.selection.selected is True
    assert composition.selection.effective_source is ObservationSource.NATIVE_INTELLICENTER
    assert composition.selection.authoritative_observation_source is False
    assert composition.selection.reason is ObservationSourceSelectionReason.NATIVE_CANDIDATE_SELECTED
    assert composition.selection.command_authority == "none"
    assert composition.selection.command_delivery_enabled is False
    assert composition.selection.physical_delivery_enabled is False


def test_initializing_native_snapshot_is_not_selected_as_candidate() -> None:
    composition = compose_native_observation_candidate(
        _snapshot(status=NativeIntelliCenterStatus.INITIALIZING)
    )

    assert composition.snapshot is None
    assert composition.selection.selected is False
    assert composition.selection.effective_source is None
    assert (
        composition.selection.reason
        is ObservationSourceSelectionReason.REQUESTED_SOURCE_UNAVAILABLE
    )


def test_unavailable_native_snapshot_is_not_selected_as_candidate() -> None:
    composition = compose_native_observation_candidate(
        _snapshot(
            status=NativeIntelliCenterStatus.UNAVAILABLE,
            failure_reason_code="source_disconnected",
        )
    )

    assert composition.snapshot is None
    assert composition.read.failure_reason_code == "SOURCE_DISCONNECTED"
    assert composition.selection.selected is False
    assert composition.selection.authoritative_observation_source is False


def test_composition_diagnostics_remain_explicitly_non_authoritative() -> None:
    diagnostics = dict(
        compose_native_observation_candidate(
            _snapshot(status=NativeIntelliCenterStatus.AVAILABLE)
        ).diagnostics()
    )

    assert diagnostics == {
        "source": "native_intellicenter",
        "available": True,
        "generated_at": NOW.isoformat(),
        "failure_reason_code": None,
        "candidate_selected": True,
        "effective_source": "native_intellicenter",
        "authoritative_observation_source": False,
        "observation_count": 0,
        "missing_concept_count": 1,
        "production_native_selection_enabled": False,
        "command_authority": "none",
        "command_delivery_enabled": False,
        "physical_delivery_enabled": False,
    }


def test_production_native_selection_remains_blocked_after_provider_composition() -> None:
    composition = compose_native_observation_candidate(
        _snapshot(status=NativeIntelliCenterStatus.AVAILABLE)
    )

    production = select_production_observation_source(
        requested_source=ObservationSource.NATIVE_INTELLICENTER,
        home_assistant_available=False,
        native_intellicenter_available=composition.read.available,
    )

    assert production.selected is False
    assert production.effective_source is None
    assert production.authoritative_observation_source is False
    assert production.reason is ObservationSourceSelectionReason.NO_AUTHORIZED_SOURCE_AVAILABLE


def test_production_native_request_still_falls_back_to_ha_when_ha_available() -> None:
    composition = compose_native_observation_candidate(
        _snapshot(status=NativeIntelliCenterStatus.AVAILABLE)
    )

    production = select_production_observation_source(
        requested_source=ObservationSource.NATIVE_INTELLICENTER,
        home_assistant_available=True,
        native_intellicenter_available=composition.read.available,
    )

    assert production.effective_source is ObservationSource.HOME_ASSISTANT
    assert production.authoritative_observation_source is True
    assert production.fallback_used is True
    assert (
        production.reason
        is ObservationSourceSelectionReason.NATIVE_PRODUCTION_SELECTION_DISABLED
    )


def test_composition_rejects_authoritative_native_selection() -> None:
    read = NativeIntelliCenterObservationProvider(
        _snapshot(status=NativeIntelliCenterStatus.AVAILABLE)
    ).read()
    with pytest.raises(ValueError, match="authoritative observations must remain Home Assistant"):
        selection = ObservationSourceSelection(
            requested_source=ObservationSource.NATIVE_INTELLICENTER,
            effective_source=ObservationSource.NATIVE_INTELLICENTER,
            selected=True,
            authoritative_observation_source=True,
            fallback_used=False,
            reason=ObservationSourceSelectionReason.NATIVE_CANDIDATE_SELECTED,
        )
        NativeObservationCandidateComposition(read=read, selection=selection)
