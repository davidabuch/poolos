"""Constants for the PoolOS Home Assistant integration."""

from __future__ import annotations

from datetime import timedelta

DOMAIN = "poolos"
NAME = "PoolOS"
INTEGRATION_VERSION = "0.10.0"

CONF_DIAGNOSTICS_ENABLED = "diagnostics_enabled"
DEFAULT_DIAGNOSTICS_ENABLED = True

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
CONF_SOLAR_PREFERRED_ENTITY = "solar_preferred_entity"
CONF_WATERFALL_ACTIVE_ENTITY = "waterfall_active_entity"
CONF_JETS_ACTIVE_ENTITY = "jets_active_entity"
CONF_SLIDE_ACTIVE_ENTITY = "slide_active_entity"
CONF_GRID_STATUS_ENTITY = "grid_status_entity"
CONF_POOL_LIGHT_ENTITY = "pool_light_entity"

REQUIRED_ENTITY_OPTIONS = (
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
    CONF_GRID_STATUS_ENTITY,
    CONF_POOL_LIGHT_ENTITY,
)
OPTIONAL_ENTITY_OPTIONS = (
    CONF_SOLAR_PREFERRED_ENTITY,
    CONF_WATERFALL_ACTIVE_ENTITY,
    CONF_JETS_ACTIVE_ENTITY,
    CONF_SLIDE_ACTIVE_ENTITY,
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

PLATFORMS = ("sensor", "button")
