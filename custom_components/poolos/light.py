"""Native PoolOS manual IntelliCenter pool light entity."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from homeassistant.components.light import ATTR_EFFECT, ColorMode, LightEntity, LightEntityFeature
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback
from homeassistant.helpers.event import async_call_later
from homeassistant.helpers.update_coordinator import CoordinatorEntity
from pyintellicenter import LIGHT_EFFECTS

from . import PoolOSRuntimeData
from .const import DOMAIN, INTEGRATION_VERSION
from .coordinator import PoolOSCoordinator
from .manual_intellicenter import ManualIntelliCenterCommandError

_POOL_LIGHT_OBJNAM = "C0002"
_POOL_LIGHT_CONCEPT = "pool_light.active"
_POOL_LIGHT_EFFECT_CONCEPT = "pool_light.effect"
_POOL_LIGHT_TRANSITION_SECONDS = 20


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
    _attr_supported_features = LightEntityFeature.EFFECT
    _attr_effect_list = list(LIGHT_EFFECTS.values())

    def __init__(
        self,
        coordinator: PoolOSCoordinator,
        entry: ConfigEntry[PoolOSRuntimeData],
    ) -> None:
        super().__init__(coordinator)
        self._runtime = entry.runtime_data
        self._cancel_transition_timer: Callable[[], None] | None = None
        self._transitioning = False

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
            not self._transitioning
            and snapshot is not None
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

    @property
    def effect(self) -> str | None:
        """Return confirmed native IntelliBrite effect."""

        effect_code = _native_value(
            self.coordinator,
            _POOL_LIGHT_EFFECT_CONCEPT,
        )
        if not isinstance(effect_code, str):
            return None
        return LIGHT_EFFECTS.get(effect_code)

    @property
    def native_effect_code(self) -> str | None:
        """Return confirmed native IntelliBrite controller effect code."""

        value = _native_value(
            self.coordinator,
            _POOL_LIGHT_EFFECT_CONCEPT,
        )
        return value if isinstance(value, str) else None

    async def async_turn_on(self, **kwargs: Any) -> None:
        """Turn the Pool Light circuit on."""

        effect = kwargs.get(ATTR_EFFECT)

        manual = self._runtime.manual_intellicenter
        if manual is None:
            raise ManualIntelliCenterCommandError(
                "manual IntelliCenter command connection is not configured"
            )

        if effect is not None:
            reverse_effects = {name: code for code, name in LIGHT_EFFECTS.items()}
            effect_code = reverse_effects.get(str(effect))
            if effect_code is None:
                raise ValueError(f"unsupported Pool Light effect: {effect}")

            await manual.async_set_light_effect(
                _POOL_LIGHT_OBJNAM,
                effect_code,
            )

        await manual.async_set_circuit_state(
            _POOL_LIGHT_OBJNAM,
            True,
        )

        self._begin_transition_lockout()

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

    def _begin_transition_lockout(self) -> None:
        """Temporarily disable interaction while IntelliCenter engages the scene."""

        if self._cancel_transition_timer is not None:
            self._cancel_transition_timer()
            self._cancel_transition_timer = None

        self._transitioning = True
        self.async_write_ha_state()

        self._cancel_transition_timer = async_call_later(
            self.hass,
            _POOL_LIGHT_TRANSITION_SECONDS,
            self._async_transition_complete,
        )

    async def _async_transition_complete(self, _now: Any) -> None:
        """Re-enable the entity after the controller transition window."""

        self._cancel_transition_timer = None
        self._transitioning = False
        self.async_write_ha_state()

    async def async_will_remove_from_hass(self) -> None:
        """Cancel the transition timer when the entity is removed."""

        if self._cancel_transition_timer is not None:
            self._cancel_transition_timer()
            self._cancel_transition_timer = None

        await super().async_will_remove_from_hass()

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
            "effect_control_enabled": True,
            "effect_observation_concept": _POOL_LIGHT_EFFECT_CONCEPT,
            "effect_code": self.native_effect_code,
            "optimistic": False,
            "transitioning": self._transitioning,
            "transition_lockout_seconds": _POOL_LIGHT_TRANSITION_SECONDS,
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
