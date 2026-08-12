"""Non-authoritative native IntelliCenter observation-provider composition.

Milestone 12.0C5 adapts the existing immutable native IntelliCenter observation
snapshot into the generic observation-source boundary introduced by 12.0C4.
It deliberately does not integrate with the Home Assistant coordinator and does
not grant native observations production authority.
"""

from __future__ import annotations

from dataclasses import dataclass
from types import MappingProxyType
from typing import Any, Mapping

from .intellicenter_readonly import (
    NativeIntelliCenterObservationSnapshot,
    NativeIntelliCenterStatus,
)
from .observation_source_selection import (
    ObservationSource,
    ObservationSourceRead,
    ObservationSourceSelection,
    select_non_authoritative_candidate_source,
)


_NATIVE_INITIALIZING_REASON = "NATIVE_SOURCE_INITIALIZING"
_NATIVE_UNAVAILABLE_REASON = "NATIVE_SOURCE_UNAVAILABLE"


@dataclass(frozen=True, slots=True)
class NativeIntelliCenterObservationProvider:
    """Expose one immutable native snapshot through the C4 provider contract."""

    snapshot: NativeIntelliCenterObservationSnapshot

    @property
    def source(self) -> ObservationSource:
        """Return the provider's fixed source identity."""

        return ObservationSource.NATIVE_INTELLICENTER

    def read(
        self,
    ) -> ObservationSourceRead[NativeIntelliCenterObservationSnapshot]:
        """Return the native snapshot as candidate evidence without authority."""

        snapshot = self.snapshot
        if snapshot.available:
            return ObservationSourceRead(
                source=self.source,
                generated_at=snapshot.generated_at,
                available=True,
                payload=snapshot,
            )

        failure_reason = snapshot.failure_reason_code
        if failure_reason is None:
            failure_reason = (
                _NATIVE_INITIALIZING_REASON
                if snapshot.status is NativeIntelliCenterStatus.INITIALIZING
                else _NATIVE_UNAVAILABLE_REASON
            )
        return ObservationSourceRead(
            source=self.source,
            generated_at=snapshot.generated_at,
            available=False,
            payload=None,
            failure_reason_code=failure_reason,
        )


@dataclass(frozen=True, slots=True)
class NativeObservationCandidateComposition:
    """Immutable evidence for one non-authoritative native candidate composition."""

    read: ObservationSourceRead[NativeIntelliCenterObservationSnapshot]
    selection: ObservationSourceSelection

    def __post_init__(self) -> None:
        if self.read.source is not ObservationSource.NATIVE_INTELLICENTER:
            raise ValueError("native composition requires native IntelliCenter source read")
        if self.selection.requested_source is not ObservationSource.NATIVE_INTELLICENTER:
            raise ValueError("native composition requires native IntelliCenter selection")
        if self.selection.authoritative_observation_source:
            raise ValueError("native candidate composition must remain non-authoritative")
        if self.selection.command_authority != "none":
            raise ValueError("native candidate composition must not grant command authority")
        if self.selection.command_delivery_enabled or self.selection.physical_delivery_enabled:
            raise ValueError("native candidate composition must not enable delivery")
        if self.selection.selected != self.read.available:
            raise ValueError("native candidate selection must match provider availability")
        if self.selection.selected:
            if self.selection.effective_source is not ObservationSource.NATIVE_INTELLICENTER:
                raise ValueError("selected native candidate must retain native source identity")
            if self.read.payload is None:
                raise ValueError("selected native candidate must retain its snapshot payload")
        elif self.selection.effective_source is not None:
            raise ValueError("unselected native candidate must not expose an effective source")

    @property
    def snapshot(self) -> NativeIntelliCenterObservationSnapshot | None:
        """Return the original immutable native snapshot when candidate is usable."""

        return self.read.payload

    def diagnostics(self) -> Mapping[str, Any]:
        """Return bounded diagnostics explicit about the non-authoritative boundary."""

        snapshot = self.read.payload
        return MappingProxyType(
            {
                "source": self.read.source.value,
                "available": self.read.available,
                "generated_at": self.read.generated_at.isoformat(),
                "failure_reason_code": self.read.failure_reason_code,
                "candidate_selected": self.selection.selected,
                "effective_source": (
                    None
                    if self.selection.effective_source is None
                    else self.selection.effective_source.value
                ),
                "authoritative_observation_source": False,
                "observation_count": 0 if snapshot is None else len(snapshot.observations),
                "missing_concept_count": (
                    0 if snapshot is None else len(snapshot.missing_concepts)
                ),
                "production_native_selection_enabled": False,
                "command_authority": "none",
                "command_delivery_enabled": False,
                "physical_delivery_enabled": False,
            }
        )


def compose_native_observation_candidate(
    snapshot: NativeIntelliCenterObservationSnapshot,
) -> NativeObservationCandidateComposition:
    """Compose one native snapshot into non-authoritative candidate evidence."""

    read = NativeIntelliCenterObservationProvider(snapshot).read()
    selection = select_non_authoritative_candidate_source(
        requested_source=ObservationSource.NATIVE_INTELLICENTER,
        available_sources={ObservationSource.NATIVE_INTELLICENTER: read.available},
    )
    return NativeObservationCandidateComposition(read=read, selection=selection)
