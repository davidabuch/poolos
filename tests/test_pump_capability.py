"""Tests for the vendor-neutral pump capability contract."""

from __future__ import annotations

import pytest

from poolos.capabilities import Capability
from poolos.pump_capability import (
    CommissionedPumpCapability,
    PumpCapabilityEvidenceSource,
    PumpCapabilityProfile,
    PumpCapabilitySupport,
    resolve_commissioned_pump_capability,
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


def test_unknown_flow_control_can_be_commissioned_for_exact_identity() -> None:
    native = PumpCapabilityProfile(
        pump_id="pump-1",
        provider="jandy",
        evidence_source=PumpCapabilityEvidenceSource.ADAPTER,
        capabilities=frozenset({Capability.RPM_CONTROL}),
        minimum_rpm=600,
        maximum_rpm=3450,
        flow_control_support=PumpCapabilitySupport.UNKNOWN,
    )
    commissioned = CommissionedPumpCapability(
        provider="jandy",
        pump_id="pump-1",
        flow_control_supported=True,
        minimum_gpm=20,
        maximum_gpm=120,
    )

    resolved = resolve_commissioned_pump_capability(native, commissioned)

    assert resolved is not None
    assert resolved.supports(Capability.FLOW_CONTROL) is True
    assert resolved.minimum_gpm == 20
    assert resolved.maximum_gpm == 120
    assert resolved.evidence_source is PumpCapabilityEvidenceSource.COMMISSIONED_OVERRIDE
    assert (
        resolved.effective_flow_control_support
        is PumpCapabilitySupport.SUPPORTED
    )


def test_explicit_unsupported_flow_control_cannot_be_overridden() -> None:
    native = PumpCapabilityProfile(
        pump_id="pump-1",
        provider="intellicenter",
        evidence_source=PumpCapabilityEvidenceSource.NATIVE,
        capabilities=frozenset({Capability.RPM_CONTROL}),
        minimum_rpm=450,
        maximum_rpm=3450,
        flow_control_support=PumpCapabilitySupport.UNSUPPORTED,
    )
    commissioned = CommissionedPumpCapability(
        provider="intellicenter",
        pump_id="pump-1",
        flow_control_supported=True,
        minimum_gpm=15,
        maximum_gpm=130,
    )

    assert resolve_commissioned_pump_capability(native, commissioned) == native


def test_commissioning_is_invalidated_by_pump_identity_change() -> None:
    native = PumpCapabilityProfile(
        pump_id="replacement-pump",
        provider="hayward",
        evidence_source=PumpCapabilityEvidenceSource.ADAPTER,
        capabilities=frozenset({Capability.RPM_CONTROL}),
        minimum_rpm=600,
        maximum_rpm=3450,
        flow_control_support=PumpCapabilitySupport.UNKNOWN,
    )
    old = CommissionedPumpCapability(
        provider="hayward",
        pump_id="old-pump",
        flow_control_supported=True,
        minimum_gpm=20,
        maximum_gpm=120,
    )

    assert resolve_commissioned_pump_capability(native, old) == native


def test_commissioned_rpm_only_resolves_unknown_to_unsupported() -> None:
    native = PumpCapabilityProfile(
        pump_id="pump-1",
        provider="unknown-adapter",
        evidence_source=PumpCapabilityEvidenceSource.ADAPTER,
        capabilities=frozenset({Capability.RPM_CONTROL}),
        minimum_rpm=600,
        maximum_rpm=3450,
        flow_control_support=PumpCapabilitySupport.UNKNOWN,
    )
    commissioned = CommissionedPumpCapability(
        provider="unknown-adapter",
        pump_id="pump-1",
        flow_control_supported=False,
    )

    resolved = resolve_commissioned_pump_capability(native, commissioned)

    assert resolved is not None
    assert resolved.supports(Capability.FLOW_CONTROL) is False
    assert (
        resolved.effective_flow_control_support
        is PumpCapabilitySupport.UNSUPPORTED
    )
    assert resolved.evidence_source is PumpCapabilityEvidenceSource.COMMISSIONED_OVERRIDE
