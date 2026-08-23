"""Native PoolOS manual IntelliCenter feature switches."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from homeassistant.components.switch import SwitchEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from . import PoolOSRuntimeData
from .const import DOMAIN, INTEGRATION_VERSION
from .coordinator import PoolOSCoordinator
from .manual_intellicenter import ManualIntelliCenterCommandError


@dataclass(frozen=True, slots=True)
class PoolOSSwitchDescription:
    """Describe one explicitly controllable IntelliCenter feature."""

    key: str
    name: str
    objnam: str
    active_concept: str
    icon: str
    required_parent_concept: str | None = None
    required_parent_name: str | None = None


SWITCH_DESCRIPTIONS = (
    PoolOSSwitchDescription(
        key="jets",
        name="Jets / Bubbles",
        objnam="C0003",
        active_concept="jets.active",
        icon="mdi:weather-windy",
        required_parent_concept="spa.active",
        required_parent_name="Spa",
    ),
    PoolOSSwitchDescription(
        key="slide",
        name="Water Slide",
        objnam="C0004",
        active_concept="slide.active",
        icon="mdi:slide",
    ),
    PoolOSSwitchDescription(
        key="waterfall",
        name="Spillway",
        objnam="FTR01",
        active_concept="waterfall.active",
        icon="mdi:waves-arrow-down",
        required_parent_concept="pool.active",
        required_parent_name="Pool",
    ),
)


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


class PoolOSNativeIntelliCenterSwitch(
    CoordinatorEntity[PoolOSCoordinator],
    SwitchEntity,
):
    """Represent one explicit manual IntelliCenter feature switch."""

    _attr_has_entity_name = True

    def __init__(
        self,
        coordinator: PoolOSCoordinator,
        entry: ConfigEntry[PoolOSRuntimeData],
        description: PoolOSSwitchDescription,
    ) -> None:
        super().__init__(coordinator)
        self._runtime = entry.runtime_data
        self._description = description
        self._safety_interlock_off_pending = False

        self._attr_name = description.name
        self._attr_unique_id = (
            f"{entry.entry_id}_native_intellicenter_{description.key}_switch"
        )
        self._attr_icon = description.icon
        self._attr_device_info = {
            "identifiers": {(DOMAIN, f"{entry.entry_id}_native_intellicenter")},
            "name": "PoolOS Native IntelliCenter",
            "manufacturer": "PoolOS",
            "model": "Native IntelliCenter Manual Feature Control",
            "sw_version": INTEGRATION_VERSION,
        }

    @property
    def available(self) -> bool:
        """Return whether native truth and manual command delivery are available."""

        snapshot = self.coordinator.native_intellicenter_snapshot
        manual = self._runtime.manual_intellicenter

        return (
            snapshot is not None
            and bool(getattr(snapshot, "available", False))
            and _native_observation(
                self.coordinator,
                self._description.active_concept,
            )
            is not None
            and manual is not None
            and manual.available
        )

    @property
    def is_on(self) -> bool | None:
        """Return confirmed native IntelliCenter state."""

        value = _native_value(
            self.coordinator,
            self._description.active_concept,
        )
        return value if isinstance(value, bool) else None

    async def async_turn_on(self, **kwargs: Any) -> None:
        """Explicitly turn the feature on."""

        del kwargs

        manual = self._runtime.manual_intellicenter
        if manual is None:
            raise ManualIntelliCenterCommandError(
                "manual IntelliCenter command connection is not configured"
            )

        parent_concept = self._description.required_parent_concept
        if parent_concept is not None:
            parent_active = _native_value(
                self.coordinator,
                parent_concept,
            )
            if parent_active is not True:
                parent_name = (
                    self._description.required_parent_name
                    or parent_concept
                )
                raise ManualIntelliCenterCommandError(
                    f"{self._description.name} cannot be turned on "
                    f"unless {parent_name} is active"
                )

        await manual.async_set_circuit_state(
            self._description.objnam,
            True,
        )

    async def async_turn_off(self, **kwargs: Any) -> None:
        """Explicitly turn the feature off."""

        del kwargs

        manual = self._runtime.manual_intellicenter
        if manual is None:
            raise ManualIntelliCenterCommandError(
                "manual IntelliCenter command connection is not configured"
            )

        await manual.async_set_circuit_state(
            self._description.objnam,
            False,
        )

    async def _async_enforce_parent_interlock(self) -> None:
        """Force the child feature off if its required parent is not active."""

        parent_concept = self._description.required_parent_concept
        if parent_concept is None:
            return

        child_active = _native_value(
            self.coordinator,
            self._description.active_concept,
        )
        parent_active = _native_value(
            self.coordinator,
            parent_concept,
        )

        if child_active is not True:
            self._safety_interlock_off_pending = False
            return

        if parent_active is True:
            self._safety_interlock_off_pending = False
            return

        if self._safety_interlock_off_pending:
            return

        manual = self._runtime.manual_intellicenter
        if manual is None or not manual.available:
            return

        self._safety_interlock_off_pending = True

        try:
            await manual.async_set_circuit_state(
                self._description.objnam,
                False,
            )
        except Exception:
            self._safety_interlock_off_pending = False
            raise

    def _handle_coordinator_update(self) -> None:
        """Enforce safety invariants whenever fresh native state is published."""

        parent_concept = self._description.required_parent_concept

        if parent_concept is not None:
            child_active = _native_value(
                self.coordinator,
                self._description.active_concept,
            )
            parent_active = _native_value(
                self.coordinator,
                parent_concept,
            )

            if child_active is not True or parent_active is True:
                self._safety_interlock_off_pending = False
            elif not self._safety_interlock_off_pending:
                self.hass.async_create_task(
                    self._async_enforce_parent_interlock(),
                    (
                        "PoolOS safety interlock "
                        f"{self._description.key} parent loss"
                    ),
                )

        super()._handle_coordinator_update()

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Expose bounded authority and command-path diagnostics."""

        manual = self._runtime.manual_intellicenter

        return {
            "circuit_objnam": self._description.objnam,
            "canonical_concept": self._description.active_concept,
            "observation_source": "poolos.independent_intellicenter",
            "observation_authority": "native_intellicenter",
            "manual_command_delivery_enabled": (
                manual is not None and manual.available
            ),
            "autonomous_command_delivery_enabled": False,
            "optimistic": False,
            "required_parent_concept": (
                self._description.required_parent_concept
            ),
            "required_parent_name": self._description.required_parent_name,
            "safety_interlock_delivery_enabled": (
                self._description.required_parent_concept is not None
            ),
            "safety_interlock_off_pending": (
                self._safety_interlock_off_pending
            ),
        }


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry[PoolOSRuntimeData],
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up PoolOS native manual feature switches."""

    del hass
    runtime = entry.runtime_data

    async_add_entities(
        PoolOSNativeIntelliCenterSwitch(
            runtime.coordinator,
            entry,
            description,
        )
        for description in SWITCH_DESCRIPTIONS
    )
