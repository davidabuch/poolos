"""Native PoolOS manual IntelliCenter pool light entity."""

from __future__ import annotations

from typing import Any

from homeassistant.components.light import ColorMode, LightEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from . import PoolOSRuntimeData
from .const import DOMAIN, INTEGRATION_VERSION
from .coordinator import PoolOSCoordinator
from .manual_intellicenter import ManualIntelliCenterCommandError

_POOL_LIGHT_OBJNAM = "C0002"
_POOL_LIGHT_CONCEPT = "pool_light.active"


def _native_observation(
    coordinator: PoolOSCoordinator,
    concept: str,
) -> Any:
    snapshot = coordinator.native_intellicenter_snapshot
    if snapshot is None:
        return None

    for observation in snapshot.observations:
        if observation.observation_id == concept:
            return observation

    return None


def _native_value(
    coordinator: PoolOSCoordinator,
    concept: str,
) -> Any:
    observation = _native_observation(coordinator, concept)
    return None if observation is None else observation.value


class PoolOSNativeIntelliCenterPoolLight(
    CoordinatorEntity[PoolOSCoordinator],
    LightEntity,
):
    """Represent the native IntelliCenter Pool Light circuit."""

    _attr_has_entity_name = True
    _attr_name = "Pool Light"
    _attr_icon = "mdi:pool"
    _attr_supported_color_modes = {ColorMode.ONOFF}
    _attr_color_mode = ColorMode.ONOFF

    def __init__(
        self,
        coordinator: PoolOSCoordinator,
        entry: ConfigEntry[PoolOSRuntimeData],
    ) -> None:
        super().__init__(coordinator)
        self._runtime = entry.runtime_data

        self._attr_unique_id = (
            f"{entry.entry_id}_native_intellicenter_pool_light"
        )
        self._attr_device_info = {
            "identifiers": {(DOMAIN, f"{entry.entry_id}_native_intellicenter")},
            "name": "PoolOS Native IntelliCenter",
            "manufacturer": "PoolOS",
            "model": "Native IntelliCenter Manual Pool Light Control",
            "sw_version": INTEGRATION_VERSION,
        }

    @property
    def available(self) -> bool:
        """Return whether native truth and manual delivery are available."""

        snapshot = self.coordinator.native_intellicenter_snapshot
        manual = self._runtime.manual_intellicenter

        return (
            snapshot is not None
            and bool(getattr(snapshot, "available", False))
            and _native_observation(
                self.coordinator,
                _POOL_LIGHT_CONCEPT,
            )
            is not None
            and manual is not None
            and manual.available
        )

    @property
    def is_on(self) -> bool | None:
        """Return confirmed native IntelliCenter light state."""

        value = _native_value(
            self.coordinator,
            _POOL_LIGHT_CONCEPT,
        )
        return value if isinstance(value, bool) else None

    async def async_turn_on(self, **kwargs: Any) -> None:
        """Turn the Pool Light circuit on."""

        del kwargs

        manual = self._runtime.manual_intellicenter
        if manual is None:
            raise ManualIntelliCenterCommandError(
                "manual IntelliCenter command connection is not configured"
            )

        await manual.async_set_circuit_state(
            _POOL_LIGHT_OBJNAM,
            True,
        )

    async def async_turn_off(self, **kwargs: Any) -> None:
        """Turn the Pool Light circuit off."""

        del kwargs

        manual = self._runtime.manual_intellicenter
        if manual is None:
            raise ManualIntelliCenterCommandError(
                "manual IntelliCenter command connection is not configured"
            )

        await manual.async_set_circuit_state(
            _POOL_LIGHT_OBJNAM,
            False,
        )

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Expose bounded native-authority and command diagnostics."""

        manual = self._runtime.manual_intellicenter

        return {
            "circuit_objnam": _POOL_LIGHT_OBJNAM,
            "canonical_concept": _POOL_LIGHT_CONCEPT,
            "observation_source": "poolos.independent_intellicenter",
            "observation_authority": "native_intellicenter",
            "manual_command_delivery_enabled": (
                manual is not None and manual.available
            ),
            "autonomous_command_delivery_enabled": False,
            "effect_control_enabled": False,
            "optimistic": False,
        }


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry[PoolOSRuntimeData],
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up the PoolOS native Pool Light entity."""

    del hass

    async_add_entities(
        [
            PoolOSNativeIntelliCenterPoolLight(
                entry.runtime_data.coordinator,
                entry,
            )
        ]
    )
