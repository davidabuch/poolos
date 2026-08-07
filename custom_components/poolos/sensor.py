"""Read-only diagnostic sensors for the PoolOS Control Center."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from homeassistant.components.sensor import SensorEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity import EntityCategory
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from . import PoolOSRuntimeData
from .const import DOMAIN, INTEGRATION_VERSION
from .coordinator import PoolOSCoordinator


@dataclass(frozen=True, slots=True)
class PoolOSControlCenterSensorDescription:
    """Describe one read-only PoolOS Control Center sensor."""

    key: str
    name: str
    value: Callable[[PoolOSCoordinator, PoolOSRuntimeData], str | int | None]
    attributes: Callable[[PoolOSCoordinator, PoolOSRuntimeData], dict[str, Any]] | None = None
    icon: str | None = None


def _shadow(coordinator: PoolOSCoordinator) -> dict[str, Any]:
    return coordinator.shadow_runtime.diagnostics() or {}


def _snapshot_attributes(coordinator: PoolOSCoordinator, runtime: PoolOSRuntimeData) -> dict[str, Any]:
    snapshot = coordinator.data
    if snapshot is None:
        return {"mapped_observations": 0, "issues": ["no_snapshot"]}
    diagnostics = snapshot.diagnostics()
    return {
        "mapped_observations": diagnostics.get("observation_count", 0),
        "issues": diagnostics.get("issues", []),
        "generated_at": diagnostics.get("generated_at"),
    }



def _recommendation_attributes(coordinator: PoolOSCoordinator, runtime: PoolOSRuntimeData) -> dict[str, Any]:
    recommendation = coordinator.operator_recommendation
    if recommendation is None:
        return {"available": False, "authority": "none", "command_delivery_enabled": False}
    return recommendation.to_dict()


def _shadow_attributes(coordinator: PoolOSCoordinator, runtime: PoolOSRuntimeData) -> dict[str, Any]:
    data = _shadow(coordinator)
    return {
        key: data.get(key)
        for key in (
            "evaluation_id",
            "context_id",
            "plan_id",
            "objective_id",
            "proposed_step_count",
            "proposed_command_count",
            "blocked_reasons",
            "command_delivery_enabled",
        )
    }


SENSORS = (
    PoolOSControlCenterSensorDescription(
        "operating_mode",
        "Operating Mode",
        lambda coordinator, runtime: runtime.operating_mode,
        lambda coordinator, runtime: {
            "authority": "none",
            "command_delivery_enabled": False,
            "integration_version": INTEGRATION_VERSION,
        },
        "mdi:shield-eye",
    ),
    PoolOSControlCenterSensorDescription(
        "commissioning_stage",
        "Commissioning Stage",
        lambda coordinator, runtime: "SHADOW_VALIDATION",
        lambda coordinator, runtime: {
            "completed_milestones": ["11.1A", "11.1B", "11.1C", "11.1D", "11.1E"],
            "next_stage": "OPERATOR_COMMISSIONING",
            "authority_increase_requires_approval": True,
        },
        "mdi:progress-check",
    ),
    PoolOSControlCenterSensorDescription(
        "observation_health",
        "Observation Health",
        lambda coordinator, runtime: (
            "UNKNOWN" if coordinator.data is None else "HEALTHY" if coordinator.data.healthy else "UNHEALTHY"
        ),
        _snapshot_attributes,
        "mdi:heart-pulse",
    ),
    PoolOSControlCenterSensorDescription(
        "shadow_runtime_status",
        "Shadow Runtime Status",
        lambda coordinator, runtime: str(_shadow(coordinator).get("status", "NOT_EVALUATED")).upper(),
        _shadow_attributes,
        "mdi:thought-bubble",
    ),
    PoolOSControlCenterSensorDescription(
        "last_evaluation",
        "Last Evaluation",
        lambda coordinator, runtime: _shadow(coordinator).get("evaluated_at"),
        lambda coordinator, runtime: {
            "evaluation_id": _shadow(coordinator).get("evaluation_id"),
            "observation_fingerprint": _shadow(coordinator).get("observation_fingerprint"),
        },
        "mdi:clock-check-outline",
    ),
    PoolOSControlCenterSensorDescription(
        "last_plan",
        "Last Shadow Plan",
        lambda coordinator, runtime: _shadow(coordinator).get("plan_id") or "NO_PLAN",
        lambda coordinator, runtime: {
            "proposed_step_count": _shadow(coordinator).get("proposed_step_count", 0),
            "proposed_command_count": _shadow(coordinator).get("proposed_command_count", 0),
            "command_delivery_enabled": False,
        },
        "mdi:clipboard-text-clock-outline",
    ),
    PoolOSControlCenterSensorDescription(
        "current_objective",
        "Current Shadow Objective",
        lambda coordinator, runtime: _shadow(coordinator).get("objective_id") or "NO_OBJECTIVE",
        lambda coordinator, runtime: {"authority": "none", "baseline": "maintain_observed_state"},
        "mdi:target",
    ),
    PoolOSControlCenterSensorDescription(
        "operator_recommendation",
        "Operator Recommendation",
        lambda coordinator, runtime: (
            "NOT_AVAILABLE"
            if coordinator.operator_recommendation is None
            else coordinator.operator_recommendation.summary
        ),
        _recommendation_attributes,
        "mdi:account-eye-outline",
    ),
    PoolOSControlCenterSensorDescription(
        "last_explanation",
        "Last Shadow Explanation",
        lambda coordinator, runtime: _shadow(coordinator).get("summary") or "No evaluation available",
        lambda coordinator, runtime: {
            "blocked_reasons": _shadow(coordinator).get("blocked_reasons", []),
            "context_id": _shadow(coordinator).get("context_id"),
        },
        "mdi:text-box-search-outline",
    ),
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry[PoolOSRuntimeData],
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up PoolOS read-only diagnostic sensors."""

    runtime = entry.runtime_data
    async_add_entities(
        PoolOSControlCenterSensor(runtime.coordinator, entry, runtime, description)
        for description in SENSORS
    )


class PoolOSControlCenterSensor(CoordinatorEntity[PoolOSCoordinator], SensorEntity):
    """Expose one read-only PoolOS commissioning diagnostic."""

    _attr_entity_category = EntityCategory.DIAGNOSTIC
    _attr_has_entity_name = True

    def __init__(
        self,
        coordinator: PoolOSCoordinator,
        entry: ConfigEntry[PoolOSRuntimeData],
        runtime: PoolOSRuntimeData,
        description: PoolOSControlCenterSensorDescription,
    ) -> None:
        super().__init__(coordinator)
        self._entry = entry
        self._runtime = runtime
        self._description = description
        self._attr_name = description.name
        self._attr_unique_id = f"{entry.entry_id}_{description.key}"
        self._attr_icon = description.icon
        self._attr_device_info = {
            "identifiers": {(DOMAIN, entry.entry_id)},
            "name": "PoolOS Control Center",
            "manufacturer": "PoolOS",
            "model": "Operational Commissioning Runtime",
            "sw_version": INTEGRATION_VERSION,
        }

    @property
    def native_value(self) -> str | int | datetime | None:
        return self._description.value(self.coordinator, self._runtime)

    @property
    def extra_state_attributes(self) -> dict[str, Any] | None:
        if self._description.attributes is None:
            return None
        return self._description.attributes(self.coordinator, self._runtime)
