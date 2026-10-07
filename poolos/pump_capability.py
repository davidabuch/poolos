"""Vendor-neutral pump capability evidence for PoolOS."""

from __future__ import annotations

from dataclasses import dataclass, replace
from enum import StrEnum
from types import MappingProxyType
from typing import Any, Mapping, Protocol

from .capabilities import Capability


class PumpCapabilityEvidenceSource(StrEnum):
    """How a pump capability claim was established."""

    NATIVE = "native"
    ADAPTER = "adapter"
    COMMISSIONED_OVERRIDE = "commissioned_override"


class PumpCapabilitySupport(StrEnum):
    """Tri-state support evidence for capabilities that can be commissioned."""

    SUPPORTED = "supported"
    UNSUPPORTED = "unsupported"
    UNKNOWN = "unknown"


@dataclass(frozen=True, slots=True)
class CommissionedPumpCapability:
    """Persisted installer evidence bound to one exact provider pump identity."""

    provider: str
    pump_id: str
    flow_control_supported: bool
    minimum_gpm: int | None = None
    maximum_gpm: int | None = None

    def __post_init__(self) -> None:
        if not self.provider.strip():
            raise ValueError("commissioned pump provider must not be blank")
        if not self.pump_id.strip():
            raise ValueError("commissioned pump_id must not be blank")
        if self.flow_control_supported:
            PumpCapabilityProfile._validate_range(
                self.minimum_gpm,
                self.maximum_gpm,
                "commissioned GPM",
            )
            if self.minimum_gpm is None or self.maximum_gpm is None:
                raise ValueError(
                    "commissioned GPM support requires complete positive limits"
                )
        elif self.minimum_gpm is not None or self.maximum_gpm is not None:
            raise ValueError(
                "commissioned RPM-only capability must not include GPM limits"
            )


@dataclass(frozen=True, slots=True)
class PumpCapabilityProfile:
    """Typed, vendor-neutral control and sensing capabilities for one pump."""

    pump_id: str
    provider: str
    evidence_source: PumpCapabilityEvidenceSource
    capabilities: frozenset[Capability]
    pump_circuit_id: str | None = None
    minimum_rpm: int | None = None
    maximum_rpm: int | None = None
    minimum_gpm: int | None = None
    maximum_gpm: int | None = None
    flow_control_support: PumpCapabilitySupport = PumpCapabilitySupport.UNKNOWN

    def __post_init__(self) -> None:
        if not self.pump_id.strip():
            raise ValueError("pump capability pump_id must not be blank")
        if not self.provider.strip():
            raise ValueError("pump capability provider must not be blank")
        self._validate_range(self.minimum_rpm, self.maximum_rpm, "RPM")
        self._validate_range(self.minimum_gpm, self.maximum_gpm, "GPM")
        if Capability.RPM_CONTROL in self.capabilities and (
            self.minimum_rpm is None or self.maximum_rpm is None
        ):
            raise ValueError("RPM control capability requires proven RPM limits")
        if Capability.FLOW_CONTROL in self.capabilities and (
            self.minimum_gpm is None or self.maximum_gpm is None
        ):
            raise ValueError("flow control capability requires proven GPM limits")
        if (
            Capability.FLOW_CONTROL in self.capabilities
            and self.flow_control_support is PumpCapabilitySupport.UNSUPPORTED
        ):
            raise ValueError("flow control cannot be both supported and unsupported")

    @staticmethod
    def _validate_range(
        minimum: int | None,
        maximum: int | None,
        label: str,
    ) -> None:
        if (minimum is None) != (maximum is None):
            raise ValueError(f"{label} capability limits must be complete")
        if minimum is None:
            return
        assert maximum is not None
        if minimum <= 0 or maximum <= 0 or minimum > maximum:
            raise ValueError(f"{label} capability limits are invalid")

    def supports(self, capability: Capability) -> bool:
        """Return whether positive evidence proves one capability."""

        return capability in self.capabilities

    @property
    def effective_flow_control_support(self) -> PumpCapabilitySupport:
        """Return the resolved tri-state flow-control evidence."""

        if self.supports(Capability.FLOW_CONTROL):
            return PumpCapabilitySupport.SUPPORTED
        return self.flow_control_support

    def as_mapping(self) -> Mapping[str, Any]:
        """Return an immutable HA/diagnostics representation."""

        return MappingProxyType(
            {
                "pump_id": self.pump_id,
                "pump_circuit_id": self.pump_circuit_id,
                "provider": self.provider,
                "evidence_source": self.evidence_source.value,
                "rpm_control": self.supports(Capability.RPM_CONTROL),
                "rpm_sensing": self.supports(Capability.RPM_SENSING),
                "gpm_control": self.supports(Capability.FLOW_CONTROL),
                "gpm_control_status": self.effective_flow_control_support.value,
                "gpm_sensing": self.supports(Capability.FLOW_SENSING),
                "minimum_rpm": self.minimum_rpm,
                "maximum_rpm": self.maximum_rpm,
                "minimum_gpm": self.minimum_gpm,
                "maximum_gpm": self.maximum_gpm,
            }
        )


def resolve_commissioned_pump_capability(
    profile: PumpCapabilityProfile | None,
    commissioned: CommissionedPumpCapability | None,
) -> PumpCapabilityProfile | None:
    """Apply exact-identity commissioning only when native/adapter evidence is unknown."""

    if profile is None or commissioned is None:
        return profile
    if profile.provider != commissioned.provider or profile.pump_id != commissioned.pump_id:
        return profile
    if profile.effective_flow_control_support is not PumpCapabilitySupport.UNKNOWN:
        return profile

    if commissioned.flow_control_supported:
        return replace(
            profile,
            evidence_source=PumpCapabilityEvidenceSource.COMMISSIONED_OVERRIDE,
            capabilities=frozenset(
                set(profile.capabilities) | {Capability.FLOW_CONTROL}
            ),
            minimum_gpm=commissioned.minimum_gpm,
            maximum_gpm=commissioned.maximum_gpm,
            flow_control_support=PumpCapabilitySupport.SUPPORTED,
        )
    return replace(
        profile,
        evidence_source=PumpCapabilityEvidenceSource.COMMISSIONED_OVERRIDE,
        flow_control_support=PumpCapabilitySupport.UNSUPPORTED,
    )


class PumpCapabilityProvider(Protocol):
    """Adapter contract for vendor-neutral pump capability discovery."""

    def pump_capability_profile(
        self,
        *,
        body: str,
    ) -> PumpCapabilityProfile | None:
        """Return resolved capability evidence for one hydraulic body."""


__all__ = [
    "CommissionedPumpCapability",
    "PumpCapabilityEvidenceSource",
    "PumpCapabilityProfile",
    "PumpCapabilityProvider",
    "PumpCapabilitySupport",
    "resolve_commissioned_pump_capability",
]
