"""Configuration flow for the PoolOS integration skeleton."""

from __future__ import annotations

from typing import Any

from homeassistant.config_entries import ConfigEntry, ConfigFlow, ConfigFlowResult, OptionsFlow
from homeassistant.core import callback
import voluptuous as vol

from .const import (
    CONF_DIAGNOSTICS_ENABLED,
    DEFAULT_DIAGNOSTICS_ENABLED,
    DEFAULT_OPERATING_MODE,
    DOMAIN,
    NAME,
)


class PoolOSConfigFlow(ConfigFlow, domain=DOMAIN):
    """Create the single PoolOS commissioning entry."""

    VERSION = 1
    MINOR_VERSION = 1

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Create an inert OBSERVE-mode entry after explicit confirmation."""
        if self._async_current_entries():
            return self.async_abort(reason="single_instance_allowed")

        if user_input is not None:
            return self.async_create_entry(
                title=NAME,
                data={"operating_mode": DEFAULT_OPERATING_MODE},
            )

        return self.async_show_form(step_id="user", data_schema=vol.Schema({}))

    @staticmethod
    @callback
    def async_get_options_flow(config_entry: ConfigEntry) -> PoolOSOptionsFlow:
        """Return the PoolOS options flow."""
        return PoolOSOptionsFlow()


class PoolOSOptionsFlow(OptionsFlow):
    """Configure non-authority-changing integration options."""

    async def async_step_init(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Configure diagnostic collection only."""
        if user_input is not None:
            return self.async_create_entry(data=user_input)

        current = self.config_entry.options.get(
            CONF_DIAGNOSTICS_ENABLED, DEFAULT_DIAGNOSTICS_ENABLED
        )
        schema = vol.Schema(
            {vol.Required(CONF_DIAGNOSTICS_ENABLED, default=current): bool}
        )
        return self.async_show_form(step_id="init", data_schema=schema)
