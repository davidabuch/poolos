"""Constants for the PoolOS Home Assistant integration."""

from __future__ import annotations

from datetime import timedelta

DOMAIN = "poolos"
NAME = "PoolOS"
INTEGRATION_VERSION = "1.0.3"
CONFIG_ENTRY_VERSION = 2
CONFIG_ENTRY_MINOR_VERSION = 2

CONF_DIAGNOSTICS_ENABLED = "diagnostics_enabled"
DEFAULT_DIAGNOSTICS_ENABLED = True

CONF_PREFERRED_FILTRATION_CATCHUP_START = "preferred_filtration_catchup_start"
DEFAULT_PREFERRED_FILTRATION_CATCHUP_START = "20:00"
CONF_FILTRATION_SCHEDULING_MODE = "filtration_scheduling_mode"
FILTRATION_SCHEDULING_MODE_SOLAR_TOU_OPTIMIZED = "solar_tou_optimized"
FILTRATION_SCHEDULING_MODE_TRADITIONAL_TIME_BASED = "traditional_time_based"
FILTRATION_SCHEDULING_MODE_OPTIONS = (
    FILTRATION_SCHEDULING_MODE_SOLAR_TOU_OPTIMIZED,
    FILTRATION_SCHEDULING_MODE_TRADITIONAL_TIME_BASED,
)
DEFAULT_FILTRATION_SCHEDULING_MODE = FILTRATION_SCHEDULING_MODE_SOLAR_TOU_OPTIMIZED
CONF_TRADITIONAL_FILTRATION_START = "traditional_filtration_start"
DEFAULT_TRADITIONAL_FILTRATION_START = "08:00"
CONF_SPA_SOLAR_ROOF_F = "spa_solar_roof_f"
MIN_SPA_SOLAR_ROOF_F = 110.0
MAX_SPA_SOLAR_ROOF_F = 150.0
DEFAULT_SPA_SOLAR_ROOF_F = (MIN_SPA_SOLAR_ROOF_F + MAX_SPA_SOLAR_ROOF_F) / 2
CONF_PUMP_FILTRATION_RPM = "pump_filtration_rpm"
CONF_PUMP_SOLAR_HEATING_RPM = "pump_solar_heating_rpm"
CONF_PUMP_GAS_HEATING_RPM = "pump_gas_heating_rpm"
CONF_PUMP_TEMPERATURE_PROBE_RPM = "pump_temperature_probe_rpm"
CONF_PUMP_PRIMING_RPM = "pump_priming_rpm"
CONF_PUMP_GRID_OUTAGE_RPM = "pump_grid_outage_rpm"
CONF_SANITATION_RPM = "sanitation_rpm"
DEFAULT_SANITATION_RPM = 3200

# Unit-aware pump target policy. Existing installations omit these keys and
# therefore remain exact RPM-only configurations.
PUMP_TARGET_UNIT_RPM = "rpm"
PUMP_TARGET_UNIT_GPM = "gpm"
PUMP_TARGET_UNIT_OPTIONS = (PUMP_TARGET_UNIT_RPM, PUMP_TARGET_UNIT_GPM)
DEFAULT_PUMP_TARGET_UNIT = PUMP_TARGET_UNIT_RPM

CONF_PUMP_FILTRATION_UNIT = "pump_filtration_unit"
CONF_PUMP_FILTRATION_GPM = "pump_filtration_gpm"
CONF_PUMP_SOLAR_HEATING_UNIT = "pump_solar_heating_unit"
CONF_PUMP_SOLAR_HEATING_GPM = "pump_solar_heating_gpm"
CONF_PUMP_GAS_HEATING_UNIT = "pump_gas_heating_unit"
CONF_PUMP_GAS_HEATING_GPM = "pump_gas_heating_gpm"
CONF_PUMP_TEMPERATURE_PROBE_UNIT = "pump_temperature_probe_unit"
CONF_PUMP_TEMPERATURE_PROBE_GPM = "pump_temperature_probe_gpm"
CONF_PUMP_PRIMING_UNIT = "pump_priming_unit"
CONF_PUMP_PRIMING_GPM = "pump_priming_gpm"
CONF_PUMP_GRID_OUTAGE_UNIT = "pump_grid_outage_unit"
CONF_PUMP_GRID_OUTAGE_GPM = "pump_grid_outage_gpm"
CONF_SANITATION_UNIT = "sanitation_unit"
CONF_SANITATION_GPM = "sanitation_gpm"

# Optional installer commissioning used only when automatic adapter evidence is UNKNOWN.
COMMISSIONED_PUMP_MODE_AUTOMATIC = "automatic"
COMMISSIONED_PUMP_MODE_RPM_ONLY = "rpm_only"
COMMISSIONED_PUMP_MODE_RPM_GPM = "rpm_gpm"
COMMISSIONED_PUMP_MODE_OPTIONS = (
    COMMISSIONED_PUMP_MODE_AUTOMATIC,
    COMMISSIONED_PUMP_MODE_RPM_ONLY,
    COMMISSIONED_PUMP_MODE_RPM_GPM,
)
DEFAULT_COMMISSIONED_PUMP_MODE = COMMISSIONED_PUMP_MODE_AUTOMATIC

CONF_POOL_COMMISSIONED_PUMP_MODE = "pool_commissioned_pump_mode"
CONF_POOL_COMMISSIONED_PUMP_PROVIDER = "pool_commissioned_pump_provider"
CONF_POOL_COMMISSIONED_PUMP_ID = "pool_commissioned_pump_id"
CONF_POOL_COMMISSIONED_PUMP_MIN_GPM = "pool_commissioned_pump_min_gpm"
CONF_POOL_COMMISSIONED_PUMP_MAX_GPM = "pool_commissioned_pump_max_gpm"
CONF_SPA_COMMISSIONED_PUMP_MODE = "spa_commissioned_pump_mode"
CONF_SPA_COMMISSIONED_PUMP_PROVIDER = "spa_commissioned_pump_provider"
CONF_SPA_COMMISSIONED_PUMP_ID = "spa_commissioned_pump_id"
CONF_SPA_COMMISSIONED_PUMP_MIN_GPM = "spa_commissioned_pump_min_gpm"
CONF_SPA_COMMISSIONED_PUMP_MAX_GPM = "spa_commissioned_pump_max_gpm"
CONF_POOL_SANITATION_DURATION_MINUTES = "pool_sanitation_duration_minutes"
DEFAULT_POOL_SANITATION_DURATION_MINUTES = 240
CONF_HOT_TUB_SANITATION_DURATION_MINUTES = "hot_tub_sanitation_duration_minutes"
DEFAULT_HOT_TUB_SANITATION_DURATION_MINUTES = 240
MIN_SANITATION_DURATION_MINUTES = 30
MAX_SANITATION_DURATION_MINUTES = 1440
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
CONF_GRID_OUTAGE_SIMULATION_ENTITY = "grid_outage_simulation_entity"
CONF_POOL_LIGHT_ENTITY = "pool_light_entity"

# Removed in config-entry schema 2.1. Native IntelliCenter observations remain;
# only the obsolete Home Assistant shadow/parity mappings are retired.
RETIRED_LEGACY_RUNTIME_OPTIONS = frozenset({"operating_mode"})

RETIRED_LEGACY_INTELLICENTER_ENTITY_OPTIONS = frozenset(
    {
        "firmware_version_entity",
        "freeze_active_entity",
        "intellichlor_pool_output_entity",
        "intellichlor_salt_entity",
        "intellichlor_spa_output_entity",
        "pool_maximum_temperature_entity",
        "pump_maximum_rpm_entity",
        "pump_minimum_rpm_entity",
        "spa_maximum_temperature_entity",
        "system_mode_entity",
    }
)

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
    CONF_GRID_OUTAGE_SIMULATION_ENTITY,
)
ALL_ENTITY_OPTIONS = REQUIRED_ENTITY_OPTIONS + OPTIONAL_ENTITY_OPTIONS

# Periodic reconciliation is a resilience/backstop mechanism.  Relevant HA
# state-change events are observed immediately between reconciliation passes.
OBSERVATION_UPDATE_INTERVAL = timedelta(seconds=30)
OBSERVATION_STALE_AFTER = timedelta(minutes=5)
STARTUP_HEALTH_GRACE = timedelta(seconds=60)
MULTIDAY_COMMISSIONING_WINDOW_DAYS = 14


PLATFORMS = ("sensor", "binary_sensor", "button", "climate", "switch", "light", "number", "select")
