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
    value: Callable[[PoolOSCoordinator, PoolOSRuntimeData], str | int | float | None]
    attributes: Callable[[PoolOSCoordinator, PoolOSRuntimeData], dict[str, Any]] | None = None
    icon: str | None = None
    unit: str | None = None


def _shadow(coordinator: PoolOSCoordinator) -> dict[str, Any]:
    return coordinator.shadow_runtime.diagnostics() or {}


def _snapshot_attributes(coordinator: PoolOSCoordinator, runtime: PoolOSRuntimeData) -> dict[str, Any]:
    snapshot = coordinator.data
    if snapshot is None:
        return {
            "healthy": False,
            "mapped_observations": 0,
            "missing_required": [],
            "unavailable_entities": [],
            "stale_entities": [],
            "generated_at": None,
            "diagnostic_reason": "no_snapshot",
        }
    diagnostics = snapshot.diagnostics()
    return {
        "healthy": bool(diagnostics.get("healthy", False)),
        "mapped_observations": diagnostics.get("observation_count", 0),
        "missing_required": diagnostics.get("missing_required", []),
        "unavailable_entities": diagnostics.get("unavailable_entities", []),
        "stale_entities": diagnostics.get("stale_entities", []),
        "freshness_warning": diagnostics.get("freshness_warning", False),
        "startup_grace_active": coordinator.in_startup_health_grace(),
        "startup_grace_until": coordinator.health_incident_diagnostics()["startup_grace_until"],
        "generated_at": diagnostics.get("generated_at"),
    }




def _health_incident_attributes(
    coordinator: PoolOSCoordinator, runtime: PoolOSRuntimeData
) -> dict[str, Any]:
    """Expose the current-session health incident latch."""

    return coordinator.health_incident_diagnostics()


def _behavioral_attributes(coordinator: PoolOSCoordinator, runtime: PoolOSRuntimeData) -> dict[str, Any]:
    report = coordinator.behavioral_inference_report
    if report is None:
        return {"available": False, "source_event_count": 0}
    data = report.to_dict()
    return {
        "available": True,
        "confidence": data["current_state_confidence"],
        "source_event_count": data["source_event_count"],
        "generated_from_start": data["generated_from_start"],
        "generated_from_end": data["generated_from_end"],
        "recent_events": data["events"][-10:],
    }


def _solar_inference_attributes(coordinator: PoolOSCoordinator, runtime: PoolOSRuntimeData) -> dict[str, Any]:
    report = coordinator.behavioral_inference_report
    if report is None:
        return {"available": False}
    return {"available": True, **report.to_dict()["solar"]}



def _retrospective_attributes(coordinator: PoolOSCoordinator, runtime: PoolOSRuntimeData) -> dict[str, Any]:
    report = coordinator.current_daily_retrospective
    if report is None:
        return {"available": False, "authority": "none", "command_delivery_enabled": False}
    data = report.to_dict()
    actual = data["actual"]
    completed = coordinator.latest_completed_daily_retrospective
    return {
        "available": True,
        "report_id": data["report_id"],
        "report_date": data["report_date"],
        "complete_day": data["complete_day"],
        "coverage_ratio": actual["coverage_ratio"],
        "pump_runtime_seconds": actual["pump_runtime_seconds"],
        "runtime_by_mode_seconds": actual["runtime_by_mode_seconds"],
        "priming_count": actual["priming_count"],
        "inferred_priming_duration_seconds": actual["inferred_priming_duration_seconds"],
        "spa_runtime_seconds": actual["spa_runtime_seconds"],
        "solar_runtime_seconds": actual["solar_runtime_seconds"],
        "heater_runtime_seconds": actual["heater_runtime_seconds"],
        "filtration_interruptions": actual["filtration_interruptions"],
        "average_running_rpm": actual["average_running_rpm"],
        "pump_energy_kwh": actual["pump_energy_kwh"],
        "temperatures": actual["temperatures"],
        "soak_quality": data["soak_quality"],
        "incidents": data["incidents"],
        "solar_learning": data["solar_learning"],
        "daily_assessment": data["daily_assessment"],
        "latest_completed_report_id": None if completed is None else completed.report_id,
        "latest_completed_report_date": None if completed is None else completed.report_date,
        "authority": "none",
        "command_delivery_enabled": False,
    }


def _quality_attributes(
    coordinator: PoolOSCoordinator, runtime: PoolOSRuntimeData
) -> dict[str, Any]:
    report = coordinator.current_daily_retrospective
    if report is None:
        return {"available": False, "authority": "none"}
    return {
        "available": True,
        "report_id": report.report_id,
        "report_date": report.report_date,
        **report.soak_quality.to_dict(),
        "authority": "none",
        "command_delivery_enabled": False,
    }


def _incidents_attributes(
    coordinator: PoolOSCoordinator, runtime: PoolOSRuntimeData
) -> dict[str, Any]:
    report = coordinator.current_daily_retrospective
    if report is None:
        return {"available": False, "incidents": [], "authority": "none"}
    return {
        "available": True,
        "report_id": report.report_id,
        "report_date": report.report_date,
        "incidents": [item.to_dict() for item in report.incidents],
        "authority": "none",
        "command_delivery_enabled": False,
    }


def _solar_learning_attributes(
    coordinator: PoolOSCoordinator, runtime: PoolOSRuntimeData
) -> dict[str, Any]:
    report = coordinator.current_daily_retrospective
    if report is None:
        return {"available": False, "authority": "none"}
    return {
        "available": True,
        "report_id": report.report_id,
        "report_date": report.report_date,
        **report.solar_learning.to_dict(),
        "authority": "none",
        "command_delivery_enabled": False,
    }


def _counterfactual_attributes(coordinator: PoolOSCoordinator, runtime: PoolOSRuntimeData) -> dict[str, Any]:
    report = coordinator.current_daily_retrospective
    if report is None:
        return {"available": False, "authority": "none", "command_delivery_enabled": False}
    data = report.counterfactual.to_dict()
    return {"available": True, "report_id": report.report_id, "report_date": report.report_date, **data}

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


def _observation_value(coordinator: PoolOSCoordinator, observation_id: str) -> Any:
    snapshot = coordinator.data
    if snapshot is None:
        return None
    for observation in snapshot.observations:
        if observation.observation_id == observation_id:
            return observation.value
    return None


def _display_observation_value(coordinator: PoolOSCoordinator, observation_id: str) -> Any:
    """Return operator-friendly telemetry without changing recorded evidence."""

    value = _observation_value(coordinator, observation_id)

    if observation_id in {"pool_light.color_mode", "pool_light.effect"}:
        light_active = _observation_value(coordinator, "pool_light.active")
        if light_active is False:
            return "OFF"
        if value is None:
            return "UNKNOWN"

    if isinstance(value, bool):
        return "ON" if value else "OFF"
    return value


def _recorder_attributes(coordinator: PoolOSCoordinator, runtime: PoolOSRuntimeData) -> dict[str, Any]:
    return {
        **coordinator.observation_recorder.diagnostics(),
        **coordinator.evidence_exporter.diagnostics(),
        "authority": "none",
        "command_delivery_enabled": False,
    }


TELEMETRY = (
    ("pool_active", "Pool Active", "pool.active", "mdi:pool"),
    ("spa_active", "Spa Active", "spa.active", "mdi:hot-tub"),
    ("pool_command_active", "Pool Command Active", "pool.command_active", "mdi:toggle-switch-outline"),
    ("spa_command_active", "Spa Command Active", "spa.command_active", "mdi:toggle-switch-outline"),
    ("pump_rpm", "Pump RPM", "pump.rpm", "mdi:pump"),
    ("pump_gpm", "Pump GPM", "pump.gpm", "mdi:waves-arrow-right"),
    ("pump_power", "Pump Power", "pump.power", "mdi:flash"),
    ("pool_temperature", "Pool Temperature", "pool.temperature", "mdi:thermometer-water"),
    ("pool_target_temperature", "Pool Target Temperature", "pool.target_temperature", "mdi:thermometer-check"),
    ("spa_temperature", "Spa Temperature", "spa.temperature", "mdi:thermometer-water"),
    ("spa_target_temperature", "Spa Target Temperature", "spa.target_temperature", "mdi:thermometer-check"),
    ("water_temperature", "Water Temperature", "water.temperature", "mdi:coolant-temperature"),
    ("solar_temperature", "Solar Roof Temperature", "solar.temperature", "mdi:solar-power"),
    ("air_temperature", "Air Temperature", "air.temperature", "mdi:thermometer"),
    ("solar_active", "Solar Active", "solar.active", "mdi:solar-panel-large"),
    ("heater_active", "Gas Heater Active", "heater.active", "mdi:fire"),
    ("pool_heating_demand", "Pool Heating Demand", "pool.heating_demand_active", "mdi:heat-wave"),
    ("spa_heating_demand", "Spa Heating Demand", "spa.heating_demand_active", "mdi:heat-wave"),
    ("solar_preferred_active", "Solar Preferred", "solar_preferred.active", "mdi:sun-compass"),
    ("waterfall_active", "Waterfall Active", "waterfall.active", "mdi:waterfall"),
    ("jets_active", "Jets Active", "jets.active", "mdi:weather-windy"),
    ("slide_active", "Slide Active", "slide.active", "mdi:slide"),
    ("grid_available", "Grid Available", "grid.available", "mdi:transmission-tower"),
    ("grid_outage_active", "Grid Outage Active", "grid.outage_active", "mdi:transmission-tower-off"),
    ("pool_light_active", "Pool Light Active", "pool_light.active", "mdi:pool"),
    ("pool_light_color_mode", "Pool Light Color Mode", "pool_light.color_mode", "mdi:palette"),
    ("pool_light_effect", "Pool Light Scene / Effect", "pool_light.effect", "mdi:creation"),
)


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
        lambda coordinator, runtime: "HIGH_FIDELITY_OBSERVATION_READY",
        lambda coordinator, runtime: {
            "completed_milestones": [
                "11.1A", "11.1B", "11.1C", "11.1D", "11.1E",
                "11.2A", "11.2B", "11.2C", "11.2D", "11.2E",
                "11.3A", "11.3B", "11.3C", "11.3D", "11.4A",
                "11.5",
            ],
            "next_stage": "PUBLIC_RELEASE_AND_HA_COMMISSIONING_AUDIT",
            "authority_increase_requires_approval": True,
        },
        "mdi:progress-check",
    ),
    PoolOSControlCenterSensorDescription(
        "observation_health",
        "Observation Health",
        lambda coordinator, runtime: coordinator.observation_health_state(),
        _snapshot_attributes,
        "mdi:heart-pulse",
    ),
    PoolOSControlCenterSensorDescription(
        "health_incident_since_restart",
        "Health Incident Since Reset",
        lambda coordinator, runtime: (
            "UNHEALTHY SEEN"
            if coordinator.health_incident_diagnostics()["unhealthy_seen_since_start"]
            else "NO INCIDENTS"
        ),
        _health_incident_attributes,
        "mdi:alert-circle-check-outline",
    ),
    PoolOSControlCenterSensorDescription(
        "observation_quality",
        "Observation Quality",
        lambda coordinator, runtime: (
            "NOT_AVAILABLE"
            if coordinator.current_daily_retrospective is None
            else coordinator.current_daily_retrospective.soak_quality.status.value
        ),
        _quality_attributes,
        "mdi:chart-timeline-variant-shimmer",
    ),
    PoolOSControlCenterSensorDescription(
        "observation_coverage",
        "Observation Coverage",
        lambda coordinator, runtime: (
            None
            if coordinator.current_daily_retrospective is None
            else round(
                coordinator.current_daily_retrospective.soak_quality.observation_coverage_ratio
                * 100,
                1,
            )
        ),
        _quality_attributes,
        "mdi:percent-circle-outline",
        "%",
    ),
    PoolOSControlCenterSensorDescription(
        "observation_incidents_today",
        "Observation Incidents Today",
        lambda coordinator, runtime: (
            None
            if coordinator.current_daily_retrospective is None
            else len(coordinator.current_daily_retrospective.incidents)
        ),
        _incidents_attributes,
        "mdi:alert-decagram-outline",
    ),
    PoolOSControlCenterSensorDescription(
        "solar_transitions_today",
        "Solar Transitions Today",
        lambda coordinator, runtime: (
            None
            if coordinator.current_daily_retrospective is None
            else (
                coordinator.current_daily_retrospective.solar_learning.activation_count
                + coordinator.current_daily_retrospective.solar_learning.deactivation_count
            )
        ),
        _solar_learning_attributes,
        "mdi:solar-panel-large",
    ),
    PoolOSControlCenterSensorDescription(
        "solar_learning_quality",
        "Solar Learning Quality",
        lambda coordinator, runtime: (
            "NOT_AVAILABLE"
            if coordinator.current_daily_retrospective is None
            else coordinator.current_daily_retrospective.solar_learning.learning_quality.value
        ),
        _solar_learning_attributes,
        "mdi:book-check-outline",
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
        "inferred_operating_state",
        "Inferred Operating State",
        lambda coordinator, runtime: (
            "NOT_AVAILABLE"
            if coordinator.behavioral_inference_report is None
            else coordinator.behavioral_inference_report.current_state.value
        ),
        _behavioral_attributes,
        "mdi:state-machine",
    ),
    PoolOSControlCenterSensorDescription(
        "solar_behavior_inference",
        "Solar Behavior Inference",
        lambda coordinator, runtime: (
            "NOT_AVAILABLE"
            if coordinator.behavioral_inference_report is None
            else coordinator.behavioral_inference_report.solar.assessment
        ),
        _solar_inference_attributes,
        "mdi:solar-power-variant-outline",
    ),
    PoolOSControlCenterSensorDescription(
        "daily_operational_retrospective",
        "Daily Operational Retrospective",
        lambda coordinator, runtime: (
            "NOT_AVAILABLE"
            if coordinator.current_daily_retrospective is None
            else coordinator.current_daily_retrospective.report_date
        ),
        _retrospective_attributes,
        "mdi:calendar-search",
    ),
    PoolOSControlCenterSensorDescription(
        "daily_counterfactual_report",
        "Daily Counterfactual Report",
        lambda coordinator, runtime: (
            "NOT_AVAILABLE"
            if coordinator.current_daily_retrospective is None
            else coordinator.current_daily_retrospective.counterfactual.status.value
        ),
        _counterfactual_attributes,
        "mdi:compare-horizontal",
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
        "recorder_status",
        "Recorder Status",
        lambda coordinator, runtime: "ERROR" if coordinator.evidence_exporter.last_error else "RECORDING",
        _recorder_attributes,
        "mdi:file-chart-outline",
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
) + tuple(
    PoolOSControlCenterSensorDescription(
        key, name, lambda coordinator, runtime, observation_id=observation_id: _display_observation_value(coordinator, observation_id), icon=icon
    )
    for key, name, observation_id, icon in TELEMETRY
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
        self._attr_native_unit_of_measurement = description.unit
        self._attr_device_info = {
            "identifiers": {(DOMAIN, entry.entry_id)},
            "name": "PoolOS Control Center",
            "manufacturer": "PoolOS",
            "model": "Operational Commissioning Runtime",
            "sw_version": INTEGRATION_VERSION,
        }

    @property
    def native_value(self) -> str | int | float | datetime | None:
        return self._description.value(self.coordinator, self._runtime)

    @property
    def extra_state_attributes(self) -> dict[str, Any] | None:
        if self._description.attributes is None:
            return None
        return self._description.attributes(self.coordinator, self._runtime)
