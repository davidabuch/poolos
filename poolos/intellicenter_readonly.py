"""PoolOS-owned read-only IntelliCenter snapshot boundary.

The boundary accepts immutable transport evidence and produces canonical
observations. It contains no connection, command, service, or write interface.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import Enum
from types import MappingProxyType
from typing import Any, Mapping, Protocol

from .observations import (
    ObservationQuality,
    ObservationSourceKind,
    PoolObservation,
    TruthLevel,
)

NATIVE_ADAPTER_ID = "poolos.native_intellicenter.readonly.v1"


class NativeIntelliCenterStatus(str, Enum):
    """Availability of the shadow native read source."""

    INITIALIZING = "INITIALIZING"
    AVAILABLE = "AVAILABLE"
    UNAVAILABLE = "UNAVAILABLE"


class NativeBodyKind(str, Enum):
    POOL = "pool"
    SPA = "spa"
    UNKNOWN = "unknown"


class NativeTemperatureKind(str, Enum):
    AIR = "air"
    WATER = "water"
    SOLAR = "solar"
    UNKNOWN = "unknown"


@dataclass(frozen=True, slots=True)
class NativeBodyState:
    native_id: str
    name: str
    kind: NativeBodyKind
    active: bool
    heating_active: bool
    current_temperature: float | None
    target_temperature: float | None
    active_heat_source: str | None = None
    selected_heat_mode: str | None = None


@dataclass(frozen=True, slots=True)
class NativePumpState:
    native_id: str
    name: str
    running: bool
    rpm: float | None
    gpm: float | None
    power_watts: float | None


@dataclass(frozen=True, slots=True)
class NativeTemperatureState:
    native_id: str
    name: str
    kind: NativeTemperatureKind
    temperature: float | None


@dataclass(frozen=True, slots=True)
class NativeCircuitState:
    native_id: str
    name: str
    active: bool
    use: str | None = None
    subtype: str | None = None


@dataclass(frozen=True, slots=True)
class NativeIntelliCenterTransportSnapshot:
    """Minimal immutable protocol snapshot admitted by the PoolOS adapter."""

    source_id: str
    observed_at: datetime
    connected: bool
    temperature_unit: str
    bodies: tuple[NativeBodyState, ...] = ()
    pumps: tuple[NativePumpState, ...] = ()
    temperatures: tuple[NativeTemperatureState, ...] = ()
    circuits: tuple[NativeCircuitState, ...] = ()

    def __post_init__(self) -> None:
        if not self.source_id.strip():
            raise ValueError("native source_id must not be blank")
        if self.observed_at.tzinfo is None or self.observed_at.utcoffset() is None:
            raise ValueError("native observed_at must be timezone-aware")
        object.__setattr__(self, "bodies", tuple(self.bodies))
        object.__setattr__(self, "pumps", tuple(self.pumps))
        object.__setattr__(self, "temperatures", tuple(self.temperatures))
        object.__setattr__(self, "circuits", tuple(self.circuits))


class NativeIntelliCenterReadError(RuntimeError):
    """Explicit failure from a read-only native snapshot source."""

    def __init__(self, reason_code: str) -> None:
        reason = reason_code.strip().upper()
        if not reason:
            raise ValueError("native failure reason_code must not be blank")
        self.reason_code = reason
        super().__init__(reason)


class NativeIntelliCenterReadSource(Protocol):
    """Minimal source contract; deliberately exposes only a read operation."""

    def read_snapshot(self) -> NativeIntelliCenterTransportSnapshot:
        """Return one immutable transport snapshot or raise a typed read error."""


@dataclass(frozen=True, slots=True)
class NativeIntelliCenterObservationSnapshot:
    """Canonical observations from one native read attempt."""

    generated_at: datetime
    status: NativeIntelliCenterStatus
    source_id: str | None
    observations: tuple[PoolObservation, ...]
    missing_concepts: tuple[str, ...]
    failure_reason_code: str | None = None

    def __post_init__(self) -> None:
        if self.generated_at.tzinfo is None or self.generated_at.utcoffset() is None:
            raise ValueError("native snapshot generated_at must be timezone-aware")
        object.__setattr__(
            self,
            "observations",
            tuple(sorted(self.observations, key=lambda item: item.observation_id)),
        )
        object.__setattr__(self, "missing_concepts", tuple(sorted(self.missing_concepts)))

    @property
    def available(self) -> bool:
        return self.status is NativeIntelliCenterStatus.AVAILABLE

    def diagnostics(self) -> Mapping[str, Any]:
        return MappingProxyType(
            {
                "generated_at": self.generated_at.isoformat(),
                "status": self.status.value,
                "source_id": self.source_id,
                "observation_count": len(self.observations),
                "missing_concept_count": len(self.missing_concepts),
                "missing_concepts": list(self.missing_concepts),
                "failure_reason_code": self.failure_reason_code,
                "authority": "none",
                "command_delivery_enabled": False,
            }
        )

    def mapped_concept_diagnostics(self) -> tuple[Mapping[str, Any], ...]:
        """Return deterministic, compact diagnostics for mapped concepts."""

        return tuple(
            MappingProxyType(
                {
                    "concept": item.observation_id,
                    "native_source_id": _compact_diagnostic_value(item.source_id),
                    "quality": item.quality.value,
                    "value_type": type(item.value).__name__,
                    "value": _compact_diagnostic_value(item.value),
                }
            )
            for item in self.observations
        )


NATIVE_TARGET_CONCEPTS = (
    "air.temperature",
    "heater.active",
    "jets.active",
    "pool.active",
    "pool.command_active",
    "pool.heating_demand_active",
    "pool.target_temperature",
    "pool.temperature",
    "pump.gpm",
    "pump.power",
    "pump.rpm",
    "slide.active",
    "solar.active",
    "solar.temperature",
    "solar_preferred.active",
    "spa.active",
    "spa.command_active",
    "spa.heating_demand_active",
    "spa.target_temperature",
    "spa.temperature",
    "water.temperature",
    "waterfall.active",
)


class NativeIntelliCenterReadAdapter:
    """Map immutable native read evidence into canonical observations."""

    def capture(
        self,
        source: NativeIntelliCenterReadSource,
        *,
        generated_at: datetime,
    ) -> NativeIntelliCenterObservationSnapshot:
        if generated_at.tzinfo is None or generated_at.utcoffset() is None:
            raise ValueError("generated_at must be timezone-aware")
        try:
            transport = source.read_snapshot()
        except NativeIntelliCenterReadError as exc:
            return self.unavailable(generated_at, reason_code=exc.reason_code)
        return self.map_snapshot(transport, generated_at=generated_at)

    def initializing(self, generated_at: datetime) -> NativeIntelliCenterObservationSnapshot:
        return NativeIntelliCenterObservationSnapshot(
            generated_at=generated_at,
            status=NativeIntelliCenterStatus.INITIALIZING,
            source_id=None,
            observations=(),
            missing_concepts=NATIVE_TARGET_CONCEPTS,
            failure_reason_code=None,
        )

    def unavailable(
        self, generated_at: datetime, *, reason_code: str
    ) -> NativeIntelliCenterObservationSnapshot:
        return NativeIntelliCenterObservationSnapshot(
            generated_at=generated_at,
            status=NativeIntelliCenterStatus.UNAVAILABLE,
            source_id=None,
            observations=(),
            missing_concepts=NATIVE_TARGET_CONCEPTS,
            failure_reason_code=reason_code.strip().upper(),
        )

    def map_snapshot(
        self,
        transport: NativeIntelliCenterTransportSnapshot,
        *,
        generated_at: datetime,
    ) -> NativeIntelliCenterObservationSnapshot:
        if not transport.connected:
            return self.unavailable(generated_at, reason_code="SOURCE_DISCONNECTED")
        values: dict[str, tuple[Any, str | None, str]] = {}

        pool = _body(transport.bodies, NativeBodyKind.POOL)
        spa = _body(transport.bodies, NativeBodyKind.SPA)
        _body_values(values, "pool", pool, transport.temperature_unit)
        _body_values(values, "spa", spa, transport.temperature_unit)

        pump = _primary_pump(transport.pumps)
        if pump is not None:
            _put(values, "pump.rpm", pump.rpm, "rpm", pump.native_id)
            _put(values, "pump.gpm", pump.gpm, "gpm", pump.native_id)
            _put(values, "pump.power", pump.power_watts, "W", pump.native_id)

        for kind, concept in (
            (NativeTemperatureKind.AIR, "air.temperature"),
            (NativeTemperatureKind.SOLAR, "solar.temperature"),
            (NativeTemperatureKind.WATER, "water.temperature"),
        ):
            sensor = _temperature(transport.temperatures, kind)
            if sensor is not None:
                _put(
                    values,
                    concept,
                    _canonical_temperature(
                        sensor.temperature, transport.temperature_unit
                    ),
                    "°F",
                    sensor.native_id,
                )

        circuits = tuple(sorted(transport.circuits, key=lambda item: item.native_id))
        for concept, aliases in _CIRCUIT_ALIASES.items():
            circuit = _circuit(circuits, aliases)
            if circuit is not None:
                _put(values, concept, circuit.active, None, circuit.native_id)

        bodies = tuple(item for item in (pool, spa) if item is not None)
        heater_active = _active_heat_source_value(bodies, expected_source="gas")
        solar_active = _active_heat_source_value(bodies, expected_source="solar")
        solar_preferred = _solar_preferred_value(bodies)
        _put(values, "heater.active", heater_active, None, "body-heat-source")
        _put(values, "solar.active", solar_active, None, "body-heat-source")
        _put(
            values,
            "solar_preferred.active",
            solar_preferred,
            None,
            "body-selected-heat-mode",
        )

        observations = tuple(
            PoolObservation(
                observation_id=concept,
                value=value,
                unit=unit,
                truth_level=TruthLevel.MEASURED,
                observed_at=transport.observed_at,
                source_kind=ObservationSourceKind.LIVE,
                source_id=f"intellicenter_native:{transport.source_id}:{native_id}",
                quality=ObservationQuality.GOOD,
                confidence=1.0,
            )
            for concept, (value, unit, native_id) in sorted(values.items())
        )
        present = {item.observation_id for item in observations}
        return NativeIntelliCenterObservationSnapshot(
            generated_at=generated_at,
            status=NativeIntelliCenterStatus.AVAILABLE,
            source_id=transport.source_id,
            observations=observations,
            missing_concepts=tuple(
                concept for concept in NATIVE_TARGET_CONCEPTS if concept not in present
            ),
        )


def _body(
    bodies: tuple[NativeBodyState, ...], kind: NativeBodyKind
) -> NativeBodyState | None:
    return next(
        (item for item in sorted(bodies, key=lambda body: body.native_id) if item.kind is kind),
        None,
    )


def _body_values(
    values: dict[str, tuple[Any, str | None, str]],
    prefix: str,
    body: NativeBodyState | None,
    temperature_unit: str,
) -> None:
    if body is None:
        return
    _put(values, f"{prefix}.active", body.active, None, body.native_id)
    _put(
        values,
        f"{prefix}.heating_demand_active",
        body.heating_active,
        None,
        body.native_id,
    )
    _put(
        values,
        f"{prefix}.temperature",
        _canonical_temperature(body.current_temperature, temperature_unit),
        "°F",
        body.native_id,
    )
    _put(
        values,
        f"{prefix}.target_temperature",
        _canonical_temperature(body.target_temperature, temperature_unit),
        "°F",
        body.native_id,
    )


def _primary_pump(pumps: tuple[NativePumpState, ...]) -> NativePumpState | None:
    ordered = tuple(sorted(pumps, key=lambda item: item.native_id))
    if len(ordered) == 1:
        return ordered[0]
    named = tuple(
        item
        for item in ordered
        if any(token in item.name.casefold() for token in ("filter", "main", "circulation"))
    )
    if len(named) == 1:
        return named[0]
    running = tuple(item for item in ordered if item.running)
    return running[0] if len(running) == 1 else None


def _active_heat_source_value(
    bodies: tuple[NativeBodyState, ...], *, expected_source: str
) -> bool | None:
    active = tuple(body for body in bodies if body.heating_active)
    if not active:
        return False if bodies else None
    sources = tuple(_normalized_token(body.active_heat_source) for body in active)
    if any(source in {None, "unknown"} for source in sources):
        return None
    return expected_source in sources


def _solar_preferred_value(bodies: tuple[NativeBodyState, ...]) -> bool | None:
    modes = tuple(
        mode
        for body in bodies
        if (mode := _normalized_token(body.selected_heat_mode)) not in {None, "unknown"}
    )
    if not modes:
        return None
    return "solar preferred" in modes


def _normalized_token(value: str | None) -> str | None:
    if value is None:
        return None
    return " ".join(value.strip().casefold().replace("_", " ").replace("-", " ").split())


def _temperature(
    temperatures: tuple[NativeTemperatureState, ...], kind: NativeTemperatureKind
) -> NativeTemperatureState | None:
    candidates = tuple(
        item
        for item in sorted(temperatures, key=lambda sensor: sensor.native_id)
        if item.kind is kind
    )
    if len(candidates) == 1:
        return candidates[0]
    exact = tuple(item for item in candidates if item.name.strip().casefold() == kind.value)
    return exact[0] if len(exact) == 1 else None


_CIRCUIT_ALIASES: Mapping[str, frozenset[str]] = MappingProxyType(
    {
        "pool.command_active": frozenset({"pool", "pool circuit"}),
        "spa.command_active": frozenset({"spa", "spa circuit"}),
        "solar.active": frozenset({"solar", "solar heat"}),
        "solar_preferred.active": frozenset({"solar preferred", "solarpref"}),
        "waterfall.active": frozenset({"waterfall", "water fall"}),
        "jets.active": frozenset({"jets", "spa jets"}),
        "slide.active": frozenset({"slide", "pool slide"}),
    }
)


def _circuit(
    circuits: tuple[NativeCircuitState, ...], aliases: frozenset[str]
) -> NativeCircuitState | None:
    for circuit in circuits:
        candidates = (circuit.name, circuit.use, circuit.subtype)
        normalized = {
            " ".join(
                str(value).strip().casefold().replace("_", " ").replace("-", " ").split()
            )
            for value in candidates
            if value
        }
        if normalized.intersection(aliases):
            return circuit
    return None


def _put(
    values: dict[str, tuple[Any, str | None, str]],
    concept: str,
    value: Any,
    unit: str | None,
    native_id: str,
) -> None:
    if value is not None:
        values[concept] = (value, unit, native_id)


def _canonical_temperature(value: float | None, unit: str) -> float | None:
    if value is None:
        return None
    normalized = unit.strip().casefold()
    if normalized in {"°c", "c", "celsius"}:
        return round(value * 9.0 / 5.0 + 32.0, 3)
    return value


def _compact_diagnostic_value(value: Any) -> Any:
    if isinstance(value, str):
        return value[:64]
    if isinstance(value, (bool, int, float)) or value is None:
        return value
    return str(value)[:64]


__all__ = [
    "NATIVE_ADAPTER_ID",
    "NATIVE_TARGET_CONCEPTS",
    "NativeBodyKind",
    "NativeBodyState",
    "NativeCircuitState",
    "NativeIntelliCenterObservationSnapshot",
    "NativeIntelliCenterReadAdapter",
    "NativeIntelliCenterReadError",
    "NativeIntelliCenterReadSource",
    "NativeIntelliCenterStatus",
    "NativeIntelliCenterTransportSnapshot",
    "NativePumpState",
    "NativeTemperatureKind",
    "NativeTemperatureState",
]
