"""Fail-closed observation-source selection architecture for PoolOS.

Milestone 12.0C4 introduces a typed boundary between observation provenance and
future source selection.  It deliberately does not integrate with Home
Assistant runtime configuration and does not grant native IntelliCenter
observations production authority.

Production selection remains hard-locked to Home Assistant.  Native source
reads may be represented and evaluated as non-authoritative candidate evidence
for tests and future commissioning work.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import Enum
from types import MappingProxyType
from typing import Any, Generic, Mapping, Protocol, TypeVar


class ObservationSource(str, Enum):
    """Known provenance sources for canonical PoolOS observations."""

    HOME_ASSISTANT = "home_assistant"
    NATIVE_INTELLICENTER = "native_intellicenter"


class ObservationSourceSelectionReason(str, Enum):
    """Stable reasons emitted by source-selection decisions."""

    HOME_ASSISTANT_SELECTED = "HOME_ASSISTANT_SELECTED"
    NATIVE_CANDIDATE_SELECTED = "NATIVE_CANDIDATE_SELECTED"
    NATIVE_PRODUCTION_SELECTION_DISABLED = "NATIVE_PRODUCTION_SELECTION_DISABLED"
    REQUESTED_SOURCE_UNAVAILABLE = "REQUESTED_SOURCE_UNAVAILABLE"
    HOME_ASSISTANT_UNAVAILABLE = "HOME_ASSISTANT_UNAVAILABLE"
    NO_AUTHORIZED_SOURCE_AVAILABLE = "NO_AUTHORIZED_SOURCE_AVAILABLE"


PayloadT = TypeVar("PayloadT", covariant=True)


@dataclass(frozen=True, slots=True)
class ObservationSourceRead(Generic[PayloadT]):
    """Immutable result from one observation provider read.

    ``payload`` is intentionally generic.  At the Home Assistant composition
    boundary it can carry the existing canonical snapshot type; native
    commissioning can carry its existing canonical native snapshot type.  The
    selector never interprets or mutates observation values.
    """

    source: ObservationSource
    generated_at: datetime
    available: bool
    payload: PayloadT | None
    failure_reason_code: str | None = None

    def __post_init__(self) -> None:
        if self.generated_at.tzinfo is None or self.generated_at.utcoffset() is None:
            raise ValueError("generated_at must be timezone-aware")
        if self.available and self.payload is None:
            raise ValueError("available source read must contain a payload")
        if self.available and self.failure_reason_code is not None:
            raise ValueError("available source read must not contain a failure reason")
        if not self.available and self.payload is not None:
            raise ValueError("unavailable source read must not contain a payload")
        if self.failure_reason_code is not None:
            normalized = self.failure_reason_code.strip().upper()
            if not normalized:
                raise ValueError("failure_reason_code must not be blank")
            object.__setattr__(self, "failure_reason_code", normalized[:64])


class ObservationSourceProvider(Protocol[PayloadT]):
    """Read-only provider contract for one canonical observation source."""

    @property
    def source(self) -> ObservationSource:
        """Return the provider's fixed source identity."""

    def read(self) -> ObservationSourceRead[PayloadT]:
        """Return one immutable read result without issuing commands."""


@dataclass(frozen=True, slots=True)
class ObservationSourceSelection:
    """Immutable evidence describing one source-selection decision."""

    requested_source: ObservationSource
    effective_source: ObservationSource | None
    selected: bool
    authoritative_observation_source: bool
    fallback_used: bool
    reason: ObservationSourceSelectionReason
    production_native_selection_enabled: bool = False
    command_authority: str = "none"
    command_delivery_enabled: bool = False
    physical_delivery_enabled: bool = False

    def __post_init__(self) -> None:
        if self.command_authority != "none":
            raise ValueError("observation source selection must not grant command authority")
        if self.command_delivery_enabled or self.physical_delivery_enabled:
            raise ValueError("observation source selection must not enable command delivery")
        if self.production_native_selection_enabled:
            raise ValueError("12.0C4 must keep production native selection disabled")
        if self.selected != (self.effective_source is not None):
            raise ValueError("selected must match effective_source presence")
        if self.authoritative_observation_source and self.effective_source is not ObservationSource.HOME_ASSISTANT:
            raise ValueError("12.0C4 authoritative observations must remain Home Assistant")
        if self.fallback_used and self.effective_source is None:
            raise ValueError("fallback requires an effective source")

    def diagnostics(self) -> Mapping[str, Any]:
        """Return stable bounded diagnostics for Home Assistant publication later."""

        return MappingProxyType(
            {
                "requested_source": self.requested_source.value,
                "effective_source": (
                    None if self.effective_source is None else self.effective_source.value
                ),
                "selected": self.selected,
                "authoritative_observation_source": self.authoritative_observation_source,
                "fallback_used": self.fallback_used,
                "reason": self.reason.value,
                "production_native_selection_enabled": self.production_native_selection_enabled,
                "command_authority": self.command_authority,
                "command_delivery_enabled": self.command_delivery_enabled,
                "physical_delivery_enabled": self.physical_delivery_enabled,
            }
        )


def select_production_observation_source(
    *,
    requested_source: ObservationSource,
    home_assistant_available: bool,
    native_intellicenter_available: bool,
) -> ObservationSourceSelection:
    """Resolve the production observation source with a hard C4 safety lock.

    Home Assistant is the only source that may become authoritative in 12.0C4.
    A request for the native IntelliCenter source is rejected even when native
    evidence is healthy.  If Home Assistant remains available, the result
    explicitly falls back to Home Assistant; otherwise selection fails closed.

    ``native_intellicenter_available`` is retained in the API so diagnostics and
    tests prove that native availability alone can never elevate authority.
    """

    if requested_source is ObservationSource.HOME_ASSISTANT:
        if home_assistant_available:
            return ObservationSourceSelection(
                requested_source=requested_source,
                effective_source=ObservationSource.HOME_ASSISTANT,
                selected=True,
                authoritative_observation_source=True,
                fallback_used=False,
                reason=ObservationSourceSelectionReason.HOME_ASSISTANT_SELECTED,
            )
        return ObservationSourceSelection(
            requested_source=requested_source,
            effective_source=None,
            selected=False,
            authoritative_observation_source=False,
            fallback_used=False,
            reason=ObservationSourceSelectionReason.HOME_ASSISTANT_UNAVAILABLE,
        )

    # Native production selection is structurally disabled for milestone C4.
    # The availability flag is intentionally observed but cannot change the
    # authority result.  This assignment makes that safety property explicit.
    _native_candidate_available = native_intellicenter_available
    del _native_candidate_available

    if home_assistant_available:
        return ObservationSourceSelection(
            requested_source=requested_source,
            effective_source=ObservationSource.HOME_ASSISTANT,
            selected=True,
            authoritative_observation_source=True,
            fallback_used=True,
            reason=ObservationSourceSelectionReason.NATIVE_PRODUCTION_SELECTION_DISABLED,
        )
    return ObservationSourceSelection(
        requested_source=requested_source,
        effective_source=None,
        selected=False,
        authoritative_observation_source=False,
        fallback_used=False,
        reason=ObservationSourceSelectionReason.NO_AUTHORIZED_SOURCE_AVAILABLE,
    )


def select_non_authoritative_candidate_source(
    *,
    requested_source: ObservationSource,
    available_sources: Mapping[ObservationSource, bool],
) -> ObservationSourceSelection:
    """Select a candidate source for tests/commissioning without authority.

    This helper exists so native-source composition can be developed and tested
    before production source switching is approved.  A candidate selection is
    never marked authoritative and cannot enable command or physical delivery.
    """

    available = bool(available_sources.get(requested_source, False))
    if not available:
        return ObservationSourceSelection(
            requested_source=requested_source,
            effective_source=None,
            selected=False,
            authoritative_observation_source=False,
            fallback_used=False,
            reason=ObservationSourceSelectionReason.REQUESTED_SOURCE_UNAVAILABLE,
        )

    reason = (
        ObservationSourceSelectionReason.HOME_ASSISTANT_SELECTED
        if requested_source is ObservationSource.HOME_ASSISTANT
        else ObservationSourceSelectionReason.NATIVE_CANDIDATE_SELECTED
    )
    return ObservationSourceSelection(
        requested_source=requested_source,
        effective_source=requested_source,
        selected=True,
        authoritative_observation_source=False,
        fallback_used=False,
        reason=reason,
    )
