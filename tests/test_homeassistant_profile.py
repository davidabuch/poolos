from __future__ import annotations

from pathlib import Path

import pytest

from poolos.homeassistant import InstallationProfileError, load_site_profile


VALID_PROFILE = """
schema_version: 1
installation:
  pumps:
    filter-pump:
      minimum_rpm: 450
      maximum_rpm: 3450
home_assistant:
  pool:
    pumps:
      filter-pump:
        running_entity: switch.pool_filter_pump
        speed_command_entity: number.pool_filter_pump_speed
        rpm_sensor_entity: sensor.buch_family_vs_rpm
    hydraulic_routes:
      shared-pool-spa:
        route_entity: select.pool_hydraulic_route
        options:
          pool:pool: Pool
          spa:spa: Spa
  external_systems:
    energy:
      grid_status_entity: binary_sensor.powerwall_grid_status
"""


def write_profile(tmp_path: Path, content: str = VALID_PROFILE) -> Path:
    path = tmp_path / "installation.yaml"
    path.write_text(content, encoding="utf-8")
    return path


def test_loads_typed_physical_and_home_assistant_profiles(tmp_path: Path) -> None:
    profile = load_site_profile(write_profile(tmp_path))

    pump = profile.installation.pumps["filter-pump"]
    binding = profile.home_assistant.pumps["filter-pump"]
    assert pump.minimum_rpm == 450
    assert pump.maximum_rpm == 3450
    assert binding.running_entity == "switch.pool_filter_pump"
    assert binding.rpm_sensor_entity == "sensor.buch_family_vs_rpm"
    assert profile.home_assistant.energy.grid_status_entity == (
        "binary_sensor.powerwall_grid_status"
    )


def test_loaded_profile_mappings_are_immutable(tmp_path: Path) -> None:
    profile = load_site_profile(write_profile(tmp_path))

    with pytest.raises(TypeError):
        profile.installation.pumps["other"] = profile.installation.pumps["filter-pump"]  # type: ignore[index]
    with pytest.raises(TypeError):
        profile.home_assistant.hydraulic_routes["shared-pool-spa"].options["x:y"] = "X"  # type: ignore[index]


@pytest.mark.parametrize("schema_version", [0, 2])
def test_rejects_unsupported_schema_version(tmp_path: Path, schema_version: int) -> None:
    content = VALID_PROFILE.replace("schema_version: 1", f"schema_version: {schema_version}")

    with pytest.raises(InstallationProfileError, match="unsupported schema_version"):
        load_site_profile(write_profile(tmp_path, content))


def test_requires_binding_for_every_physical_pump(tmp_path: Path) -> None:
    content = VALID_PROFILE.replace(
        "  pool:\n    pumps:\n      filter-pump:\n        running_entity: switch.pool_filter_pump\n        speed_command_entity: number.pool_filter_pump_speed\n        rpm_sensor_entity: sensor.buch_family_vs_rpm\n",
        "  pool:\n    pumps: {}\n",
    )

    with pytest.raises(InstallationProfileError, match="missing Home Assistant pump bindings"):
        load_site_profile(write_profile(tmp_path, content))


@pytest.mark.parametrize(
    ("old", "new", "message"),
    [
        ("switch.pool_filter_pump", "sensor.pool_filter_pump", "running_entity"),
        ("number.pool_filter_pump_speed", "sensor.pool_speed", "speed_command_entity"),
        ("sensor.buch_family_vs_rpm", "number.pool_rpm", "rpm_sensor_entity"),
        ("binary_sensor.powerwall_grid_status", "switch.powerwall_grid", "grid_status_entity"),
    ],
)
def test_rejects_incompatible_entity_domains(
    tmp_path: Path,
    old: str,
    new: str,
    message: str,
) -> None:
    with pytest.raises(InstallationProfileError, match=message):
        load_site_profile(write_profile(tmp_path, VALID_PROFILE.replace(old, new)))


def test_rejects_invalid_rpm_range(tmp_path: Path) -> None:
    content = VALID_PROFILE.replace("maximum_rpm: 3450", "maximum_rpm: 400")

    with pytest.raises(InstallationProfileError, match="maximum_rpm"):
        load_site_profile(write_profile(tmp_path, content))


def test_rejects_malformed_yaml(tmp_path: Path) -> None:
    with pytest.raises(InstallationProfileError, match="invalid YAML"):
        load_site_profile(write_profile(tmp_path, "schema_version: ["))
