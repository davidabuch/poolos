"""Constants for the PoolOS Home Assistant integration."""

from __future__ import annotations

from datetime import timedelta

DOMAIN = "poolos"
NAME = "PoolOS"
INTEGRATION_VERSION = "0.10.0"

CONF_DIAGNOSTICS_ENABLED = "diagnostics_enabled"
DEFAULT_DIAGNOSTICS_ENABLED = True
CONF_INTELLICENTER_HOST = "intellicenter_host"
CONF_INTELLICENTER_TRANSPORT = "intellicenter_transport"
DEFAULT_INTELLICENTER_TRANSPORT = "tcp"
INTELLICENTER_TRANSPORT_OPTIONS = ("tcp", "websocket")

# High-fidelity observation sources.  Pool/spa thermostat entities are reused for
# several attribute-level observations; no template sensors are required.
CONF_POOL_THERMOSTAT_ENTITY = "pool_thermostat_entity"
CONF_SPA_THERMOSTAT_ENTITY = "spa_thermostat_entity"
CONF_PUMP_RPM_ENTITY = "pump_rpm_entity"
CONF_PUMP_GPM_ENTITY = "pump_gpm_entity"
CONF_PUMP_POWER_ENTITY = "pump_power_entity"
CONF_WATER_TEMPERATURE_ENTITY = "water_temperature_entity"
CONF_SOLAR_TEMPERATURE_ENTITY = "solar_temperature_entity"
CONF_AIR_TEMPERATURE_ENTITY = "air_temperature_entity"
CONF_SOLAR_ACTIVE_ENTITY = "solar_active_entity"
CONF_HEATER_ACTIVE_ENTITY = "heater_active_entity"
CONF_POOL_COMMAND_ENTITY = "pool_command_entity"
CONF_SPA_COMMAND_ENTITY = "spa_command_entity"
CONF_WATERFALL_ACTIVE_ENTITY = "waterfall_active_entity"
CONF_JETS_ACTIVE_ENTITY = "jets_active_entity"
CONF_SLIDE_ACTIVE_ENTITY = "slide_active_entity"
CONF_GRID_STATUS_ENTITY = "grid_status_entity"
CONF_POOL_LIGHT_ENTITY = "pool_light_entity"
CONF_INTELLICHLOR_SALT_ENTITY = "intellichlor_salt_entity"
CONF_INTELLICHLOR_POOL_OUTPUT_ENTITY = "intellichlor_pool_output_entity"
CONF_INTELLICHLOR_SPA_OUTPUT_ENTITY = "intellichlor_spa_output_entity"
CONF_FREEZE_ACTIVE_ENTITY = "freeze_active_entity"
CONF_FIRMWARE_VERSION_ENTITY = "firmware_version_entity"
CONF_SYSTEM_MODE_ENTITY = "system_mode_entity"
CONF_POOL_MAXIMUM_TEMPERATURE_ENTITY = "pool_maximum_temperature_entity"
CONF_SPA_MAXIMUM_TEMPERATURE_ENTITY = "spa_maximum_temperature_entity"
CONF_PUMP_MINIMUM_RPM_ENTITY = "pump_minimum_rpm_entity"
CONF_PUMP_MAXIMUM_RPM_ENTITY = "pump_maximum_rpm_entity"

# C5.9 native-authoritative contract:
# Home Assistant is authoritative only for genuinely external observations.
# IntelliCenter-owned controller mappings remain optional parity-shadow inputs.
REQUIRED_ENTITY_OPTIONS = (
    CONF_GRID_STATUS_ENTITY,
)
OPTIONAL_ENTITY_OPTIONS = (
    CONF_POOL_THERMOSTAT_ENTITY,
    CONF_SPA_THERMOSTAT_ENTITY,
    CONF_PUMP_RPM_ENTITY,
    CONF_PUMP_GPM_ENTITY,
    CONF_PUMP_POWER_ENTITY,
    CONF_WATER_TEMPERATURE_ENTITY,
    CONF_SOLAR_TEMPERATURE_ENTITY,
    CONF_AIR_TEMPERATURE_ENTITY,
    CONF_SOLAR_ACTIVE_ENTITY,
    CONF_HEATER_ACTIVE_ENTITY,
    CONF_POOL_COMMAND_ENTITY,
    CONF_SPA_COMMAND_ENTITY,
    CONF_WATERFALL_ACTIVE_ENTITY,
    CONF_JETS_ACTIVE_ENTITY,
    CONF_SLIDE_ACTIVE_ENTITY,
    CONF_POOL_LIGHT_ENTITY,
    CONF_INTELLICHLOR_SALT_ENTITY,
    CONF_INTELLICHLOR_POOL_OUTPUT_ENTITY,
    CONF_INTELLICHLOR_SPA_OUTPUT_ENTITY,
    CONF_FREEZE_ACTIVE_ENTITY,
    CONF_FIRMWARE_VERSION_ENTITY,
    CONF_SYSTEM_MODE_ENTITY,
    CONF_POOL_MAXIMUM_TEMPERATURE_ENTITY,
    CONF_SPA_MAXIMUM_TEMPERATURE_ENTITY,
    CONF_PUMP_MINIMUM_RPM_ENTITY,
    CONF_PUMP_MAXIMUM_RPM_ENTITY,
)
ALL_ENTITY_OPTIONS = REQUIRED_ENTITY_OPTIONS + OPTIONAL_ENTITY_OPTIONS

# Periodic reconciliation is a resilience/backstop mechanism.  Relevant HA
# state-change events are observed immediately between reconciliation passes.
OBSERVATION_UPDATE_INTERVAL = timedelta(seconds=30)
OBSERVATION_STALE_AFTER = timedelta(minutes=5)
STARTUP_HEALTH_GRACE = timedelta(seconds=60)
MULTIDAY_COMMISSIONING_WINDOW_DAYS = 14

OPERATING_MODE_OBSERVE = "OBSERVE"
DEFAULT_OPERATING_MODE = OPERATING_MODE_OBSERVE

PLATFORMS = ("sensor", "binary_sensor", "button", "climate", "switch", "light", "number", "select")
