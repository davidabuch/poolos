"""Pentair IntelliCenter climate entities for pool/spa temperature control.

This module provides two climate entity types:

* PoolClimate
  For bodies with cooling-capable UltraTemp equipment. It exposes HEAT_COOL
  with separate heating and cooling setpoints.

* PoolHeatOnlyClimate
  For ordinary Pool/Spa bodies with heating-only equipment such as gas,
  solar, or heat-pump heating. It exposes only OFF and HEAT and combines:

  - Pool/Spa body STATUS for circulation and pump operation
  - LOTMP for the heating target
  - HEATER/HTMODE for heating configuration
  - OFF, IDLE, and HEATING thermostat activity

The heat-only entity intentionally does not expose fan modes, cooling, or auto.
"""

from __future__ import annotations

from collections.abc import Iterable
import logging
from typing import Any

from homeassistant.components.climate import ClimateEntity
from homeassistant.components.climate.const import (
    ATTR_TARGET_TEMP_HIGH,
    ATTR_TARGET_TEMP_LOW,
    ClimateEntityFeature,
    HVACAction,
    HVACMode,
)
from homeassistant.const import ATTR_TEMPERATURE
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from pyintellicenter import (
    COOL_ATTR,
    HEATER_ATTR,
    HITMP_ATTR,
    HTMODE_ATTR,
    LOTMP_ATTR,
    LSTTMP_ATTR,
    NULL_OBJNAM,
    STATUS_ATTR,
    STATUS_OFF,
    PoolObject,
)

from . import (
    IntelliCenterConfigEntry,
    PoolEntity,
    async_setup_pool_entities,
    bodies_affected_by,
    body_temperature_limits,
    heaters_for_body,
)
from .coordinator import IntelliCenterCoordinator

_LOGGER = logging.getLogger(__name__)

# Coordinator handles updates through push notifications.
PARALLEL_UPDATES = 0


def _build_entities(
    coordinator: IntelliCenterCoordinator,
    candidates: Iterable[PoolObject],
) -> list[ClimateEntity]:
    """Build the appropriate climate entity for each heated Pool/Spa body.

    Cooling-capable bodies retain the original PoolClimate implementation.

    Heating-only bodies receive PoolHeatOnlyClimate, which combines the body
    STATUS control with the heating setpoint and thermostat state.
    """
    climate_entities: list[ClimateEntity] = []

    for body in bodies_affected_by(coordinator, candidates):
        heater_list = heaters_for_body(coordinator, body.objnam)

        if not heater_list:
            continue

        if coordinator.controller.body_supports_cooling(body.objnam):
            climate_entities.append(
                PoolClimate(
                    coordinator,
                    body,
                    heater_list,
                )
            )
        else:
            climate_entities.append(
                PoolHeatOnlyClimate(
                    coordinator,
                    body,
                    heater_list,
                )
            )

    return climate_entities


async def async_setup_entry(
    hass: HomeAssistant,
    entry: IntelliCenterConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up IntelliCenter climate entities."""
    async_setup_pool_entities(
        entry,
        async_add_entities,
        _build_entities,
    )


# -----------------------------------------------------------------------------
# Cooling-capable UltraTemp climate entity
# -----------------------------------------------------------------------------


class PoolClimate(PoolEntity, ClimateEntity):
    """Climate entity for Pool/Spa bodies with heating and cooling support.

    This is the original cooling-capable implementation. It exposes:

    - OFF
    - HEAT_COOL
    - Heating setpoint through LOTMP
    - Cooling setpoint through HITMP
    - Heater selection through preset modes
    """

    _attr_icon = "mdi:thermometer-water"
    _enable_turn_on_off_backwards_compat = False

    def __init__(
        self,
        coordinator: IntelliCenterCoordinator,
        pool_object: PoolObject,
        heater_list: list[str],
    ) -> None:
        """Initialize the cooling-capable climate entity."""
        super().__init__(
            coordinator,
            pool_object,
            name="+ Thermostat",
            extra_state_attributes=[HEATER_ATTR, HTMODE_ATTR],
        )

        self._seed_heater_list = heater_list
        self._attr_hvac_modes = [
            HVACMode.OFF,
            HVACMode.HEAT_COOL,
        ]

    @property
    def _heater_list(self) -> list[str]:
        """Return heaters currently wired to this body."""
        live = heaters_for_body(
            self.coordinator,
            self._pool_object.objnam,
        )
        return live if live else self._seed_heater_list

    @property
    def unique_id(self) -> str:
        """Return a unique ID."""
        return f"{super().unique_id}_climate"

    @property
    def supported_features(self) -> ClimateEntityFeature:
        """Return supported features."""
        return (
            ClimateEntityFeature.TARGET_TEMPERATURE_RANGE
            | ClimateEntityFeature.TURN_ON
            | ClimateEntityFeature.TURN_OFF
            | ClimateEntityFeature.PRESET_MODE
        )

    @property
    def temperature_unit(self) -> str:
        """Return the IntelliCenter temperature unit."""
        return self.pentairTemperatureSettings()

    @property
    def min_temp(self) -> float:
        """Return the minimum target temperature."""
        return body_temperature_limits(self.coordinator)[0]

    @property
    def max_temp(self) -> float:
        """Return the maximum target temperature."""
        return body_temperature_limits(self.coordinator)[1]

    @property
    def current_temperature(self) -> float | None:
        """Return the current water temperature."""
        return self._safe_float_conversion(
            self._pool_object[LSTTMP_ATTR]
        )

    @property
    def target_temperature_low(self) -> float | None:
        """Return the heating setpoint."""
        return self._safe_float_conversion(
            self._pool_object[LOTMP_ATTR]
        )

    @property
    def target_temperature_high(self) -> float | None:
        """Return the cooling setpoint."""
        return self._safe_float_conversion(
            self._pool_object[HITMP_ATTR]
        )

    @property
    def hvac_mode(self) -> HVACMode:
        """Return the current HVAC mode."""
        status = self._pool_object[STATUS_ATTR]
        heater = self._pool_object[HEATER_ATTR]

        if status == STATUS_OFF or heater == NULL_OBJNAM:
            return HVACMode.OFF

        return HVACMode.HEAT_COOL

    @property
    def preset_mode(self) -> str | None:
        """Return the selected heater."""
        heater = self._pool_object[HEATER_ATTR]

        if heater in self._heater_list:
            heater_obj = self.coordinator.model[heater]

            if heater_obj is not None and heater_obj.sname is not None:
                return str(heater_obj.sname)

        return None

    @property
    def preset_modes(self) -> list[str]:
        """Return available heater selections."""
        presets: list[str] = []

        for heater in self._heater_list:
            heater_obj = self.coordinator.model[heater]

            if heater_obj is not None and heater_obj.sname is not None:
                presets.append(str(heater_obj.sname))

        return presets

    @property
    def hvac_action(self) -> HVACAction:
        """Return the current heating or cooling action."""
        status = self._pool_object[STATUS_ATTR]
        heater = self._pool_object[HEATER_ATTR]

        if status == STATUS_OFF or heater == NULL_OBJNAM:
            return HVACAction.OFF

        htmode = self._pool_object[HTMODE_ATTR]

        if htmode in (None, "", "0"):
            return HVACAction.IDLE

        if self._controller.is_body_cooling(
            self._pool_object.objnam
        ):
            return HVACAction.COOLING

        if self._controller.is_body_heating(
            self._pool_object.objnam
        ):
            return HVACAction.HEATING

        return HVACAction.IDLE

    async def async_set_hvac_mode(
        self,
        hvac_mode: HVACMode,
    ) -> None:
        """Set the HVAC mode and body state."""
        if hvac_mode == HVACMode.OFF:
            await self._async_execute_command(
                self._controller.request_changes(
                    self._pool_object.objnam,
                    {
                        STATUS_ATTR: self._pool_object.off_status,
                    },
                )
            )
            return

        if hvac_mode != HVACMode.HEAT_COOL:
            raise HomeAssistantError(
                f"Unsupported HVAC mode '{hvac_mode}'"
            )

        current_heater = self._pool_object[HEATER_ATTR]

        if current_heater not in self._heater_list:
            if not self._heater_list:
                raise HomeAssistantError(
                    "No heater is configured for this body"
                )

            await self._async_execute_command(
                self._controller.request_changes(
                    self._pool_object.objnam,
                    {
                        HEATER_ATTR: self._heater_list[0],
                    },
                )
            )

        await self._async_execute_command(
            self._controller.request_changes(
                self._pool_object.objnam,
                {
                    STATUS_ATTR: self._pool_object.on_status,
                },
            )
        )

    async def async_set_preset_mode(
        self,
        preset_mode: str,
    ) -> None:
        """Select a heater."""
        for heater in self._heater_list:
            heater_obj = self.coordinator.model[heater]

            if (
                heater_obj is not None
                and preset_mode == heater_obj.sname
            ):
                await self._async_execute_command(
                    self._controller.request_changes(
                        self._pool_object.objnam,
                        {
                            HEATER_ATTR: heater,
                        },
                    )
                )
                return

        raise HomeAssistantError(
            f"Unknown heater preset '{preset_mode}'"
        )

    async def async_set_temperature(
        self,
        **kwargs: Any,
    ) -> None:
        """Set heating and cooling targets."""
        low_temp = kwargs.get(ATTR_TARGET_TEMP_LOW)
        high_temp = kwargs.get(ATTR_TARGET_TEMP_HIGH)

        if low_temp is not None:
            await self._async_execute_command(
                self._controller.set_heating_setpoint(
                    self._pool_object.objnam,
                    self._coerce_setpoint(low_temp),
                )
            )

        if high_temp is not None:
            await self._async_execute_command(
                self._controller.set_cooling_setpoint(
                    self._pool_object.objnam,
                    self._coerce_setpoint(high_temp),
                )
            )

    @staticmethod
    def _coerce_setpoint(value: Any) -> int:
        """Convert a target temperature to an integer."""
        try:
            return int(value)
        except (ValueError, TypeError) as err:
            raise HomeAssistantError(
                f"Invalid temperature value '{value}'"
            ) from err

    async def async_turn_on(self) -> None:
        """Turn the Pool/Spa body on."""
        await self.async_set_hvac_mode(HVACMode.HEAT_COOL)

    async def async_turn_off(self) -> None:
        """Turn the Pool/Spa body off."""
        await self.async_set_hvac_mode(HVACMode.OFF)

    def isUpdated(
        self,
        updates: dict[str, dict[str, Any]],
    ) -> bool:
        """Return True when climate-relevant data changes."""
        my_updates = updates.get(
            self._pool_object.objnam,
            {},
        )

        if bool(
            my_updates
            and {
                STATUS_ATTR,
                HEATER_ATTR,
                HTMODE_ATTR,
                LOTMP_ATTR,
                HITMP_ATTR,
                LSTTMP_ATTR,
            }
            & my_updates.keys()
        ):
            return True

        return any(
            COOL_ATTR in updates.get(heater, {})
            for heater in self._heater_list
        )


# -----------------------------------------------------------------------------
# Heat-only Pool/Spa thermostat
# -----------------------------------------------------------------------------


class PoolHeatOnlyClimate(PoolEntity, ClimateEntity):
    """Heat-only thermostat for an IntelliCenter Pool or Spa body.

    This entity exposes only:

    - HVACMode.OFF
    - HVACMode.HEAT
    - HVACAction.OFF
    - HVACAction.IDLE
    - HVACAction.HEATING

    Turning the thermostat on or off controls the Pool/Spa body STATUS. That
    activates or deactivates the body circuit and lets IntelliCenter manage the
    associated circulation pump.

    Heater selection and HTMODE are preserved when the body is turned off.
    """

    _attr_icon = "mdi:thermometer-water"
    _enable_turn_on_off_backwards_compat = False

    def __init__(
        self,
        coordinator: IntelliCenterCoordinator,
        pool_object: PoolObject,
        heater_list: list[str],
    ) -> None:
        """Initialize the heat-only climate entity."""
        super().__init__(
            coordinator,
            pool_object,
            name="+ Thermostat",
            extra_state_attributes=[
                HEATER_ATTR,
                HTMODE_ATTR,
            ],
        )

        self._seed_heater_list = heater_list
        self._attr_hvac_modes = [
            HVACMode.OFF,
            HVACMode.HEAT,
        ]

    @property
    def _heater_list(self) -> list[str]:
        """Return heaters currently wired to this body."""
        live = heaters_for_body(
            self.coordinator,
            self._pool_object.objnam,
        )
        return live if live else self._seed_heater_list

    @property
    def unique_id(self) -> str:
        """Return a stable unique ID."""
        return f"{super().unique_id}_heat_only_climate"

    @property
    def supported_features(self) -> ClimateEntityFeature:
        """Return supported thermostat features."""
        return (
            ClimateEntityFeature.TARGET_TEMPERATURE
            | ClimateEntityFeature.TURN_ON
            | ClimateEntityFeature.TURN_OFF
        )

    @property
    def temperature_unit(self) -> str:
        """Return the IntelliCenter temperature unit."""
        return self.pentairTemperatureSettings()

    @property
    def min_temp(self) -> float:
        """Return the minimum target temperature."""
        return body_temperature_limits(self.coordinator)[0]

    @property
    def max_temp(self) -> float:
        """Return the maximum target temperature."""
        return body_temperature_limits(self.coordinator)[1]

    @property
    def current_temperature(self) -> float | None:
        """Return the current Pool/Spa water temperature."""
        return self._safe_float_conversion(
            self._pool_object[LSTTMP_ATTR]
        )

    @property
    def target_temperature(self) -> float | None:
        """Return the heating target."""
        return self._safe_float_conversion(
            self._pool_object[LOTMP_ATTR]
        )

    @property
    def hvac_mode(self) -> HVACMode:
        """Return OFF when the body is off and HEAT when it is on."""
        if self._pool_object[STATUS_ATTR] == STATUS_OFF:
            return HVACMode.OFF

        return HVACMode.HEAT

    @property
    def hvac_action(self) -> HVACAction:
        """Return OFF, IDLE, or HEATING.

        IntelliCenter's HTMODE indicates that a heating method is selected,
        but a selected heating method does not necessarily mean that heat is
        currently required.

        The entity therefore reports HEATING only while:

        - The Pool/Spa body is on
        - A heater is selected
        - HTMODE is active
        - The current water temperature is below the target
        """
        if self._pool_object[STATUS_ATTR] == STATUS_OFF:
            return HVACAction.OFF

        heater = self._pool_object[HEATER_ATTR]
        htmode = self._pool_object[HTMODE_ATTR]

        if heater in (None, "", NULL_OBJNAM):
            return HVACAction.IDLE

        if htmode in (None, "", "0"):
            return HVACAction.IDLE

        current = self.current_temperature
        target = self.target_temperature

        if current is None or target is None:
            return HVACAction.IDLE

        if current < target:
            return HVACAction.HEATING

        return HVACAction.IDLE

    async def async_set_temperature(
        self,
        **kwargs: Any,
    ) -> None:
        """Set the heating target without changing body state."""
        target = kwargs.get(ATTR_TEMPERATURE)

        if target is None:
            return

        try:
            target_value = int(target)
        except (TypeError, ValueError) as err:
            raise HomeAssistantError(
                f"Invalid temperature value '{target}'"
            ) from err

        await self._async_execute_command(
            self._controller.set_setpoint(
                self._pool_object.objnam,
                target_value,
            )
        )

    async def async_set_hvac_mode(
        self,
        hvac_mode: HVACMode,
    ) -> None:
        """Turn the Pool/Spa body on or off.

        Turning HEAT on preserves the currently selected heater. If no valid
        heater is selected, the first heater wired to the body is selected
        before the body is started.

        Turning OFF stops the Pool/Spa body but preserves the heater selection
        and setpoint for the next start.
        """
        if hvac_mode == HVACMode.OFF:
            await self._async_execute_command(
                self._controller.request_changes(
                    self._pool_object.objnam,
                    {
                        STATUS_ATTR: self._pool_object.off_status,
                    },
                )
            )
            return

        if hvac_mode != HVACMode.HEAT:
            raise HomeAssistantError(
                f"Unsupported HVAC mode '{hvac_mode}'"
            )

        current_heater = self._pool_object[HEATER_ATTR]

        if current_heater not in self._heater_list:
            if not self._heater_list:
                raise HomeAssistantError(
                    "No heater is configured for this Pool/Spa body"
                )

            await self._async_execute_command(
                self._controller.request_changes(
                    self._pool_object.objnam,
                    {
                        HEATER_ATTR: self._heater_list[0],
                    },
                )
            )

        await self._async_execute_command(
            self._controller.request_changes(
                self._pool_object.objnam,
                {
                    STATUS_ATTR: self._pool_object.on_status,
                },
            )
        )

    async def async_turn_on(self) -> None:
        """Turn the Pool/Spa body on."""
        await self.async_set_hvac_mode(HVACMode.HEAT)

    async def async_turn_off(self) -> None:
        """Turn the Pool/Spa body off."""
        await self.async_set_hvac_mode(HVACMode.OFF)

    def isUpdated(
        self,
        updates: dict[str, dict[str, Any]],
    ) -> bool:
        """Return True when thermostat-relevant body data changes."""
        return self._check_attributes_updated(
            updates,
            STATUS_ATTR,
            HEATER_ATTR,
            HTMODE_ATTR,
            LOTMP_ATTR,
            LSTTMP_ATTR,
        )