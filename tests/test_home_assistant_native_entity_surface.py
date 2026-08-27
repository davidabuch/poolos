"""Contracts for the PoolOS native IntelliCenter HA entity surface."""

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
COMPONENT = ROOT / "custom_components" / "poolos"


def test_poolos_loads_binary_sensor_platform() -> None:
    const_text = (COMPONENT / "const.py").read_text(encoding="utf-8")
    assert 'PLATFORMS = ("sensor", "binary_sensor", "button", "climate", "switch", "light", "number", "select")' in const_text


def test_native_sensor_surface_uses_independent_snapshot() -> None:
    sensor_text = (COMPONENT / "sensor.py").read_text(encoding="utf-8")

    assert "class PoolOSNativeIntelliCenterSensor" in sensor_text
    assert "coordinator.native_intellicenter_snapshot" in sensor_text
    assert '"source": "poolos.independent_intellicenter"' in sensor_text
    assert '"PoolOS Native IntelliCenter"' in sensor_text


def test_native_binary_sensor_surface_uses_independent_snapshot() -> None:
    binary_text = (COMPONENT / "binary_sensor.py").read_text(encoding="utf-8")

    assert "class PoolOSNativeIntelliCenterBinarySensor" in binary_text
    assert "coordinator.native_intellicenter_snapshot" in binary_text
    assert '"source": "poolos.independent_intellicenter"' in binary_text
    assert '"PoolOS Native IntelliCenter"' in binary_text


def test_native_surface_exposes_all_26_canonical_concepts_once() -> None:
    sensor_text = (COMPONENT / "sensor.py").read_text(encoding="utf-8")
    binary_text = (COMPONENT / "binary_sensor.py").read_text(encoding="utf-8")

    sensor_block = sensor_text.split(
        "NATIVE_SENSORS: tuple[PoolOSNativeSensorDescription, ...] = (",
        1,
    )[1].split(
        "class PoolOSNativeIntelliCenterSensor",
        1,
    )[0]

    binary_block = binary_text.split(
        "NATIVE_BINARY_SENSORS: tuple[PoolOSNativeBinarySensorDescription, ...] = (",
        1,
    )[1].split(
        "def _native_observation",
        1,
    )[0]

    concepts = {
        "air.temperature",
        "heater.active",
        "jets.active",
        "pool.active",
        "pool.command_active",
        "pool.heating_demand_active",
        "pool.raw_heater_id",
        "pool.raw_htmode",
        "pool.target_temperature",
        "pool.temperature",
        "pool_light.active",
        "pump.gpm",
        "pump.power",
        "pump.rpm",
        "slide.active",
        "solar.active",
        "solar.temperature",
        "spa.active",
        "spa.command_active",
        "spa.heating_demand_active",
        "spa.raw_heater_id",
        "spa.raw_htmode",
        "spa.target_temperature",
        "spa.temperature",
        "water.temperature",
        "waterfall.active",
    }

    native_blocks = sensor_block + binary_block

    for concept in concepts:
        assert native_blocks.count(f'"{concept}"') == 1

    assert sensor_block.count("PoolOSNativeSensorDescription(") == 14
    assert binary_block.count("PoolOSNativeBinarySensorDescription(") == 12


def test_native_entity_names_do_not_duplicate_device_name() -> None:
    sensor_text = (COMPONENT / "sensor.py").read_text(encoding="utf-8")
    binary_text = (COMPONENT / "binary_sensor.py").read_text(encoding="utf-8")

    assert "self._attr_name = description.name" in sensor_text
    assert "self._attr_name = description.name" in binary_text
    assert 'self._attr_name = f"Native IntelliCenter {description.name}"' not in sensor_text
    assert 'self._attr_name = f"Native IntelliCenter {description.name}"' not in binary_text


def test_native_surface_remains_read_only() -> None:
    sensor_text = (COMPONENT / "sensor.py").read_text(encoding="utf-8")
    binary_text = (COMPONENT / "binary_sensor.py").read_text(encoding="utf-8")

    combined = sensor_text + binary_text

    assert '"command_delivery_enabled": False' in combined
    assert '"read_only": True' in combined
    assert "async_turn_on" not in binary_text
    assert "async_turn_off" not in binary_text
