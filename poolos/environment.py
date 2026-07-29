"""Runtime composition boundary for safe simulation, shadow, and live operation."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from types import MappingProxyType
from typing import Iterable, Mapping

from .clock import Clock, SystemClock
from .delivery import DeliveryEndpointKind, EndpointRegistry, VendorCommandEndpoint


class RuntimeMode(str, Enum):
    """Mutually exclusive PoolOS runtime operating modes."""

    SIMULATION = "simulation"
    SHADOW = "shadow"
    LIVE = "live"


class ObservationSourceKind(str, Enum):
    """Provenance categories admitted by a runtime environment."""

    LIVE = "live"
    SIMULATED = "simulated"
    DERIVED = "derived"


class RuntimeEnvironmentError(ValueError):
    """Raised when a runtime environment violates a safety invariant."""


@dataclass(frozen=True, slots=True)
class ObservationPolicy:
    """Immutable allow-list for observation provenance."""

    allowed_sources: frozenset[ObservationSourceKind]

    def allows(self, source: ObservationSourceKind) -> bool:
        return source in self.allowed_sources


@dataclass(frozen=True, slots=True)
class DeliverySafetyPolicy:
    """Immutable allow-list for endpoint delivery behavior."""

    allowed_endpoint_kinds: frozenset[DeliveryEndpointKind]
    physical_delivery_allowed: bool

    def allows(self, endpoint: VendorCommandEndpoint) -> bool:
        return endpoint.delivery_kind in self.allowed_endpoint_kinds


@dataclass(frozen=True, slots=True)
class PoolRuntimeEnvironment:
    """Validated, immutable composition for one PoolOS runtime.

    The environment is selected at startup. It admits observation provenance
    independently from command delivery and rejects unsafe endpoint mixtures
    before any command can be routed.
    """

    mode: RuntimeMode
    installation_id: str
    clock: Clock
    observation_policy: ObservationPolicy
    delivery_policy: DeliverySafetyPolicy
    endpoints: tuple[VendorCommandEndpoint, ...] = ()
    metadata: Mapping[str, str] = field(default_factory=dict)

    def __post_init__(self) -> None:
        installation_id = self.installation_id.strip()
        if not installation_id:
            raise RuntimeEnvironmentError("installation_id must not be empty")
        object.__setattr__(self, "installation_id", installation_id)
        object.__setattr__(self, "endpoints", tuple(self.endpoints))
        object.__setattr__(self, "metadata", MappingProxyType(dict(self.metadata)))
        self._validate_policy_for_mode()
        self._validate_endpoints()

    @property
    def physical_delivery_allowed(self) -> bool:
        return self.delivery_policy.physical_delivery_allowed

    def allows_observation(self, source: ObservationSourceKind) -> bool:
        return self.observation_policy.allows(source)

    def build_endpoint_registry(self) -> EndpointRegistry:
        """Build the writable registry after environment validation."""

        registry = EndpointRegistry()
        for endpoint in self.endpoints:
            registry.register(endpoint)
        return registry

    def _validate_policy_for_mode(self) -> None:
        expected = _delivery_policy_for(self.mode)
        if self.delivery_policy != expected:
            raise RuntimeEnvironmentError(
                f"delivery policy does not match runtime mode {self.mode.value!r}"
            )

    def _validate_endpoints(self) -> None:
        endpoint_ids: set[str] = set()
        for endpoint in self.endpoints:
            endpoint_id = endpoint.endpoint_id.strip()
            if not endpoint_id:
                raise RuntimeEnvironmentError("endpoint_id must not be empty")
            if endpoint_id in endpoint_ids:
                raise RuntimeEnvironmentError(
                    f"duplicate endpoint_id in runtime environment: {endpoint_id!r}"
                )
            endpoint_ids.add(endpoint_id)

            try:
                allowed = self.delivery_policy.allows(endpoint)
            except AttributeError as exc:
                raise RuntimeEnvironmentError(
                    f"endpoint {endpoint_id!r} does not declare delivery_kind"
                ) from exc
            if not allowed:
                raise RuntimeEnvironmentError(
                    f"{self.mode.value} runtime prohibits "
                    f"{endpoint.delivery_kind.value} endpoint {endpoint_id!r}"
                )


@dataclass(slots=True)
class RuntimeEnvironmentBuilder:
    """Construct a validated environment without mutable mode switches."""

    mode: RuntimeMode
    installation_id: str
    clock: Clock = field(default_factory=SystemClock)
    _endpoints: list[VendorCommandEndpoint] = field(default_factory=list)
    _observation_sources: set[ObservationSourceKind] = field(default_factory=set)
    _metadata: dict[str, str] = field(default_factory=dict)

    def allow_observation(
        self,
        *sources: ObservationSourceKind,
    ) -> RuntimeEnvironmentBuilder:
        self._observation_sources.update(sources)
        return self

    def add_endpoint(
        self,
        endpoint: VendorCommandEndpoint,
    ) -> RuntimeEnvironmentBuilder:
        self._endpoints.append(endpoint)
        return self

    def with_metadata(self, **metadata: str) -> RuntimeEnvironmentBuilder:
        for key, value in metadata.items():
            normalized_key = key.strip()
            normalized_value = value.strip()
            if not normalized_key or not normalized_value:
                raise RuntimeEnvironmentError("metadata keys and values must not be empty")
            self._metadata[normalized_key] = normalized_value
        return self

    def build(self) -> PoolRuntimeEnvironment:
        observation_sources = (
            frozenset(self._observation_sources)
            if self._observation_sources
            else _default_observation_sources(self.mode)
        )
        return PoolRuntimeEnvironment(
            mode=self.mode,
            installation_id=self.installation_id,
            clock=self.clock,
            observation_policy=ObservationPolicy(observation_sources),
            delivery_policy=_delivery_policy_for(self.mode),
            endpoints=tuple(self._endpoints),
            metadata=self._metadata,
        )


def build_runtime_environment(
    *,
    mode: RuntimeMode,
    installation_id: str,
    endpoints: Iterable[VendorCommandEndpoint] = (),
    observation_sources: Iterable[ObservationSourceKind] | None = None,
    clock: Clock | None = None,
) -> PoolRuntimeEnvironment:
    """Convenience factory for startup composition code."""

    builder = RuntimeEnvironmentBuilder(
        mode=mode,
        installation_id=installation_id,
        clock=clock if clock is not None else SystemClock(),
    )
    for endpoint in endpoints:
        builder.add_endpoint(endpoint)
    if observation_sources is not None:
        builder.allow_observation(*observation_sources)
    return builder.build()


def _delivery_policy_for(mode: RuntimeMode) -> DeliverySafetyPolicy:
    if mode is RuntimeMode.SIMULATION:
        return DeliverySafetyPolicy(
            allowed_endpoint_kinds=frozenset({DeliveryEndpointKind.SIMULATOR}),
            physical_delivery_allowed=False,
        )
    if mode is RuntimeMode.SHADOW:
        return DeliverySafetyPolicy(
            allowed_endpoint_kinds=frozenset({DeliveryEndpointKind.SHADOW}),
            physical_delivery_allowed=False,
        )
    return DeliverySafetyPolicy(
        allowed_endpoint_kinds=frozenset({DeliveryEndpointKind.PHYSICAL}),
        physical_delivery_allowed=True,
    )


def _default_observation_sources(
    mode: RuntimeMode,
) -> frozenset[ObservationSourceKind]:
    if mode is RuntimeMode.SIMULATION:
        return frozenset(
            {
                ObservationSourceKind.LIVE,
                ObservationSourceKind.SIMULATED,
                ObservationSourceKind.DERIVED,
            }
        )
    if mode is RuntimeMode.SHADOW:
        return frozenset(
            {
                ObservationSourceKind.LIVE,
                ObservationSourceKind.DERIVED,
            }
        )
    return frozenset(
        {
            ObservationSourceKind.LIVE,
            ObservationSourceKind.DERIVED,
        }
    )
