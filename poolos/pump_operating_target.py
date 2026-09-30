"""Unit-aware pump operating targets.

This module generalizes the configured pump requirement without changing
ownership semantics.  RPM remains the default and compatibility mode for every
existing PoolOS installation.  GPM targets are explicit opt-in policy and must
still pass live native capability/limit checks before command delivery.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from hashlib import sha256
import json
from types import MappingProxyType
from typing import Mapping

from .operating_baselines import PumpOperatingBaselines


class PumpTargetUnit(StrEnum):
    """Supported configured pump-control units."""

    RPM = "rpm"
    GPM = "gpm"


@dataclass(frozen=True, slots=True)
class PumpOperatingTarget:
    """One exact configured pump target."""

    unit: PumpTargetUnit
    value: int

    def __post_init__(self) -> None:
        if isinstance(self.value, bool) or not isinstance(self.value, int):
            raise ValueError("pump target value must be an integer")
        if self.value <= 0:
            raise ValueError("pump target value must be positive")
        if self.unit is PumpTargetUnit.RPM and not (
            PumpOperatingBaselines.MINIMUM_CONFIGURABLE_RPM
            <= self.value
            <= PumpOperatingBaselines.MAXIMUM_CONFIGURABLE_RPM
        ):
            raise ValueError(
                "RPM target must be between "
                f"{PumpOperatingBaselines.MINIMUM_CONFIGURABLE_RPM} and "
                f"{PumpOperatingBaselines.MAXIMUM_CONFIGURABLE_RPM}"
            )

    @property
    def configured_concept(self) -> str:
        """Canonical configured-intent concept for this target."""

        return (
            "pump.configured_rpm"
            if self.unit is PumpTargetUnit.RPM
            else "pump.configured_flow_gpm"
        )

    @property
    def observed_concept(self) -> str:
        """Canonical physical verification concept for this target."""

        return "pump.rpm" if self.unit is PumpTargetUnit.RPM else "pump.gpm"

    @property
    def verification_tolerance(self) -> float:
        """Default physical convergence tolerance for the selected unit."""

        return 25.0 if self.unit is PumpTargetUnit.RPM else 2.0

    def diagnostics(self) -> Mapping[str, object]:
        return MappingProxyType({"unit": self.unit.value, "value": self.value})


@dataclass(frozen=True, slots=True)
class PumpOperatingTargetPolicy:
    """Canonical per-purpose targets for one loaded PoolOS config entry."""

    filtration: PumpOperatingTarget
    solar_heating: PumpOperatingTarget
    gas_heating: PumpOperatingTarget
    temperature_probe: PumpOperatingTarget
    priming: PumpOperatingTarget
    grid_outage: PumpOperatingTarget
    sanitation: PumpOperatingTarget
    spillway: PumpOperatingTarget

    @classmethod
    def from_rpm_baselines(
        cls,
        baselines: PumpOperatingBaselines,
        *,
        sanitation_rpm: int = 3200,
    ) -> "PumpOperatingTargetPolicy":
        """Build the exact legacy-compatible all-RPM policy."""

        rpm = PumpTargetUnit.RPM
        return cls(
            filtration=PumpOperatingTarget(rpm, baselines.filtration_rpm),
            solar_heating=PumpOperatingTarget(rpm, baselines.solar_heating_rpm),
            gas_heating=PumpOperatingTarget(rpm, baselines.gas_heating_rpm),
            temperature_probe=PumpOperatingTarget(rpm, baselines.temperature_probe_rpm),
            priming=PumpOperatingTarget(rpm, baselines.priming_rpm),
            grid_outage=PumpOperatingTarget(rpm, baselines.grid_outage_rpm),
            sanitation=PumpOperatingTarget(rpm, sanitation_rpm),
            spillway=PumpOperatingTarget(rpm, baselines.spillway_rpm),
        )

    @property
    def fingerprint(self) -> str:
        payload = json.dumps(
            {
                name: dict(target.diagnostics())
                for name, target in self.as_dict().items()
            },
            sort_keys=True,
            separators=(",", ":"),
        )
        return sha256(payload.encode()).hexdigest()[:24]

    def as_dict(self) -> Mapping[str, PumpOperatingTarget]:
        return MappingProxyType(
            {
                "filtration": self.filtration,
                "solar_heating": self.solar_heating,
                "gas_heating": self.gas_heating,
                "temperature_probe": self.temperature_probe,
                "priming": self.priming,
                "grid_outage": self.grid_outage,
                "sanitation": self.sanitation,
                "spillway": self.spillway,
            }
        )


__all__ = [
    "PumpOperatingTarget",
    "PumpOperatingTargetPolicy",
    "PumpTargetUnit",
]
