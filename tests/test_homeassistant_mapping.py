from __future__ import annotations

from pathlib import Path

import pytest

from poolos.delivery import PentairCommandRequest
from poolos.homeassistant import (
    HomeAssistantMappingError,
    PentairHomeAssistantCommandMapper,
    load_site_profile,
)


PROFILE = """
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
"""


def mapper(tmp_path: Path) -> PentairHomeAssistantCommandMapper:
    path = tmp_path / "profile.yaml"
    path.write_text(PROFILE, encoding="utf-8")
    profile = load_site_profile(path)
    return PentairHomeAssistantCommandMapper(
        installation=profile.installation,
        bindings=profile.home_assistant,
    )


def request(operation: str, *, target: str = "filter-pump", parameters=None):
    return PentairCommandRequest(
        operation=operation,
        target=target,
        parameters=parameters or {},
        correlation_id="correlation-123",
    )


def test_maps_pump_speed_to_number_service(tmp_path: Path) -> None:
    call = mapper(tmp_path).map_command(
        request("pump.set_speed", parameters={"rpm": 2200})
    )

    assert call.domain == "number"
    assert call.service == "set_value"
    assert call.target == {"entity_id": "number.pool_filter_pump_speed"}
    assert call.data == {"value": 2200}
    assert call.context == {"correlation_id": "correlation-123"}


@pytest.mark.parametrize(
    ("operation", "service"),
    [("pump.start", "turn_on"), ("pump.stop", "turn_off")],
)
def test_maps_pump_start_stop_to_switch_services(
    tmp_path: Path,
    operation: str,
    service: str,
) -> None:
    call = mapper(tmp_path).map_command(request(operation))

    assert call.domain == "switch"
    assert call.service == service
    assert call.target == {"entity_id": "switch.pool_filter_pump"}


def test_maps_hydraulic_route_to_select_option(tmp_path: Path) -> None:
    call = mapper(tmp_path).map_command(
        request(
            "hydraulics.set_route",
            target="shared-pool-spa",
            parameters={"suction_body_id": "spa", "return_body_id": "spa"},
        )
    )

    assert call.domain == "select"
    assert call.service == "select_option"
    assert call.target == {"entity_id": "select.pool_hydraulic_route"}
    assert call.data == {"option": "Spa"}


@pytest.mark.parametrize("rpm", [449, 3451])
def test_rejects_speed_outside_profile_range(tmp_path: Path, rpm: int) -> None:
    with pytest.raises(HomeAssistantMappingError, match="outside configured range"):
        mapper(tmp_path).map_command(
            request("pump.set_speed", parameters={"rpm": rpm})
        )


def test_rejects_unknown_pump(tmp_path: Path) -> None:
    with pytest.raises(HomeAssistantMappingError, match="unknown pump"):
        mapper(tmp_path).map_command(request("pump.start", target="booster-pump"))


def test_rejects_unknown_hydraulic_route(tmp_path: Path) -> None:
    with pytest.raises(HomeAssistantMappingError, match="no Home Assistant option"):
        mapper(tmp_path).map_command(
            request(
                "hydraulics.set_route",
                target="shared-pool-spa",
                parameters={"suction_body_id": "pool", "return_body_id": "spa"},
            )
        )


def test_rejects_unknown_operation(tmp_path: Path) -> None:
    with pytest.raises(HomeAssistantMappingError, match="unsupported Pentair operation"):
        mapper(tmp_path).map_command(request("heater.explode"))
