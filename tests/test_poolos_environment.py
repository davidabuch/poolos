"""Tests for the immutable runtime environment safety boundary."""

from __future__ import annotations

from dataclasses import FrozenInstanceError, dataclass
from datetime import datetime, timezone
from typing import ClassVar

import pytest

from poolos.clock import FixedClock
from poolos.delivery import (
    DeliveryEndpointKind,
    PentairCommandResponse,
    PentairVendorCommandEndpoint,
    SimulatorVendorCommandEndpoint,
)
from poolos.environment import (
    DeliverySafetyPolicy,
    ObservationPolicy,
    ObservationSourceKind,
    PoolRuntimeEnvironment,
    RuntimeEnvironmentBuilder,
    RuntimeEnvironmentError,
    RuntimeMode,
    build_runtime_environment,
)
from poolos.hal import CommandReceipt, CommandStatus
from poolos.integration import VendorCommand


@dataclass(slots=True)
class ShadowEndpoint:
    delivery_kind: ClassVar[DeliveryEndpointKind] = DeliveryEndpointKind.SHADOW
    endpoint_id: str = "shadow-recorder"
    vendor: str = "pentair"

    def deliver(
        self,
        command: VendorCommand,
        *,
        correlation_id: str,
        timeout: float | None = None,
    ) -> CommandReceipt:
        return CommandReceipt(CommandStatus.ACKNOWLEDGED)


class PentairClientStub:
    def execute(
        self,
        request: object,
        *,
        timeout: float | None = None,
    ) -> PentairCommandResponse:
        return PentairCommandResponse(accepted=True, acknowledged=True)


def simulator_endpoint(endpoint_id: str = "sim-controller") -> SimulatorVendorCommandEndpoint:
    return SimulatorVendorCommandEndpoint(endpoint_id, "pentair")


def physical_endpoint(endpoint_id: str = "main-controller") -> PentairVendorCommandEndpoint:
    return PentairVendorCommandEndpoint(endpoint_id, PentairClientStub())


def test_simulation_environment_accepts_simulator_and_live_observations() -> None:
    environment = build_runtime_environment(
        mode=RuntimeMode.SIMULATION,
        installation_id="buch-family-sim",
        endpoints=(simulator_endpoint(),),
    )

    assert environment.mode is RuntimeMode.SIMULATION
    assert not environment.physical_delivery_allowed
    assert environment.allows_observation(ObservationSourceKind.LIVE)
    assert environment.allows_observation(ObservationSourceKind.SIMULATED)
    assert environment.allows_observation(ObservationSourceKind.DERIVED)
    assert environment.build_endpoint_registry().get("sim-controller").delivery_kind is (
        DeliveryEndpointKind.SIMULATOR
    )


def test_simulation_environment_rejects_physical_endpoint() -> None:
    with pytest.raises(RuntimeEnvironmentError, match="simulation runtime prohibits physical"):
        build_runtime_environment(
            mode=RuntimeMode.SIMULATION,
            installation_id="buch-family-sim",
            endpoints=(physical_endpoint(),),
        )


def test_shadow_environment_accepts_only_shadow_endpoint() -> None:
    environment = build_runtime_environment(
        mode=RuntimeMode.SHADOW,
        installation_id="buch-family-shadow",
        endpoints=(ShadowEndpoint(),),
    )

    assert not environment.physical_delivery_allowed
    assert environment.build_endpoint_registry().get("shadow-recorder").delivery_kind is (
        DeliveryEndpointKind.SHADOW
    )
    assert environment.allows_observation(ObservationSourceKind.LIVE)
    assert not environment.allows_observation(ObservationSourceKind.SIMULATED)


@pytest.mark.parametrize(
    "endpoint",
    [simulator_endpoint(), physical_endpoint()],
)
def test_shadow_environment_rejects_non_shadow_endpoints(endpoint: object) -> None:
    with pytest.raises(RuntimeEnvironmentError, match="shadow runtime prohibits"):
        build_runtime_environment(
            mode=RuntimeMode.SHADOW,
            installation_id="buch-family-shadow",
            endpoints=(endpoint,),  # type: ignore[arg-type]
        )


def test_live_environment_accepts_physical_endpoint() -> None:
    environment = build_runtime_environment(
        mode=RuntimeMode.LIVE,
        installation_id="buch-family-live",
        endpoints=(physical_endpoint(),),
    )

    assert environment.physical_delivery_allowed
    assert environment.build_endpoint_registry().get("main-controller").delivery_kind is (
        DeliveryEndpointKind.PHYSICAL
    )


def test_live_environment_rejects_simulator_endpoint() -> None:
    with pytest.raises(RuntimeEnvironmentError, match="live runtime prohibits simulator"):
        build_runtime_environment(
            mode=RuntimeMode.LIVE,
            installation_id="buch-family-live",
            endpoints=(simulator_endpoint(),),
        )


def test_observation_permissions_are_independent_from_delivery_mode() -> None:
    environment = build_runtime_environment(
        mode=RuntimeMode.SIMULATION,
        installation_id="hybrid-sim",
        endpoints=(simulator_endpoint(),),
        observation_sources=(ObservationSourceKind.LIVE,),
    )

    assert environment.allows_observation(ObservationSourceKind.LIVE)
    assert not environment.allows_observation(ObservationSourceKind.SIMULATED)
    assert not environment.physical_delivery_allowed


def test_builder_preserves_explicit_clock_and_metadata() -> None:
    clock = FixedClock(datetime(2026, 7, 29, 20, 0, tzinfo=timezone.utc))
    environment = (
        RuntimeEnvironmentBuilder(RuntimeMode.SIMULATION, " sim-pool ", clock)
        .allow_observation(ObservationSourceKind.LIVE, ObservationSourceKind.DERIVED)
        .add_endpoint(simulator_endpoint())
        .with_metadata(purpose="multi-day soak test")
        .build()
    )

    assert environment.installation_id == "sim-pool"
    assert environment.clock is clock
    assert environment.metadata == {"purpose": "multi-day soak test"}


def test_environment_rejects_blank_and_duplicate_identity() -> None:
    with pytest.raises(RuntimeEnvironmentError, match="installation_id"):
        build_runtime_environment(mode=RuntimeMode.SIMULATION, installation_id=" ")

    with pytest.raises(RuntimeEnvironmentError, match="duplicate endpoint_id"):
        build_runtime_environment(
            mode=RuntimeMode.SIMULATION,
            installation_id="sim-pool",
            endpoints=(simulator_endpoint("same"), simulator_endpoint("same")),
        )


def test_environment_rejects_policy_that_does_not_match_mode() -> None:
    with pytest.raises(RuntimeEnvironmentError, match="delivery policy"):
        PoolRuntimeEnvironment(
            mode=RuntimeMode.SIMULATION,
            installation_id="sim-pool",
            clock=FixedClock(datetime(2026, 7, 29, tzinfo=timezone.utc)),
            observation_policy=ObservationPolicy(
                frozenset({ObservationSourceKind.LIVE})
            ),
            delivery_policy=DeliverySafetyPolicy(
                frozenset({DeliveryEndpointKind.PHYSICAL}),
                physical_delivery_allowed=True,
            ),
        )


def test_environment_mode_and_identity_are_immutable_after_startup() -> None:
    environment = build_runtime_environment(
        mode=RuntimeMode.SIMULATION,
        installation_id="sim-pool",
    )

    with pytest.raises(FrozenInstanceError):
        environment.mode = RuntimeMode.LIVE  # type: ignore[misc]
    with pytest.raises(FrozenInstanceError):
        environment.installation_id = "live-pool"  # type: ignore[misc]


def test_concrete_endpoints_declare_their_delivery_kind() -> None:
    assert simulator_endpoint().delivery_kind is DeliveryEndpointKind.SIMULATOR
    assert physical_endpoint().delivery_kind is DeliveryEndpointKind.PHYSICAL
