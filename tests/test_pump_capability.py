"""Tests for the vendor-neutral pump capability contract."""

from __future__ import annotations

import pytest

from poolos.capabilities import Capability
from poolos.pump_capability import (
    PumpCapabilityEvidenceSource,
    PumpCapabilityProfile,
)


def test_profile_separates_flow_sensing_from_flow_control() -> None:
    profile = PumpCapabilityProfile(
        pump_id="pump-1",
        provider="example",
        evidence_source=PumpCapabilityEvidenceSource.ADAPTER,
        capabilities=frozenset(
            {
                Capability.RPM_CONTROL,
                Capability.RPM_SENSING,
                Capability.FLOW_SENSING,
            }
        ),
        minimum_rpm=600,
        maximum_rpm=3450,
    )

    data = dict(profile.as_mapping())

    assert data["rpm_control"] is True
    assert data["rpm_sensing"] is True
    assert data["gpm_sensing"] is True
    assert data["gpm_control"] is False
    assert data["minimum_gpm"] is None
    assert data["maximum_gpm"] is None


def test_flow_control_requires_complete_positive_gpm_limits() -> None:
    with pytest.raises(
        ValueError,
        match="flow control capability requires proven GPM limits",
    ):
        PumpCapabilityProfile(
            pump_id="pump-1",
            provider="example",
            evidence_source=PumpCapabilityEvidenceSource.NATIVE,
            capabilities=frozenset({Capability.FLOW_CONTROL}),
        )


def test_profile_preserves_capability_provenance() -> None:
    profile = PumpCapabilityProfile(
        pump_id="pump-1",
        pump_circuit_id="circuit-1",
        provider="hayward",
        evidence_source=PumpCapabilityEvidenceSource.COMMISSIONED_OVERRIDE,
        capabilities=frozenset({Capability.FLOW_CONTROL}),
        minimum_gpm=20,
        maximum_gpm=120,
    )

    data = dict(profile.as_mapping())

    assert data["provider"] == "hayward"
    assert data["evidence_source"] == "commissioned_override"
    assert data["pump_circuit_id"] == "circuit-1"
    assert data["gpm_control"] is True
