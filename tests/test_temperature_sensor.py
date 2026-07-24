"""Tests for immutable physical temperature-probe snapshots."""

from homeassistant.const import UnitOfTemperature


def test_temperature_probe_is_included_in_snapshot(
    api_modules, temperature_sensor_object_factory, coordinator_factory
):
    probe = temperature_sensor_object_factory(temperature="74.5")
    coordinator = coordinator_factory([probe])

    api = api_modules.system.IntelliCenterAPI(coordinator)
    snapshot = api.refresh()

    assert snapshot.temperature_unit is UnitOfTemperature.FAHRENHEIT
    assert len(snapshot.temperature_sensors) == 1
    state = snapshot.temperature_sensors[0]
    assert state.id == "S0001"
    assert state.name == "Air Temperature"
    assert state.sensor_type is api_modules.models.TemperatureSensorType.AIR
    assert state.temperature == 74.5
    assert api.temperature_sensor("S0001") is state


def test_invalid_temperature_probe_value_is_contained(
    api_modules, temperature_sensor_object_factory, coordinator_factory
):
    probe = temperature_sensor_object_factory(temperature="not-a-number")
    coordinator = coordinator_factory([probe])

    state = api_modules.temperature.build_temperature_sensor_state(probe)

    assert state.temperature is None


def test_temperature_probe_type_falls_back_to_name(
    api_modules, temperature_sensor_object_factory
):
    probe = temperature_sensor_object_factory(
        name="Solar Sensor", subtype=None, temperature=110
    )

    state = api_modules.temperature.build_temperature_sensor_state(probe)

    assert state.sensor_type is api_modules.models.TemperatureSensorType.SOLAR
