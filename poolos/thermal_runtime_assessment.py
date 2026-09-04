"""Side-effect-free current thermal planning and authorization diagnostics.

This module assembles Phase 1 plans and evaluates Phase 2 authorization gates.
It deliberately imports no execution engine or delivery port and cannot issue
commands.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta
from enum import StrEnum
from hashlib import sha256
import json
from types import MappingProxyType
from typing import Any, Mapping

from .integration import PhysicalHeatMode, ThermalBody
from .native_configuration_policy import NativeConfigurationAssessment
from .spa_thermal_policy import (
    SpaHeatingMode,
    SpaPolicyInput,
    SpaThermalPolicyTracker,
    SpaUserSource,
)
from .thermal_execution_planning import (
    ThermalCurrentState,
    ThermalDesiredState,
    ThermalExecutionPlanAssessment,
    ThermalExecutionPlanBuilder,
    desired_pool_state,
    desired_spa_state,
)
from .thermal_live_execution import (
    ThermalLiveAuthorizationEngine,
    ThermalLiveAuthorizationResult,
    ThermalLiveCommissioningScope,
    ThermalLiveExecutionPolicy,
    ThermalLiveSafetyEvidence,
)
from .thermal_source_policy import (
    HeatSourcePermissions,
    PoolHeatingMode,
    ThermalSourceInput,
    ThermalSourceSelector,
)


class ThermalRequestedMode(StrEnum):
    OFF = "Off"
    SOLAR = "Solar"
    GAS = "Gas"
    SOLAR_PREFERRED = "Solar Preferred"


@dataclass(frozen=True, slots=True)
class ThermalRuntimeEvidence:
    """Explicit current native and safety evidence for one evaluation cycle."""

    evaluated_at: datetime
    native_values: Mapping[str, Any]
    pool_requested_mode: ThermalRequestedMode
    hot_tub_requested_mode: ThermalRequestedMode
    native_transport_available: bool
    manual_transport_available: bool
    immediate_observation_healthy: bool
    stale_native_concepts: tuple[str, ...]
    missing_native_concepts: tuple[str, ...]
    native_configuration: NativeConfigurationAssessment
    filtration_debt: timedelta | None = None
    pending_durable_incident_confirmation: bool = False
    durable_incident_confirmed: bool = False

    def __post_init__(self) -> None:
        _require_aware(self.evaluated_at)
        object.__setattr__(self, "native_values", MappingProxyType(dict(self.native_values)))
        object.__setattr__(
            self, "stale_native_concepts", tuple(sorted(set(self.stale_native_concepts)))
        )
        object.__setattr__(
            self,
            "missing_native_concepts",
            tuple(sorted(set(self.missing_native_concepts))),
        )


@dataclass(frozen=True, slots=True)
class ThermalTechnicalPreflight:
    """Non-authorizing technical readiness evidence."""

    ready: bool
    evaluated_at: datetime
    evaluation_id: str
    plan_id: str
    blocking_reasons: tuple[str, ...]
    authorizing: bool = False
    command_delivery_enabled: bool = False


@dataclass(frozen=True, slots=True)
class ThermalBodyRuntimeAssessment:
    body: ThermalBody
    requested_mode: ThermalRequestedMode
    evaluation_id: str
    plan: ThermalExecutionPlanAssessment
    actual_authorization: ThermalLiveAuthorizationResult
    technical_preflight: ThermalTechnicalPreflight
    body_active: bool | None
    effective_heater_id: str | None
    actual_pump_rpm: int | None
    evidence_blockers: tuple[str, ...]

    def diagnostics(self, *, blocker_limit: int = 16) -> Mapping[str, Any]:
        desired = self.plan.desired
        return MappingProxyType(
            {
                "body": self.body.value,
                "requested_mode": self.requested_mode.value,
                "planned_source": desired.selected_source.value,
                "planned_rpm": desired.required_pump_rpm,
                "source_reason_code": desired.reason_code,
                "rpm_reason_code": desired.rpm_reason_code,
                "rationale": list(desired.rationale[:8]),
                "criteria": list(desired.criteria[:12]),
                "evidence": _bounded_evidence(desired.evidence),
                "fallback_reason": desired.fallback_reason,
                "plan_disposition": self.plan.disposition.value,
                "plan_id": self.plan.plan_id,
                "evaluation_id": self.evaluation_id,
                "body_active": self.body_active,
                "effective_native_heater_id": self.effective_heater_id,
                "actual_pump_rpm": self.actual_pump_rpm,
                "actual_authorized": self.actual_authorization.authorized,
                "actual_blockers": list(
                    self.actual_authorization.blocking_reasons[:blocker_limit]
                ),
                "technical_preflight_ready": self.technical_preflight.ready,
                "technical_blockers": list(
                    self.technical_preflight.blocking_reasons[:blocker_limit]
                ),
                "evidence_blockers": list(self.evidence_blockers[:blocker_limit]),
                "authority": "none",
                "automatic_execution_driver_enabled": False,
                "command_delivery_performed": False,
            }
        )


@dataclass(frozen=True, slots=True)
class ThermalRuntimeAssessment:
    generated_at: datetime
    evaluation_id: str
    effective_live_enabled: bool
    commissioning_scope: ThermalLiveCommissioningScope
    pool: ThermalBodyRuntimeAssessment
    hot_tub: ThermalBodyRuntimeAssessment
    native_transport_available: bool
    manual_transport_available: bool
    immediate_observation_healthy: bool
    pending_durable_incident_confirmation: bool
    durable_incident_confirmed: bool
    native_conflict_codes: tuple[str, ...]

    def global_diagnostics(self) -> Mapping[str, Any]:
        blockers = tuple(
            dict.fromkeys(
                (
                    *self.pool.actual_authorization.blocking_reasons,
                    *self.hot_tub.actual_authorization.blocking_reasons,
                )
            )
        )
        return MappingProxyType(
            {
                "generated_at": self.generated_at.isoformat(),
                "evaluation_id": self.evaluation_id,
                "effective_thermal_live_enabled": self.effective_live_enabled,
                "commissioning_scope": self.commissioning_scope.value,
                "native_transport_ready": self.native_transport_available,
                "manual_transport_ready": self.manual_transport_available,
                "current_observation_health": (
                    "HEALTHY" if self.immediate_observation_healthy else "UNHEALTHY"
                ),
                "pending_durable_incident_confirmation": (
                    self.pending_durable_incident_confirmation
                ),
                "durable_incident_confirmed": self.durable_incident_confirmed,
                "pool_actual_authorized": self.pool.actual_authorization.authorized,
                "hot_tub_actual_authorized": (
                    self.hot_tub.actual_authorization.authorized
                ),
                "pool_technical_preflight_ready": self.pool.technical_preflight.ready,
                "hot_tub_technical_preflight_ready": (
                    self.hot_tub.technical_preflight.ready
                ),
                "current_blockers": list(blockers[:20]),
                "native_conflict_codes": list(self.native_conflict_codes[:20]),
                "authority": "none",
                "automatic_execution_driver_enabled": False,
                "command_delivery_performed": False,
            }
        )


@dataclass(slots=True)
class ThermalRuntimeEvaluator:
    """Evaluate both bodies without importing or invoking physical execution."""

    pool_selector: ThermalSourceSelector = field(default_factory=ThermalSourceSelector)
    spa_tracker: SpaThermalPolicyTracker = field(default_factory=SpaThermalPolicyTracker)
    planner: ThermalExecutionPlanBuilder = field(default_factory=ThermalExecutionPlanBuilder)
    authorization: ThermalLiveAuthorizationEngine = field(
        default_factory=ThermalLiveAuthorizationEngine
    )

    def evaluate(
        self,
        evidence: ThermalRuntimeEvidence,
        *,
        live_policy: ThermalLiveExecutionPolicy,
    ) -> ThermalRuntimeAssessment:
        evaluation_id = _evaluation_id(evidence)
        pool = self._evaluate_body(
            evidence,
            body=ThermalBody.POOL,
            requested_mode=evidence.pool_requested_mode,
            evaluation_id=evaluation_id,
            live_policy=live_policy,
        )
        hot_tub = self._evaluate_body(
            evidence,
            body=ThermalBody.HOT_TUB,
            requested_mode=evidence.hot_tub_requested_mode,
            evaluation_id=evaluation_id,
            live_policy=live_policy,
        )
        return ThermalRuntimeAssessment(
            generated_at=evidence.evaluated_at,
            evaluation_id=evaluation_id,
            effective_live_enabled=live_policy.thermal_live_execution_enabled,
            commissioning_scope=live_policy.commissioning_scope,
            pool=pool,
            hot_tub=hot_tub,
            native_transport_available=evidence.native_transport_available,
            manual_transport_available=evidence.manual_transport_available,
            immediate_observation_healthy=evidence.immediate_observation_healthy,
            pending_durable_incident_confirmation=(
                evidence.pending_durable_incident_confirmation
            ),
            durable_incident_confirmed=evidence.durable_incident_confirmed,
            native_conflict_codes=tuple(
                item.code for item in evidence.native_configuration.conflicts
            ),
        )

    def _evaluate_body(
        self,
        evidence: ThermalRuntimeEvidence,
        *,
        body: ThermalBody,
        requested_mode: ThermalRequestedMode,
        evaluation_id: str,
        live_policy: ThermalLiveExecutionPolicy,
    ) -> ThermalBodyRuntimeAssessment:
        values = evidence.native_values
        prefix = "pool" if body is ThermalBody.POOL else "spa"
        active = _bool_or_none(values.get(f"{prefix}.active"))
        heater_id = _string_or_none(values.get(f"{prefix}.raw_heater_id"))
        pump_rpm = _int_or_none(values.get("pump.rpm"))
        current_source = _physical_source(heater_id)
        relevant = {
            f"{prefix}.active",
            f"{prefix}.temperature",
            f"{prefix}.target_temperature",
            f"{prefix}.raw_heater_id",
            "pump.rpm",
            "solar.temperature",
            "solar.active",
        }
        missing = tuple(sorted(relevant & set(evidence.missing_native_concepts)))
        stale = tuple(sorted(relevant & set(evidence.stale_native_concepts)))
        blockers = tuple(
            (
                *(f"missing_native:{item}" for item in missing),
                *(f"stale_native:{item}" for item in stale),
                *(() if heater_id in {"00000", "H0001", "H0002"} else ("native_heater_unknown",)),
            )
        )
        desired = self._desired(
            evidence,
            body=body,
            requested_mode=requested_mode,
            evidence_usable=not blockers,
            blockers=blockers,
        )
        current = ThermalCurrentState(
            observed_at=evidence.evaluated_at,
            body=body,
            selected_source=current_source,
            pump_rpm=pump_rpm,
            body_active=active if isinstance(active, bool) else None,
            source_evidence_usable=heater_id in {"00000", "H0001", "H0002"},
            pump_evidence_usable="pump.rpm" not in missing and "pump.rpm" not in stale,
            blockers=blockers,
            htmode=_string_or_none(values.get(f"{prefix}.raw_htmode")),
        )
        plan = self.planner.build(desired, current)
        hydraulic_safe = active is True and not (
            values.get("pool.active") is True and values.get("spa.active") is True
        )
        safety = ThermalLiveSafetyEvidence(
            evaluated_at=evidence.evaluated_at,
            evaluation_id=evaluation_id,
            current_evaluation_id=evaluation_id,
            current_plan_id=plan.plan_id,
            native_transport_available=evidence.native_transport_available,
            manual_transport_available=evidence.manual_transport_available,
            required_observations_fresh=not stale and not missing,
            observation_health_acceptable=evidence.immediate_observation_healthy,
            body_active=active is True,
            hydraulic_safety_acceptable=hydraulic_safe,
            native_configuration=evidence.native_configuration,
            contradictory_evidence=(
                ("pool_and_hot_tub_active",)
                if values.get("pool.active") is True
                and values.get("spa.active") is True
                else ()
            ),
            interrupted_execution_present=False,
            metadata={"phase3_dry_run": "true"},
        )
        actual = self.authorization.authorize(
            plan,
            step_index=0,
            policy=live_policy,
            evidence=safety,
        )
        technical_blockers = self.authorization.technical_preflight_blocking_reasons(
            plan,
            step_index=0,
            policy=live_policy,
            evidence=safety,
        )
        preflight = ThermalTechnicalPreflight(
            ready=not technical_blockers,
            evaluated_at=evidence.evaluated_at,
            evaluation_id=evaluation_id,
            plan_id=plan.plan_id,
            blocking_reasons=technical_blockers,
        )
        return ThermalBodyRuntimeAssessment(
            body=body,
            requested_mode=requested_mode,
            evaluation_id=evaluation_id,
            plan=plan,
            actual_authorization=actual,
            technical_preflight=preflight,
            body_active=active,
            effective_heater_id=heater_id,
            actual_pump_rpm=pump_rpm,
            evidence_blockers=blockers,
        )

    def _desired(
        self,
        evidence: ThermalRuntimeEvidence,
        *,
        body: ThermalBody,
        requested_mode: ThermalRequestedMode,
        evidence_usable: bool,
        blockers: tuple[str, ...],
    ) -> ThermalDesiredState:
        if requested_mode is ThermalRequestedMode.OFF:
            return _off_desired(
                evidence.evaluated_at,
                body=body,
                blockers=blockers,
                evidence_usable=evidence_usable,
            )
        values = evidence.native_values
        if body is ThermalBody.POOL:
            pool_mode = {
                ThermalRequestedMode.SOLAR: PoolHeatingMode.SOLAR_ONLY,
                ThermalRequestedMode.GAS: PoolHeatingMode.GAS_ONLY,
                ThermalRequestedMode.SOLAR_PREFERRED: PoolHeatingMode.SOLAR_PREFERRED,
            }[requested_mode]
            permissions = HeatSourcePermissions(
                solar_allowed=requested_mode is not ThermalRequestedMode.GAS,
                gas_allowed=requested_mode
                in {ThermalRequestedMode.GAS, ThermalRequestedMode.SOLAR_PREFERRED},
            )
            source_input = ThermalSourceInput(
                evaluated_at=evidence.evaluated_at,
                pool_active=values.get("pool.active") is True,
                spa_active=values.get("spa.active") is True,
                solar_active=values.get("solar.active") is True,
                trusted_pool_temperature_f=_number(values.get("pool.temperature")),
                pool_target_f=_number(values.get("pool.target_temperature")),
                collector_temperature_f=_number(values.get("solar.temperature")),
                heating_mode=pool_mode,
                permissions=permissions,
            )
            return desired_pool_state(
                source_input,
                self.pool_selector.evaluate(source_input),
                evidence_usable=evidence_usable,
                blockers=blockers,
            )
        spa_mode = (
            SpaHeatingMode.GAS_ONLY
            if requested_mode is ThermalRequestedMode.GAS
            else SpaHeatingMode.SOLAR_PREFERRED
        )
        permissions = HeatSourcePermissions(
            solar_allowed=requested_mode is not ThermalRequestedMode.GAS,
            gas_allowed=requested_mode
            in {ThermalRequestedMode.GAS, ThermalRequestedMode.SOLAR_PREFERRED},
        )
        pool_temperature = _number(values.get("pool.temperature"))
        pool_target = _number(values.get("pool.target_temperature"))
        spa_input = SpaPolicyInput(
            evaluated_at=evidence.evaluated_at,
            spa_active=values.get("spa.active") is True,
            transition_source=(
                SpaUserSource.NATIVE if values.get("spa.active") is True else None
            ),
            spa_temperature_f=_number(values.get("spa.temperature")),
            spa_target_f=_number(values.get("spa.target_temperature")),
            collector_temperature_f=_number(values.get("solar.temperature")),
            heating_mode=spa_mode,
            permissions=permissions,
            pool_demand_satisfied=(
                pool_temperature is not None
                and pool_target is not None
                and pool_temperature >= pool_target
            ),
            filtration_debt=evidence.filtration_debt,
        )
        return desired_spa_state(
            spa_input,
            self.spa_tracker.evaluate(spa_input),
            evidence_usable=evidence_usable,
            blockers=blockers,
        )


def _off_desired(
    evaluated_at: datetime,
    *,
    body: ThermalBody,
    blockers: tuple[str, ...],
    evidence_usable: bool,
) -> ThermalDesiredState:
    return ThermalDesiredState(
        evaluated_at=evaluated_at,
        body=body,
        requested_mode="off",
        selected_source=PhysicalHeatMode.OFF,
        required_pump_rpm=None,
        reason_code="operator_requested_thermal_off",
        rpm_reason_code=None,
        rationale=("Operator requested thermal source Off.",),
        criteria=("explicit_operator_configuration",),
        evidence={"requested_mode": "off"},
        evidence_usable=evidence_usable,
        blockers=blockers,
    )


def _physical_source(heater_id: str | None) -> PhysicalHeatMode:
    if heater_id is None:
        return PhysicalHeatMode.OFF
    return {
        "H0001": PhysicalHeatMode.GAS,
        "H0002": PhysicalHeatMode.SOLAR,
    }.get(heater_id, PhysicalHeatMode.OFF)


def _evaluation_id(evidence: ThermalRuntimeEvidence) -> str:
    payload = {
        "evaluated_at": evidence.evaluated_at.isoformat(),
        "pool_requested_mode": evidence.pool_requested_mode.value,
        "hot_tub_requested_mode": evidence.hot_tub_requested_mode.value,
        "native_values": dict(sorted(evidence.native_values.items())),
    }
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str)
    return "thermal-runtime-evaluation-" + sha256(canonical.encode()).hexdigest()[:24]


def _bounded_evidence(value: Mapping[str, Any]) -> dict[str, Any]:
    return {
        str(key)[:64]: _bounded_scalar(item)
        for key, item in tuple(sorted(value.items(), key=lambda pair: str(pair[0])))[:20]
    }


def _bounded_scalar(value: Any) -> Any:
    if value is None or isinstance(value, (bool, int, float)):
        return value
    return str(value)[:160]


def _number(value: Any) -> float | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    return float(value)


def _int_or_none(value: Any) -> int | None:
    number = _number(value)
    return None if number is None else round(number)


def _bool_or_none(value: Any) -> bool | None:
    return value if isinstance(value, bool) else None


def _string_or_none(value: Any) -> str | None:
    return value if isinstance(value, str) else None


def _require_aware(value: datetime) -> None:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("evaluated_at must be timezone-aware")


__all__ = [
    "ThermalBodyRuntimeAssessment",
    "ThermalRequestedMode",
    "ThermalRuntimeAssessment",
    "ThermalRuntimeEvaluator",
    "ThermalRuntimeEvidence",
    "ThermalTechnicalPreflight",
]
