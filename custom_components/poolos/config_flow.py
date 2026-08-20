"""Configuration and read-only entity-mapping flows for PoolOS."""

from __future__ import annotations

from typing import Any

from homeassistant.config_entries import ConfigEntry, ConfigFlow, ConfigFlowResult, OptionsFlow
from homeassistant.core import callback
from homeassistant.helpers import selector
import voluptuous as vol

from .const import (
    ALL_ENTITY_OPTIONS,
    CONF_AIR_TEMPERATURE_ENTITY,
    CONF_DIAGNOSTICS_ENABLED,
    CONF_HEATER_ACTIVE_ENTITY,
    CONF_INTELLICENTER_HOST,
    CONF_INTELLICENTER_TRANSPORT,
    CONF_GRID_STATUS_ENTITY,
    CONF_JETS_ACTIVE_ENTITY,
    CONF_POOL_COMMAND_ENTITY,
    CONF_POOL_LIGHT_ENTITY,
    CONF_POOL_THERMOSTAT_ENTITY,
    CONF_PUMP_GPM_ENTITY,
    CONF_PUMP_POWER_ENTITY,
    CONF_PUMP_RPM_ENTITY,
    CONF_SLIDE_ACTIVE_ENTITY,
    CONF_SOLAR_ACTIVE_ENTITY,
    CONF_SOLAR_PREFERRED_ENTITY,
    CONF_SOLAR_TEMPERATURE_ENTITY,
    CONF_SPA_COMMAND_ENTITY,
    CONF_SPA_THERMOSTAT_ENTITY,
    CONF_WATERFALL_ACTIVE_ENTITY,
    CONF_WATER_TEMPERATURE_ENTITY,
    DEFAULT_DIAGNOSTICS_ENABLED,
    DEFAULT_INTELLICENTER_TRANSPORT,
    DEFAULT_OPERATING_MODE,
    DOMAIN,
    NAME,
    INTELLICENTER_TRANSPORT_OPTIONS,
)


class PoolOSConfigFlow(ConfigFlow, domain=DOMAIN):
    """Create the single PoolOS commissioning entry."""

    VERSION = 2
    MINOR_VERSION = 0

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Create an OBSERVE-mode entry after explicit confirmation."""
        if self._async_current_entries():
            return self.async_abort(reason="single_instance_allowed")

        if user_input is not None:
            return self.async_create_entry(
                title=NAME,
                data={"operating_mode": DEFAULT_OPERATING_MODE, **user_input},
            )

        return self.async_show_form(step_id="user", data_schema=_mapping_schema({}))

    @staticmethod
    @callback
    def async_get_options_flow(config_entry: ConfigEntry) -> PoolOSOptionsFlow:
        """Return the PoolOS options flow."""
        return PoolOSOptionsFlow()


class PoolOSOptionsFlow(OptionsFlow):
    """Configure read-only entity mappings and diagnostics."""

    async def async_step_init(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Update observation mappings without changing authority."""
        if user_input is not None:
            return self.async_create_entry(data=user_input)
        return self.async_show_form(
            step_id="init",
            data_schema=_mapping_schema(
                {**dict(self.config_entry.data), **dict(self.config_entry.options)}
            ),
        )


def _entity_selector(domains: list[str]) -> selector.EntitySelector:
    return selector.EntitySelector(
        selector.EntitySelectorConfig(domain=domains, multiple=False)
    )


def _mapping_schema(current: dict[str, Any]) -> vol.Schema:
    """Build the high-fidelity read-only observation mapping schema."""

    # C5.9: IntelliCenter-owned controller observations come directly from
    # PoolOS native transport. Grid remains mandatory external HA truth.
    # Legacy Pentair mappings remain optional for parity commissioning.
    required = {
        CONF_GRID_STATUS_ENTITY: ["binary_sensor"],
    }
    optional = {
        CONF_POOL_THERMOSTAT_ENTITY: ["climate"],
        CONF_SPA_THERMOSTAT_ENTITY: ["climate"],
        CONF_PUMP_RPM_ENTITY: ["sensor", "number"],
        CONF_PUMP_GPM_ENTITY: ["sensor"],
        CONF_PUMP_POWER_ENTITY: ["sensor"],
        CONF_WATER_TEMPERATURE_ENTITY: ["sensor"],
        CONF_SOLAR_TEMPERATURE_ENTITY: ["sensor"],
        CONF_AIR_TEMPERATURE_ENTITY: ["sensor"],
        CONF_SOLAR_ACTIVE_ENTITY: ["binary_sensor", "switch"],
        CONF_HEATER_ACTIVE_ENTITY: ["binary_sensor", "switch"],
        CONF_POOL_COMMAND_ENTITY: ["binary_sensor", "switch"],
        CONF_SPA_COMMAND_ENTITY: ["binary_sensor", "switch"],
        CONF_SOLAR_PREFERRED_ENTITY: ["binary_sensor", "switch"],
        CONF_WATERFALL_ACTIVE_ENTITY: ["binary_sensor", "switch"],
        CONF_JETS_ACTIVE_ENTITY: ["binary_sensor", "switch"],
        CONF_SLIDE_ACTIVE_ENTITY: ["binary_sensor", "switch"],
        CONF_POOL_LIGHT_ENTITY: ["light"],
    }

    fields: dict[vol.Marker, object] = {}
    for key, domains in required.items():
        fields[vol.Required(key, default=current.get(key, vol.UNDEFINED))] = _entity_selector(domains)
    for key, domains in optional.items():
        fields[vol.Optional(key, default=current.get(key, vol.UNDEFINED))] = _entity_selector(domains)
    fields[
        vol.Required(
            CONF_DIAGNOSTICS_ENABLED,
            default=current.get(CONF_DIAGNOSTICS_ENABLED, DEFAULT_DIAGNOSTICS_ENABLED),
        )
    ] = bool
    fields[
        vol.Optional(
            CONF_INTELLICENTER_HOST,
            default=current.get(CONF_INTELLICENTER_HOST, vol.UNDEFINED),
        )
    ] = str
    fields[
        vol.Required(
            CONF_INTELLICENTER_TRANSPORT,
            default=current.get(
                CONF_INTELLICENTER_TRANSPORT,
                DEFAULT_INTELLICENTER_TRANSPORT,
            ),
        )
    ] = vol.In(INTELLICENTER_TRANSPORT_OPTIONS)
    assert set(ALL_ENTITY_OPTIONS) == required.keys() | optional.keys()
    return vol.Schema(fields)
