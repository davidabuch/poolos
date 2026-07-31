"""Simulator-only composition boundary for vendor-command delivery.

This module does not translate canonical :class:`PoolOperation` objects and it
is not an execution coordinator.  It composes the existing runtime-environment,
endpoint-registry, and vendor-command gateway boundaries into one explicitly
simulation-only delivery facade.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from .delivery import (
    DeliveryEndpointKind,
    DeliveryReceipt,
    VendorCommandGateway,
)
from .environment import PoolRuntimeEnvironment, RuntimeMode
from .integration import VendorCommand


class SimulatorExecutionGatewayError(ValueError):
    """Raised when simulator-gateway composition violates a safety invariant."""


@dataclass(frozen=True, slots=True)
class SimulatorGatewayRoute:
    """Immutable description of one admitted simulator endpoint."""

    endpoint_id: str
    vendor: str

    def __post_init__(self) -> None:
        endpoint_id = self.endpoint_id.strip()
        vendor = self.vendor.strip().lower()
        if not endpoint_id:
            raise ValueError("endpoint_id must not be empty")
        if not vendor:
            raise ValueError("vendor must not be empty")
        object.__setattr__(self, "endpoint_id", endpoint_id)
        object.__setattr__(self, "vendor", vendor)


@dataclass(frozen=True, slots=True)
class SimulatorExecutionGateway:
    """Deliver vendor commands only through admitted simulator endpoints.

    Construction performs all mode and endpoint-kind checks before a command
    can be routed.  The underlying :class:`VendorCommandGateway` remains the
    single boundary that resolves an endpoint and invokes it exactly once.
    """

    environment: PoolRuntimeEnvironment
    _gateway: VendorCommandGateway = field(repr=False, compare=False)
    routes: tuple[SimulatorGatewayRoute, ...]

    @classmethod
    def from_environment(
        cls,
        environment: PoolRuntimeEnvironment,
    ) -> SimulatorExecutionGateway:
        """Build a simulator gateway from one validated runtime environment."""

        if environment.mode is not RuntimeMode.SIMULATION:
            raise SimulatorExecutionGatewayError(
                "simulator execution gateway requires simulation runtime mode"
            )
        if environment.physical_delivery_allowed:
            raise SimulatorExecutionGatewayError(
                "simulation runtime must prohibit physical delivery"
            )
        if not environment.endpoints:
            raise SimulatorExecutionGatewayError(
                "simulation runtime must define at least one simulator endpoint"
            )

        routes: list[SimulatorGatewayRoute] = []
        for endpoint in environment.endpoints:
            if endpoint.delivery_kind is not DeliveryEndpointKind.SIMULATOR:
                raise SimulatorExecutionGatewayError(
                    "simulator execution gateway prohibits "
                    f"{endpoint.delivery_kind.value} endpoint {endpoint.endpoint_id!r}"
                )
            routes.append(
                SimulatorGatewayRoute(
                    endpoint_id=endpoint.endpoint_id,
                    vendor=endpoint.vendor,
                )
            )

        registry = environment.build_endpoint_registry()
        return cls(
            environment=environment,
            _gateway=VendorCommandGateway(registry),
            routes=tuple(routes),
        )

    @property
    def endpoint_ids(self) -> tuple[str, ...]:
        """Return admitted endpoint identities in deterministic registration order."""

        return tuple(route.endpoint_id for route in self.routes)

    def route_for_vendor(self, vendor: str) -> SimulatorGatewayRoute:
        """Resolve the single simulator route for a vendor.

        Explicit endpoint delivery remains available for installations with
        multiple endpoints of the same vendor.  Automatic vendor routing is
        intentionally rejected when it would be ambiguous.
        """

        normalized_vendor = vendor.strip().lower()
        if not normalized_vendor:
            raise ValueError("vendor must not be empty")
        matches = tuple(route for route in self.routes if route.vendor == normalized_vendor)
        if not matches:
            raise SimulatorExecutionGatewayError(
                f"no simulator endpoint is configured for vendor {normalized_vendor!r}"
            )
        if len(matches) > 1:
            raise SimulatorExecutionGatewayError(
                f"multiple simulator endpoints are configured for vendor {normalized_vendor!r}; "
                "endpoint_id is required"
            )
        return matches[0]

    def deliver(
        self,
        command: VendorCommand,
        *,
        correlation_id: str,
        endpoint_id: str | None = None,
        timeout: float | None = None,
    ) -> DeliveryReceipt:
        """Deliver one vendor command through a simulator endpoint exactly once."""

        route = (
            self.route_for_vendor(command.vendor)
            if endpoint_id is None
            else self._route_by_id(endpoint_id)
        )
        return self._gateway.deliver(
            route.endpoint_id,
            command,
            correlation_id=correlation_id,
            timeout=timeout,
        )

    def _route_by_id(self, endpoint_id: str) -> SimulatorGatewayRoute:
        normalized_id = endpoint_id.strip()
        if not normalized_id:
            raise ValueError("endpoint_id must not be empty")
        for route in self.routes:
            if route.endpoint_id == normalized_id:
                return route
        raise SimulatorExecutionGatewayError(
            f"simulator endpoint is not admitted by this gateway: {normalized_id!r}"
        )
