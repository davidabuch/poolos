"""Read-only diagnostic sensors for the PoolOS Control Center."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
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
from poolos.integration import ThermalBody
from poolos.solar_recorder_diagnostics import (
    solar_learning_quality_state,
    solar_learning_recorder_attributes,
    solar_transitions_recorder_attributes,
    solar_transitions_state,
)


@dataclass(frozen=True, slots=True)
class PoolOSControlCenterSensorDescription:
    """Describe one read-only PoolOS Control Center sensor."""

    key: str
    name: str
    value: Callable[[PoolOSCoordinator, PoolOSRuntimeData], str | int | float | None]
    attributes: Callable[[PoolOSCoordinator, PoolOSRuntimeData], dict[str, Any]] | None = None
    icon: str | None = None
    unit: str | None = None


@dataclass(frozen=True, slots=True)
class PoolOSNativeSensorDescription:
    """Describe one read-only native IntelliCenter sensor."""

    concept: str
    name: str
    icon: str | None = None
    unit: str | None = None
    diagnostic: bool = False


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


def _native_observation_value(
    coordinator: PoolOSCoordinator,
    concept: str,
) -> str | int | float | None:
    observation = _native_observation(coordinator, concept)
    if observation is None:
        return None
    return observation.value


def _native_observation_attributes(
    coordinator: PoolOSCoordinator,
    concept: str,
) -> dict[str, Any]:
    observation = _native_observation(coordinator, concept)
    snapshot = coordinator.native_intellicenter_snapshot

    if observation is None:
        return {
            "canonical_concept": concept,
            "source": "poolos.independent_intellicenter",
            "available": False,
            "authority": "none",
            "command_delivery_enabled": False,
            "read_only": True,
        }

    quality = observation.quality
    quality_value = getattr(quality, "value", str(quality))

    return {
        "canonical_concept": concept,
        "source": "poolos.independent_intellicenter",
        "source_id": observation.source_id,
        "observed_at": observation.observed_at.isoformat(),
        "quality": quality_value,
        "available": bool(getattr(snapshot, "available", False)),
        "authority": "none",
        "command_delivery_enabled": False,
        "read_only": True,
    }


NATIVE_SENSORS: tuple[PoolOSNativeSensorDescription, ...] = (
    PoolOSNativeSensorDescription("air.temperature", "Air Temperature", "mdi:thermometer", "°F"),
    PoolOSNativeSensorDescription("pool.raw_heater_id", "Pool Heater ID", "mdi:identifier", diagnostic=True),
    PoolOSNativeSensorDescription("pool.raw_htmode", "Pool Heat Mode Raw", "mdi:code-tags", diagnostic=True),
    PoolOSNativeSensorDescription("pool.target_temperature", "Pool Target Temperature", "mdi:thermometer-check", "°F"),
    PoolOSNativeSensorDescription("pool.temperature", "Pool Temperature", "mdi:pool-thermometer", "°F"),
    PoolOSNativeSensorDescription("pump.gpm", "Pump Flow Rate", "mdi:water-pump", "gal/min"),
    PoolOSNativeSensorDescription("pump.power", "Pump Power", "mdi:flash", "W"),
    PoolOSNativeSensorDescription("pump.rpm", "Pump RPM", "mdi:speedometer", "rpm"),
    PoolOSNativeSensorDescription("solar.temperature", "Solar Temperature", "mdi:solar-power", "°F"),
    PoolOSNativeSensorDescription("spa.raw_heater_id", "Spa Heater ID", "mdi:identifier", diagnostic=True),
    PoolOSNativeSensorDescription("spa.raw_htmode", "Spa Heat Mode Raw", "mdi:code-tags", diagnostic=True),
    PoolOSNativeSensorDescription("spa.target_temperature", "Spa Target Temperature", "mdi:thermometer-check", "°F"),
    PoolOSNativeSensorDescription("spa.temperature", "Spa Temperature", "mdi:hot-tub", "°F"),
    PoolOSNativeSensorDescription("water.temperature", "Water Temperature", "mdi:thermometer-water", "°F"),
)


class PoolOSNativeIntelliCenterSensor(
    CoordinatorEntity[PoolOSCoordinator],
    SensorEntity,
):
    """Expose one canonical native IntelliCenter observation."""

    _attr_has_entity_name = True

    def __init__(
        self,
        coordinator: PoolOSCoordinator,
        entry: ConfigEntry[PoolOSRuntimeData],
        description: PoolOSNativeSensorDescription,
    ) -> None:
        super().__init__(coordinator)
        self._description = description
        self._attr_name = description.name
        key = description.concept.replace(".", "_")
        self._attr_unique_id = f"{entry.entry_id}_native_intellicenter_{key}"
        self._attr_icon = description.icon
        self._attr_native_unit_of_measurement = description.unit
        if description.diagnostic:
            self._attr_entity_category = EntityCategory.DIAGNOSTIC
        self._attr_device_info = {
            "identifiers": {(DOMAIN, f"{entry.entry_id}_native_intellicenter")},
            "name": "PoolOS Native IntelliCenter",
            "manufacturer": "PoolOS",
            "model": "Independent IntelliCenter Read-Only Transport",
            "sw_version": INTEGRATION_VERSION,
        }

    @property
    def native_value(self) -> str | int | float | None:
        return _native_observation_value(
            self.coordinator,
            self._description.concept,
        )

    @property
    def available(self) -> bool:
        observation = _native_observation(
            self.coordinator,
            self._description.concept,
        )
        snapshot = self.coordinator.native_intellicenter_snapshot
        return (
            snapshot is not None
            and bool(getattr(snapshot, "available", False))
            and observation is not None
        )

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        return _native_observation_attributes(
            self.coordinator,
            self._description.concept,
        )


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
        "authoritative_source": diagnostics.get(
            "authoritative_source",
            "unknown",
        ),
        "startup_grace_active": coordinator.in_startup_health_grace(),
        "startup_grace_until": coordinator.health_incident_diagnostics()["startup_grace_until"],
        "generated_at": diagnostics.get("generated_at"),
    }




def _health_incident_attributes(
    coordinator: PoolOSCoordinator, runtime: PoolOSRuntimeData
) -> dict[str, Any]:
    """Expose the current-session health incident latch."""

    return coordinator.health_incident_diagnostics()


def _expected_outage_annotation_attributes(
    coordinator: PoolOSCoordinator, runtime: PoolOSRuntimeData
) -> dict[str, Any]:
    return coordinator.expected_outage_annotation_diagnostics()


def _native_intellicenter_attributes(
    coordinator: PoolOSCoordinator, runtime: PoolOSRuntimeData
) -> dict[str, Any]:
    snapshot = coordinator.native_intellicenter_snapshot
    if snapshot is None:
        return {
            "status": "INITIALIZING",
            "authority": "none",
            "command_delivery_enabled": False,
        }
    return dict(snapshot.diagnostics())


def _native_inventory_attributes(
    coordinator: PoolOSCoordinator, runtime: PoolOSRuntimeData
) -> dict[str, Any]:
    inventory = coordinator.native_intellicenter_inventory
    if inventory is None:
        return {
            "available": False,
            "authority": "none",
            "command_delivery_enabled": False,
        }
    return {
        "available": True,
        **dict(inventory),
        "complete_inventory_export": dict(
            coordinator.native_inventory_exporter.diagnostics()
        ),
    }


def _independent_intellicenter_transport_attributes(
    coordinator: PoolOSCoordinator, runtime: PoolOSRuntimeData
) -> dict[str, Any]:
    transport = coordinator.independent_intellicenter_transport
    if transport is None:
        return {
            "state": "UNAVAILABLE",
            "configured": False,
            "authority": "none",
            "command_delivery_enabled": False,
            "physical_delivery_enabled": False,
            "read_only_safety_mode": True,
        }
    return {
        "configured": True,
        **dict(transport.diagnostics(generated_at=datetime.now(UTC))),
    }


def _native_mapped_concept_attributes(
    coordinator: PoolOSCoordinator, runtime: PoolOSRuntimeData
) -> dict[str, Any]:
    snapshot = coordinator.native_intellicenter_snapshot
    if snapshot is None:
        return {
            "available": False,
            "mapped_concept_count": 0,
            "mapped_concepts": [],
            "authority": "none",
            "command_delivery_enabled": False,
        }
    mapped = [dict(item) for item in snapshot.mapped_concept_diagnostics()]
    return {
        "available": snapshot.available,
        "mapped_concept_count": len(mapped),
        "mapped_concepts": mapped,
        "missing_concept_count": len(snapshot.missing_concepts),
        "missing_concepts": list(snapshot.missing_concepts),
        "authority": "none",
        "command_delivery_enabled": False,
    }


def _native_parity_attributes(
    coordinator: PoolOSCoordinator, runtime: PoolOSRuntimeData
) -> dict[str, Any]:
    report = coordinator.native_intellicenter_parity_report
    if report is None:
        return {
            "available": False,
            "authoritative_source": "home_assistant",
            "authority": "none",
            "command_delivery_enabled": False,
        }
    issues = tuple(item for item in report.details if item.status.value != "MATCH")
    return {
        "available": True,
        **report.to_dict(include_details=False),
        "issue_concepts": [
            {"concept": item.concept, "status": item.status.value}
            for item in issues
        ],
    }


def _native_parity_issue_attributes(
    coordinator: PoolOSCoordinator, runtime: PoolOSRuntimeData
) -> dict[str, Any]:
    report = coordinator.native_intellicenter_parity_report
    if report is None:
        return {
            "available": False,
            "issues": [],
            "authoritative_source": "home_assistant",
            "authority": "none",
            "command_delivery_enabled": False,
        }
    return report.diagnostic_attributes()


def _native_parity_commissioning_attributes(
    coordinator: PoolOSCoordinator, runtime: PoolOSRuntimeData
) -> dict[str, Any]:
    del runtime
    return coordinator.native_parity_commissioning_summary.diagnostic_attributes(
        history_path=str(coordinator.native_parity_commissioning_store.history_path),
        last_error=coordinator.native_parity_commissioning_store.last_error,
    )


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



def _retrospective_attributes(
    coordinator: PoolOSCoordinator, runtime: PoolOSRuntimeData
) -> dict[str, Any]:
    """Expose a compact HA summary; full evidence remains in PoolOS storage."""

    report = coordinator.current_daily_retrospective
    if report is None:
        return {
            "available": False,
            "authority": "none",
            "command_delivery_enabled": False,
        }

    data = report.to_dict()
    actual = data["actual"]
    quality = report.soak_quality
    solar = report.solar_learning
    completed = coordinator.latest_completed_daily_retrospective

    return {
        "available": True,
        "report_id": report.report_id,
        "report_date": report.report_date,
        "complete_day": data["complete_day"],
        "coverage_ratio": actual["coverage_ratio"],
        "pump_runtime_seconds": actual["pump_runtime_seconds"],
        "runtime_by_mode_seconds": actual["runtime_by_mode_seconds"],
        "priming_count": actual["priming_count"],
        "inferred_priming_duration_seconds": actual[
            "inferred_priming_duration_seconds"
        ],
        "spa_runtime_seconds": actual["spa_runtime_seconds"],
        "solar_runtime_seconds": actual["solar_runtime_seconds"],
        "heater_runtime_seconds": actual["heater_runtime_seconds"],
        "filtration_interruptions": actual["filtration_interruptions"],
        "average_running_rpm": actual["average_running_rpm"],
        "pump_energy_kwh": actual["pump_energy_kwh"],
        "temperatures": actual["temperatures"],
        "observation_quality": quality.status.value,
        "observation_coverage_ratio": round(
            quality.observation_coverage_ratio, 6
        ),
        "incident_count": quality.incident_count,
        "expected_incident_count": quality.expected_incident_count,
        "unexpected_incident_count": quality.unexpected_incident_count,
        "solar_learning_quality": solar.learning_quality.value,
        "solar_usable_for_learning": solar.usable_for_learning,
        "solar_activation_count": solar.activation_count,
        "solar_deactivation_count": solar.deactivation_count,
        "complete_solar_episode_count": solar.complete_episode_count,
        "open_solar_episode_count": solar.open_episode_count,
        "daily_assessment": data["daily_assessment"],
        "latest_completed_report_id": (
            None if completed is None else completed.report_id
        ),
        "latest_completed_report_date": (
            None if completed is None else completed.report_date
        ),
        "authority": "none",
        "command_delivery_enabled": False,
    }


def _quality_attributes(
    coordinator: PoolOSCoordinator, runtime: PoolOSRuntimeData
) -> dict[str, Any]:
    """Expose compact Recorder-safe soak-quality diagnostics."""

    report = coordinator.current_daily_retrospective
    if report is None:
        return {"available": False, "authority": "none"}

    quality = report.soak_quality
    return {
        "available": True,
        "report_id": report.report_id,
        "report_date": report.report_date,
        "status": quality.status.value,
        "observation_coverage_ratio": round(
            quality.observation_coverage_ratio, 6
        ),
        "healthy_observation_coverage_ratio": round(
            quality.healthy_observation_coverage_ratio, 6
        ),
        "commissioning_healthy_coverage_ratio": round(
            quality.commissioning_healthy_coverage_ratio, 6
        ),
        "largest_evidence_gap_seconds": round(
            quality.largest_evidence_gap_seconds, 3
        ),
        "unhealthy_duration_seconds": round(
            quality.unhealthy_duration_seconds, 3
        ),
        "unavailable_duration_seconds": round(
            quality.unavailable_duration_seconds, 3
        ),
        "stale_duration_seconds": round(
            quality.stale_duration_seconds, 3
        ),
        "incident_count": quality.incident_count,
        "expected_incident_count": quality.expected_incident_count,
        "unexpected_incident_count": quality.unexpected_incident_count,
        "expected_outage_duration_seconds": round(
            quality.expected_outage_duration_seconds, 3
        ),
        "unexpected_unhealthy_duration_seconds": round(
            quality.unexpected_unhealthy_duration_seconds, 3
        ),
        "reason_codes": [item.value for item in quality.reason_codes],
        "assessment": quality.assessment,
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


def _solar_transitions_attributes(
    coordinator: PoolOSCoordinator, runtime: PoolOSRuntimeData
) -> dict[str, Any]:
    del runtime
    return solar_transitions_recorder_attributes(
        coordinator.current_daily_retrospective
    )


def _solar_learning_attributes(
    coordinator: PoolOSCoordinator, runtime: PoolOSRuntimeData
) -> dict[str, Any]:
    del runtime
    return solar_learning_recorder_attributes(
        coordinator.current_daily_retrospective
    )


def _multiday_commissioning_attributes(
    coordinator: PoolOSCoordinator, runtime: PoolOSRuntimeData
) -> dict[str, Any]:
    report = coordinator.multiday_commissioning_report
    if report is None:
        return {
            "available": False,
            "authority": "none",
            "policy_created": False,
            "command_delivery_enabled": False,
        }
    return {"available": True, **report.to_dict()}


def _multiday_count_attributes(
    coordinator: PoolOSCoordinator, runtime: PoolOSRuntimeData
) -> dict[str, Any]:
    report = coordinator.multiday_commissioning_report
    if report is None:
        return {
            "available": False,
            "authority": "none",
            "policy_created": False,
            "command_delivery_enabled": False,
        }
    return {
        "available": True,
        "report_id": report.report_id,
        "start_date": report.start_date.isoformat(),
        "end_date": report.end_date.isoformat(),
        "evidence_status": report.evidence_status.value,
        "authority": "none",
        "policy_created": False,
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
        "thermal_execution_readiness",
        "Thermal Execution Readiness",
        lambda coordinator, runtime: (
            "UNAVAILABLE"
            if runtime.thermal_runtime.assessment is None
            else (
                "WOULD_AUTHORIZE"
                if runtime.thermal_runtime.assessment.pool.actual_authorization.authorized
                or runtime.thermal_runtime.assessment.hot_tub.actual_authorization.authorized
                else "WOULD_DENY"
            )
        ),
        lambda coordinator, runtime: runtime.thermal_runtime.global_diagnostics(),
        "mdi:shield-search",
    ),
    PoolOSControlCenterSensorDescription(
        "pool_thermal_plan",
        "Pool Thermal Plan",
        lambda coordinator, runtime: (
            "UNAVAILABLE"
            if runtime.thermal_runtime.assessment is None
            else runtime.thermal_runtime.assessment.pool.plan.disposition.value.upper()
        ),
        lambda coordinator, runtime: runtime.thermal_runtime.body_diagnostics(
            ThermalBody.POOL
        ),
        "mdi:pool-thermometer",
    ),
    PoolOSControlCenterSensorDescription(
        "hot_tub_thermal_plan",
        "Hot Tub Thermal Plan",
        lambda coordinator, runtime: (
            "UNAVAILABLE"
            if runtime.thermal_runtime.assessment is None
            else runtime.thermal_runtime.assessment.hot_tub.plan.disposition.value.upper()
        ),
        lambda coordinator, runtime: runtime.thermal_runtime.body_diagnostics(
            ThermalBody.HOT_TUB
        ),
        "mdi:hot-tub",
    ),
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
                "11.5.1", "11.6", "11.6.1", "12.0A",
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
        "expected_outage_annotation",
        "Expected Outage Annotation",
        lambda coordinator, runtime: coordinator.expected_outage_annotation_diagnostics()[
            "state"
        ],
        _expected_outage_annotation_attributes,
        "mdi:clipboard-text-clock-outline",
    ),
    PoolOSControlCenterSensorDescription(
        "independent_intellicenter_transport",
        "Independent IntelliCenter Read-Only Transport",
        lambda coordinator, runtime: (
            "UNAVAILABLE"
            if coordinator.independent_intellicenter_transport is None
            else coordinator.independent_intellicenter_transport.state.value
        ),
        _independent_intellicenter_transport_attributes,
        "mdi:lan-pending",
    ),
    PoolOSControlCenterSensorDescription(
        "native_intellicenter_status",
        "Native IntelliCenter Status",
        lambda coordinator, runtime: (
            "INITIALIZING"
            if coordinator.native_intellicenter_snapshot is None
            else coordinator.native_intellicenter_snapshot.status.value
        ),
        _native_intellicenter_attributes,
        "mdi:lan-connect",
    ),
    PoolOSControlCenterSensorDescription(
        "native_intellicenter_parity",
        "Native IntelliCenter Parity",
        lambda coordinator, runtime: (
            None
            if coordinator.native_intellicenter_parity_report is None
            else round(
                coordinator.native_intellicenter_parity_report.parity_ratio * 100,
                1,
            )
        ),
        _native_parity_attributes,
        "mdi:compare-horizontal",
        "%",
    ),
    PoolOSControlCenterSensorDescription(
        "native_intellicenter_matched_concepts",
        "Native IntelliCenter Matched Concepts",
        lambda coordinator, runtime: (
            None
            if coordinator.native_intellicenter_parity_report is None
            else coordinator.native_intellicenter_parity_report.match_count
        ),
        _native_parity_attributes,
        "mdi:check-decagram-outline",
    ),
    PoolOSControlCenterSensorDescription(
        "native_intellicenter_mismatches",
        "Native IntelliCenter Mismatches",
        lambda coordinator, runtime: (
            None
            if coordinator.native_intellicenter_parity_report is None
            else (
                coordinator.native_intellicenter_parity_report.compared_concept_count
                - coordinator.native_intellicenter_parity_report.match_count
            )
        ),
        _native_parity_attributes,
        "mdi:alert-circle-outline",
    ),
    PoolOSControlCenterSensorDescription(
        "native_intellicenter_snapshot_inventory",
        "Native IntelliCenter Snapshot Inventory",
        lambda coordinator, runtime: (
            None
            if coordinator.native_intellicenter_inventory is None
            else int(
                coordinator.native_intellicenter_inventory.get(
                    "total_native_object_count", 0
                )
            )
        ),
        _native_inventory_attributes,
        "mdi:format-list-bulleted-type",
    ),
    PoolOSControlCenterSensorDescription(
        "native_intellicenter_mapped_concepts",
        "Native IntelliCenter Mapped Concepts",
        lambda coordinator, runtime: (
            0
            if coordinator.native_intellicenter_snapshot is None
            else len(coordinator.native_intellicenter_snapshot.observations)
        ),
        _native_mapped_concept_attributes,
        "mdi:map-check-outline",
    ),
    PoolOSControlCenterSensorDescription(
        "native_intellicenter_parity_issues",
        "Native IntelliCenter Parity Issues",
        lambda coordinator, runtime: (
            None
            if coordinator.native_intellicenter_parity_report is None
            else sum(
                item.status.value != "MATCH"
                for item in coordinator.native_intellicenter_parity_report.details
            )
        ),
        _native_parity_issue_attributes,
        "mdi:text-search",
    ),
    PoolOSControlCenterSensorDescription(
        "native_parity_commissioning",
        "Native Parity Commissioning",
        lambda coordinator, runtime: (
            coordinator.native_parity_commissioning_summary.status.value
        ),
        _native_parity_commissioning_attributes,
        "mdi:timeline-check-outline",
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
        lambda coordinator, runtime: solar_transitions_state(
            coordinator.current_daily_retrospective
        ),
        _solar_transitions_attributes,
        "mdi:solar-panel-large",
    ),
    PoolOSControlCenterSensorDescription(
        "solar_learning_quality",
        "Solar Learning Quality",
        lambda coordinator, runtime: solar_learning_quality_state(
            coordinator.current_daily_retrospective
        ),
        _solar_learning_attributes,
        "mdi:book-check-outline",
    ),
    PoolOSControlCenterSensorDescription(
        "commissioning_evidence_status",
        "Commissioning Evidence Status",
        lambda coordinator, runtime: (
            "NOT_AVAILABLE"
            if coordinator.multiday_commissioning_report is None
            else coordinator.multiday_commissioning_report.evidence_status.value
        ),
        _multiday_commissioning_attributes,
        "mdi:clipboard-check-multiple-outline",
    ),
    PoolOSControlCenterSensorDescription(
        "good_observation_days",
        "Good Observation Days",
        lambda coordinator, runtime: (
            None
            if coordinator.multiday_commissioning_report is None
            else coordinator.multiday_commissioning_report.good_days
        ),
        _multiday_count_attributes,
        "mdi:calendar-check-outline",
    ),
    PoolOSControlCenterSensorDescription(
        "usable_solar_learning_days",
        "Usable Solar Learning Days",
        lambda coordinator, runtime: (
            None
            if coordinator.multiday_commissioning_report is None
            else coordinator.multiday_commissioning_report.usable_solar_learning_days
        ),
        _multiday_count_attributes,
        "mdi:calendar-star",
    ),
    PoolOSControlCenterSensorDescription(
        "complete_solar_episodes",
        "Complete Solar Episodes",
        lambda coordinator, runtime: (
            None
            if coordinator.multiday_commissioning_report is None
            else coordinator.multiday_commissioning_report.complete_solar_episode_count
        ),
        _multiday_count_attributes,
        "mdi:solar-panel-large",
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
    async_add_entities(
        PoolOSNativeIntelliCenterSensor(
            runtime.coordinator,
            entry,
            description,
        )
        for description in NATIVE_SENSORS
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
