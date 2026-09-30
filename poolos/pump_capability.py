"""Vendor-neutral pump capability evidence for PoolOS."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from types import MappingProxyType
from typing import Any, Mapping, Protocol

from .capabilities import Capability


class PumpCapabilityEvidenceSource(StrEnum):
    """How a pump capability claim was established."""

    NATIVE = "native"
    ADAPTER = "adapter"
    COMMISSIONED_OVERRIDE = "commissioned_override"


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
        if minimum <= 0 or maximum <= 0 or minimum > maximum:
            raise ValueError(f"{label} capability limits are invalid")

    def supports(self, capability: Capability) -> bool:
        """Return whether positive evidence proves one capability."""

        return capability in self.capabilities

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
                "gpm_sensing": self.supports(Capability.FLOW_SENSING),
                "minimum_rpm": self.minimum_rpm,
                "maximum_rpm": self.maximum_rpm,
                "minimum_gpm": self.minimum_gpm,
                "maximum_gpm": self.maximum_gpm,
            }
        )


class PumpCapabilityProvider(Protocol):
    """Adapter contract for vendor-neutral pump capability discovery."""

    def pump_capability_profile(
        self,
        *,
        body: str,
    ) -> PumpCapabilityProfile | None:
        """Return positive capability evidence for one hydraulic body."""


__all__ = [
    "PumpCapabilityEvidenceSource",
    "PumpCapabilityProfile",
    "PumpCapabilityProvider",
]
