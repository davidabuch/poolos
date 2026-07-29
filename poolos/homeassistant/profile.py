"""Typed, versioned installation and Home Assistant binding profiles."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from types import MappingProxyType
from typing import Any, Mapping

import yaml

SCHEMA_VERSION = 1


class InstallationProfileError(ValueError):
    """Raised when an installation profile is malformed or inconsistent."""


def _required_string(value: object, path: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise InstallationProfileError(f"{path} must be a non-empty string")
    return value.strip()


def _mapping(value: object, path: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise InstallationProfileError(f"{path} must be a mapping")
    return value


def _entity_id(value: object, path: str, *, domains: set[str]) -> str:
    entity_id = _required_string(value, path).lower()
    if "." not in entity_id:
        raise InstallationProfileError(f"{path} must be a Home Assistant entity ID")
    domain, object_id = entity_id.split(".", 1)
    if domain not in domains:
        expected = ", ".join(sorted(domains))
        raise InstallationProfileError(f"{path} must use one of these domains: {expected}")
    if not object_id or any(character.isspace() for character in object_id):
        raise InstallationProfileError(f"{path} has an invalid object ID")
    return entity_id


@dataclass(frozen=True, slots=True)
class PumpInstallation:
    """Physical pump definition independent of any automation platform."""

    equipment_id: str
    minimum_rpm: int
    maximum_rpm: int

    def __post_init__(self) -> None:
        object.__setattr__(self, "equipment_id", _required_string(self.equipment_id, "equipment_id"))
        if self.minimum_rpm <= 0:
            raise InstallationProfileError("minimum_rpm must be greater than zero")
        if self.maximum_rpm <= self.minimum_rpm:
            raise InstallationProfileError("maximum_rpm must be greater than minimum_rpm")


@dataclass(frozen=True, slots=True)
class PoolInstallationProfile:
    """Physical pool installation model."""

    pumps: Mapping[str, PumpInstallation]

    def __post_init__(self) -> None:
        copied = dict(self.pumps)
        if not copied:
            raise InstallationProfileError("installation.pumps must not be empty")
        for key, pump in copied.items():
            if key != pump.equipment_id:
                raise InstallationProfileError(
                    f"pump key {key!r} does not match equipment_id {pump.equipment_id!r}"
                )
        object.__setattr__(self, "pumps", MappingProxyType(copied))


@dataclass(frozen=True, slots=True)
class PumpHomeAssistantBinding:
    """Home Assistant entities used to command and observe one pump."""

    equipment_id: str
    running_entity: str
    speed_command_entity: str
    rpm_sensor_entity: str

    def __post_init__(self) -> None:
        object.__setattr__(self, "equipment_id", _required_string(self.equipment_id, "equipment_id"))
        object.__setattr__(
            self,
            "running_entity",
            _entity_id(self.running_entity, "running_entity", domains={"switch"}),
        )
        object.__setattr__(
            self,
            "speed_command_entity",
            _entity_id(
                self.speed_command_entity,
                "speed_command_entity",
                domains={"number", "input_number"},
            ),
        )
        object.__setattr__(
            self,
            "rpm_sensor_entity",
            _entity_id(self.rpm_sensor_entity, "rpm_sensor_entity", domains={"sensor"}),
        )


@dataclass(frozen=True, slots=True)
class HydraulicRouteBinding:
    """Home Assistant select entity and option mapping for hydraulic routes."""

    equipment_id: str
    route_entity: str
    options: Mapping[str, str]

    def __post_init__(self) -> None:
        object.__setattr__(self, "equipment_id", _required_string(self.equipment_id, "equipment_id"))
        object.__setattr__(
            self,
            "route_entity",
            _entity_id(self.route_entity, "route_entity", domains={"select", "input_select"}),
        )
        copied: dict[str, str] = {}
        for key, value in self.options.items():
            route_key = _required_string(key, "route option key")
            if ":" not in route_key:
                raise InstallationProfileError(
                    "route option keys must use '<suction_body_id>:<return_body_id>'"
                )
            copied[route_key] = _required_string(value, f"route option {route_key}")
        if not copied:
            raise InstallationProfileError("hydraulic route options must not be empty")
        object.__setattr__(self, "options", MappingProxyType(copied))


@dataclass(frozen=True, slots=True)
class EnergyObservationBindings:
    """Reserved external energy observations; no control behavior is implied."""

    grid_status_entity: str | None = None

    def __post_init__(self) -> None:
        if self.grid_status_entity is not None:
            object.__setattr__(
                self,
                "grid_status_entity",
                _entity_id(
                    self.grid_status_entity,
                    "grid_status_entity",
                    domains={"binary_sensor", "sensor"},
                ),
            )


@dataclass(frozen=True, slots=True)
class HomeAssistantBindingProfile:
    """Home Assistant bindings separated from the physical installation."""

    pumps: Mapping[str, PumpHomeAssistantBinding]
    hydraulic_routes: Mapping[str, HydraulicRouteBinding] = field(default_factory=dict)
    energy: EnergyObservationBindings = field(default_factory=EnergyObservationBindings)

    def __post_init__(self) -> None:
        pumps = dict(self.pumps)
        routes = dict(self.hydraulic_routes)
        for key, pump_binding in pumps.items():
            if key != pump_binding.equipment_id:
                raise InstallationProfileError(
                    f"pump binding key {key!r} does not match equipment_id "
                    f"{pump_binding.equipment_id!r}"
                )
        for key, route_binding in routes.items():
            if key != route_binding.equipment_id:
                raise InstallationProfileError(
                    f"route binding key {key!r} does not match equipment_id "
                    f"{route_binding.equipment_id!r}"
                )
        object.__setattr__(self, "pumps", MappingProxyType(pumps))
        object.__setattr__(self, "hydraulic_routes", MappingProxyType(routes))


@dataclass(frozen=True, slots=True)
class SiteProfile:
    """Complete versioned site profile."""

    schema_version: int
    installation: PoolInstallationProfile
    home_assistant: HomeAssistantBindingProfile

    def __post_init__(self) -> None:
        if self.schema_version != SCHEMA_VERSION:
            raise InstallationProfileError(
                f"unsupported schema_version {self.schema_version}; expected {SCHEMA_VERSION}"
            )
        installation_ids = set(self.installation.pumps)
        binding_ids = set(self.home_assistant.pumps)
        missing = installation_ids - binding_ids
        unknown = binding_ids - installation_ids
        if missing:
            raise InstallationProfileError(
                "missing Home Assistant pump bindings for: " + ", ".join(sorted(missing))
            )
        if unknown:
            raise InstallationProfileError(
                "Home Assistant pump bindings reference unknown pumps: "
                + ", ".join(sorted(unknown))
            )


def load_site_profile(path: str | Path) -> SiteProfile:
    """Load and validate a versioned YAML site profile."""

    profile_path = Path(path)
    try:
        raw = yaml.safe_load(profile_path.read_text(encoding="utf-8"))
    except OSError as exc:
        raise InstallationProfileError(f"unable to read profile {profile_path}: {exc}") from exc
    except yaml.YAMLError as exc:
        raise InstallationProfileError(f"invalid YAML in profile {profile_path}: {exc}") from exc

    root = _mapping(raw, "profile")
    schema_version = root.get("schema_version")
    if not isinstance(schema_version, int):
        raise InstallationProfileError("schema_version must be an integer")

    installation_raw = _mapping(root.get("installation"), "installation")
    pumps_raw = _mapping(installation_raw.get("pumps"), "installation.pumps")
    pumps: dict[str, PumpInstallation] = {}
    for equipment_id, item in pumps_raw.items():
        pump_raw = _mapping(item, f"installation.pumps.{equipment_id}")
        pumps[str(equipment_id)] = PumpInstallation(
            equipment_id=str(equipment_id),
            minimum_rpm=_required_int(
                pump_raw.get("minimum_rpm"),
                f"installation.pumps.{equipment_id}.minimum_rpm",
            ),
            maximum_rpm=_required_int(
                pump_raw.get("maximum_rpm"),
                f"installation.pumps.{equipment_id}.maximum_rpm",
            ),
        )

    bindings_raw = _mapping(root.get("home_assistant"), "home_assistant")
    pool_raw = _mapping(bindings_raw.get("pool"), "home_assistant.pool")
    pump_bindings_raw = _mapping(pool_raw.get("pumps"), "home_assistant.pool.pumps")
    pump_bindings: dict[str, PumpHomeAssistantBinding] = {}
    for equipment_id, item in pump_bindings_raw.items():
        binding_raw = _mapping(item, f"home_assistant.pool.pumps.{equipment_id}")
        pump_bindings[str(equipment_id)] = PumpHomeAssistantBinding(
            equipment_id=str(equipment_id),
            running_entity=_required_string(
                binding_raw.get("running_entity"),
                f"home_assistant.pool.pumps.{equipment_id}.running_entity",
            ),
            speed_command_entity=_required_string(
                binding_raw.get("speed_command_entity"),
                f"home_assistant.pool.pumps.{equipment_id}.speed_command_entity",
            ),
            rpm_sensor_entity=_required_string(
                binding_raw.get("rpm_sensor_entity"),
                f"home_assistant.pool.pumps.{equipment_id}.rpm_sensor_entity",
            ),
        )

    route_bindings: dict[str, HydraulicRouteBinding] = {}
    route_bindings_raw = pool_raw.get("hydraulic_routes", {})
    for equipment_id, item in _mapping(
        route_bindings_raw, "home_assistant.pool.hydraulic_routes"
    ).items():
        binding_raw = _mapping(item, f"home_assistant.pool.hydraulic_routes.{equipment_id}")
        options_raw = _mapping(
            binding_raw.get("options"),
            f"home_assistant.pool.hydraulic_routes.{equipment_id}.options",
        )
        route_bindings[str(equipment_id)] = HydraulicRouteBinding(
            equipment_id=str(equipment_id),
            route_entity=_required_string(
                binding_raw.get("route_entity"),
                f"home_assistant.pool.hydraulic_routes.{equipment_id}.route_entity",
            ),
            options={str(key): _required_string(value, f"route option {key}") for key, value in options_raw.items()},
        )

    external_raw = _mapping(bindings_raw.get("external_systems", {}), "home_assistant.external_systems")
    energy_raw = _mapping(external_raw.get("energy", {}), "home_assistant.external_systems.energy")
    energy = EnergyObservationBindings(grid_status_entity=energy_raw.get("grid_status_entity"))

    return SiteProfile(
        schema_version=schema_version,
        installation=PoolInstallationProfile(pumps=pumps),
        home_assistant=HomeAssistantBindingProfile(
            pumps=pump_bindings,
            hydraulic_routes=route_bindings,
            energy=energy,
        ),
    )


def _required_int(value: object, path: str) -> int:
    if not isinstance(value, int) or isinstance(value, bool):
        raise InstallationProfileError(f"{path} must be an integer")
    return value
