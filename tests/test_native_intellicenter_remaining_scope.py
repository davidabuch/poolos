"""Intentional product boundary for remaining native IntelliCenter parity."""

from __future__ import annotations

from pathlib import Path

from poolos.intellicenter_readonly import (
    INTELLICENTER_PARITY_ELIGIBLE_CONCEPTS,
    NATIVE_TARGET_CONCEPTS,
)

ROOT = Path(__file__).resolve().parents[1]
COMPONENT = ROOT / "custom_components" / "poolos"


def test_remaining_concepts_are_parity_eligible_without_super_chlorinate() -> None:
    expected = {
        "freeze.active",
        "intellicenter.firmware_version",
        "intellicenter.system_mode",
        "intellichlor.pool_output_percent",
        "intellichlor.salt_ppm",
        "intellichlor.spa_output_percent",
        "pool.maximum_temperature",
        "pump.maximum_rpm",
        "pump.minimum_rpm",
        "spa.maximum_temperature",
    }

    assert expected <= set(NATIVE_TARGET_CONCEPTS)
    assert expected <= INTELLICENTER_PARITY_ELIGIBLE_CONCEPTS
    assert not any("super" in concept.casefold() for concept in NATIVE_TARGET_CONCEPTS)


def test_optional_legacy_mappings_cover_only_supported_parity_inputs() -> None:
    const = (COMPONENT / "const.py").read_text(encoding="utf-8")
    flow = (COMPONENT / "config_flow.py").read_text(encoding="utf-8")
    observation = (COMPONENT / "observation.py").read_text(encoding="utf-8")

    for token in (
        "CONF_INTELLICHLOR_SALT_ENTITY",
        "CONF_INTELLICHLOR_POOL_OUTPUT_ENTITY",
        "CONF_INTELLICHLOR_SPA_OUTPUT_ENTITY",
        "CONF_FREEZE_ACTIVE_ENTITY",
        "CONF_FIRMWARE_VERSION_ENTITY",
        "CONF_SYSTEM_MODE_ENTITY",
        "CONF_POOL_MAXIMUM_TEMPERATURE_ENTITY",
        "CONF_SPA_MAXIMUM_TEMPERATURE_ENTITY",
        "CONF_PUMP_MINIMUM_RPM_ENTITY",
        "CONF_PUMP_MAXIMUM_RPM_ENTITY",
    ):
        assert token in const
        assert token in flow
        assert token in observation

    combined = (const + flow + observation).casefold()
    assert "super_chlor" not in combined
    assert "superchlor" not in combined


def test_intellichlor_sensors_remain_and_only_output_numbers_are_writable() -> None:
    sensor = (COMPONENT / "sensor.py").read_text(encoding="utf-8")
    binary_sensor = (COMPONENT / "binary_sensor.py").read_text(encoding="utf-8")
    number = (COMPONENT / "number.py").read_text(encoding="utf-8")
    switch = (COMPONENT / "switch.py").read_text(encoding="utf-8")
    manual = (COMPONENT / "manual_intellicenter.py").read_text(encoding="utf-8")

    assert "intellichlor" in sensor.casefold()
    assert '"freeze.active"' in binary_sensor
    assert "intellichlor" in number.casefold()
    assert "intellichlor" not in switch.casefold()
    assert "async_set_intellichlor_output" in manual
    assert "set_chlorinator_output" in manual
    assert "superchlor" not in manual.casefold()


def test_intentionally_unmigrated_legacy_product_surfaces_remain_absent() -> None:
    native_surface = "\n".join(
        (COMPONENT / name).read_text(encoding="utf-8").casefold()
        for name in ("sensor.py", "binary_sensor.py", "number.py", "switch.py")
    )

    for forbidden in (
        "vacation_mode",
        "schedule_pool",
        "rpm_heater",
        "rpm_high_speed",
        "rpm_solar",
        "rpm_spa",
        "rpm_waterfall",
        "hxslr",
        "pool_last_temp",
        "spa_last_temp",
        "water_sensor",
        "air_sensor",
        "solar_sensor",
        "intellichlor_super",
    ):
        assert forbidden not in native_surface

    number = (COMPONENT / "number.py").read_text(encoding="utf-8")
    assert "PoolOSNativeIntelliCenterPoolRPM" in number
    assert "PoolOSNativeIntelliCenterIntelliChlorOutput" in number


def test_transport_retains_super_only_as_raw_forensic_inventory() -> None:
    transport = (COMPONENT / "independent_intellicenter.py").read_text(
        encoding="utf-8"
    )
    canonical = (ROOT / "poolos" / "intellicenter_readonly.py").read_text(
        encoding="utf-8"
    )

    assert "SUPER_ATTR" not in transport
    assert "superchlor" not in canonical.casefold()
    assert "super_chlor" not in canonical.casefold()
    assert "raw_inventory=raw" in transport
