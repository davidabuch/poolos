"""Command-free pool thermal modes, forecast gate, and source selection."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import Enum
import math

from .operating_baselines import PumpOperatingBaselines, command_disabled_criterion, pump_baseline_criterion
from .operational_intent import IntentCriterion, OperationalIntent, OperationalIntentPriority, OperationalIntentSource, OperationalIntentType
from .solar_control_policy import SolarEligibilityAssessment, SolarEligibilityInput, SolarEligibilityPolicy, SolarEligibilityTracker


class PoolHeatingMode(str, Enum):
    SOLAR_ONLY = "solar_only"
    SOLAR_PREFERRED = "solar_preferred"
    GAS_ONLY = "gas_only"


class ThermalHeatSource(str, Enum):
    NONE = "none"
    SOLAR = "solar"
    GAS = "gas"


class ThermalOperatingMode(str, Enum):
    NONE = "none"
    POOL_TEMPERATURE_PROBE = "pool_temperature_probe"
    POOL_SOLAR = "pool_solar"
    POOL_GAS = "pool_gas"


@dataclass(frozen=True, slots=True)
class HeatSourcePermissions:
    solar_allowed: bool = True
    gas_allowed: bool = True
    solar_veto_reason: str | None = None
    gas_veto_reason: str | None = None


class PermissionEvidenceKind(str, Enum):
    NORMAL_OPERATION = "normal_operation"
    INTENTIONAL_USER_CONFIGURATION = "intentional_user_configuration"


@dataclass(frozen=True, slots=True)
class HeatSourcePermissionUpdate:
    evidence_kind: PermissionEvidenceKind
    solar_allowed: bool | None = None
    gas_allowed: bool | None = None
    reason: str | None = None


def apply_permission_update(
    current: HeatSourcePermissions,
    update: HeatSourcePermissionUpdate,
) -> HeatSourcePermissions:
    """Apply only deliberate permission evidence; normal cycling changes nothing."""

    if update.evidence_kind is PermissionEvidenceKind.NORMAL_OPERATION:
        return current
    solar = current.solar_allowed if update.solar_allowed is None else update.solar_allowed
    gas = current.gas_allowed if update.gas_allowed is None else update.gas_allowed
    return HeatSourcePermissions(
        solar_allowed=solar,
        gas_allowed=gas,
        solar_veto_reason=(
            (update.reason or current.solar_veto_reason) if not solar else None
        ),
        gas_veto_reason=(update.reason or current.gas_veto_reason) if not gas else None,
    )


@dataclass(frozen=True, slots=True)
class ForecastGateEvidence:
    daily_highs_f: tuple[float, ...] = ()
    available: bool = False
    trusted: bool = False

    def __post_init__(self) -> None:
        if any(not math.isfinite(value) for value in self.daily_highs_f):
            raise ValueError("forecast highs must be finite")


@dataclass(frozen=True, slots=True)
class ThermalSourcePolicyConfig:
    pool_solar_policy: SolarEligibilityPolicy = SolarEligibilityPolicy()
    forecast_deficit_threshold_f: float = 5.0
    forecast_high_threshold_f: float = 78.0
    forecast_required_days: int = 4
    forecast_horizon_days: int = 5
    baselines: PumpOperatingBaselines = PumpOperatingBaselines()


@dataclass(frozen=True, slots=True)
class ThermalSourceInput:
    evaluated_at: datetime
    pool_active: bool
    spa_active: bool
    solar_active: bool
    trusted_pool_temperature_f: float | None
    pool_target_f: float | None
    collector_temperature_f: float | None
    heating_mode: PoolHeatingMode = PoolHeatingMode.SOLAR_ONLY
    permissions: HeatSourcePermissions = HeatSourcePermissions()
    solar_override: bool = False
    forecast: ForecastGateEvidence = ForecastGateEvidence()
    temperature_probe_required: bool = False

    def __post_init__(self) -> None:
        if self.evaluated_at.tzinfo is None or self.evaluated_at.utcoffset() is None:
            raise ValueError("evaluated_at must be timezone-aware")


@dataclass(frozen=True, slots=True)
class ThermalOperatingAssessment:
    evaluated_at: datetime
    mode: ThermalOperatingMode
    heat_source: ThermalHeatSource
    recommended_pump_rpm: int | None
    solar_assessment: SolarEligibilityAssessment
    forecast_gate_applied: bool
    forecast_gate_passed: bool
    intent: OperationalIntent | None
    reason_code: str
    skipped_due_to_permission: str | None = None
    authority: str = "none"
    command_delivery_enabled: bool = False


class ThermalSourceSelector:
    """Keep thermal goal, source selection, and execution authority separate."""

    def __init__(self, policy: ThermalSourcePolicyConfig = ThermalSourcePolicyConfig()) -> None:
        self._policy = policy
        self._solar = SolarEligibilityTracker(policy.pool_solar_policy)

    def _forecast_gate(self, observation: ThermalSourceInput) -> tuple[bool, bool]:
        water = observation.trusted_pool_temperature_f
        target = observation.pool_target_f
        if observation.heating_mode is not PoolHeatingMode.SOLAR_ONLY or water is None or target is None:
            return False, True
        if target - water <= self._policy.forecast_deficit_threshold_f:
            return False, True
        if observation.solar_override:
            return True, True
        forecast = observation.forecast
        if not forecast.available or not forecast.trusted or len(forecast.daily_highs_f) < self._policy.forecast_horizon_days:
            return True, True
        horizon = forecast.daily_highs_f[: self._policy.forecast_horizon_days]
        warm = sum(value >= self._policy.forecast_high_threshold_f for value in horizon)
        return True, warm >= self._policy.forecast_required_days

    def _intent(self, observation: ThermalSourceInput, mode: ThermalOperatingMode, source: ThermalHeatSource, rpm: int) -> OperationalIntent:
        return OperationalIntent(
            intent_type=OperationalIntentType.HEAT_POOL,
            source=OperationalIntentSource.OPERATOR if observation.heating_mode is not PoolHeatingMode.SOLAR_ONLY else OperationalIntentSource.EQUIPMENT,
            priority=OperationalIntentPriority.NORMAL,
            description=f"Recommend {source.value} pool heating",
            requested_at=observation.evaluated_at,
            source_reference=f"pool-thermal-policy:{mode.value}",
            constraints=(
                pump_baseline_criterion(rpm=rpm, operating_mode=mode.value),
                command_disabled_criterion(),
                IntentCriterion("selected_heat_source", "Heat source selected independently from HEAT_POOL", {"source": source.value}),
            ),
        )

    def evaluate(self, observation: ThermalSourceInput) -> ThermalOperatingAssessment:
        solar = self._solar.evaluate(SolarEligibilityInput(
            evaluated_at=observation.evaluated_at,
            pool_active=observation.pool_active,
            spa_active=observation.spa_active,
            solar_active=observation.solar_active,
            water_temperature_f=observation.trusted_pool_temperature_f,
            collector_temperature_f=observation.collector_temperature_f,
            target_temperature_f=observation.pool_target_f,
        ))
        gate_applied, gate_passed = self._forecast_gate(observation)
        needs_heat = observation.trusted_pool_temperature_f is not None and observation.pool_target_f is not None and observation.trusted_pool_temperature_f < observation.pool_target_f

        if observation.temperature_probe_required:
            rpm = self._policy.baselines.temperature_probe_rpm
            intent = OperationalIntent(
                intent_type=OperationalIntentType.MAINTAIN_CIRCULATION,
                source=OperationalIntentSource.EQUIPMENT,
                priority=OperationalIntentPriority.NORMAL,
                description="Acquire trusted pool-water temperature",
                requested_at=observation.evaluated_at,
                source_reference="trusted-water-temperature-probe",
                constraints=(pump_baseline_criterion(rpm=rpm, operating_mode="temperature_probe"), command_disabled_criterion()),
            )
            return ThermalOperatingAssessment(observation.evaluated_at, ThermalOperatingMode.POOL_TEMPERATURE_PROBE, ThermalHeatSource.NONE, rpm, solar, gate_applied, gate_passed, intent, "pool_temperature_probe_required")

        if observation.heating_mode is PoolHeatingMode.GAS_ONLY:
            if not needs_heat:
                return self._none(observation, solar, gate_applied, gate_passed, "pool_target_satisfied")
            if not observation.permissions.gas_allowed:
                return self._none(observation, solar, gate_applied, gate_passed, "gas_permission_veto", observation.permissions.gas_veto_reason or "gas")
            return self._selected(observation, solar, gate_applied, gate_passed, ThermalOperatingMode.POOL_GAS, ThermalHeatSource.GAS, self._policy.baselines.gas_heating_rpm, "gas_only_mode")

        solar_usable = solar.eligible and observation.permissions.solar_allowed
        if observation.heating_mode is PoolHeatingMode.SOLAR_PREFERRED:
            if solar_usable:
                return self._selected(observation, solar, gate_applied, True, ThermalOperatingMode.POOL_SOLAR, ThermalHeatSource.SOLAR, self._policy.baselines.solar_heating_rpm, "solar_preferred_physical_solar")
            if needs_heat and observation.permissions.gas_allowed:
                return self._selected(observation, solar, gate_applied, True, ThermalOperatingMode.POOL_GAS, ThermalHeatSource.GAS, self._policy.baselines.gas_heating_rpm, "solar_preferred_gas_fallback")
            veto = observation.permissions.solar_veto_reason if solar.eligible and not observation.permissions.solar_allowed else observation.permissions.gas_veto_reason
            return self._none(observation, solar, gate_applied, True, "source_permission_veto" if veto else "no_eligible_heat_source", veto)

        if solar_usable and gate_passed:
            return self._selected(observation, solar, gate_applied, gate_passed, ThermalOperatingMode.POOL_SOLAR, ThermalHeatSource.SOLAR, self._policy.baselines.solar_heating_rpm, "solar_only_selected")
        veto = observation.permissions.solar_veto_reason if solar.eligible and not observation.permissions.solar_allowed else None
        return self._none(observation, solar, gate_applied, gate_passed, "solar_permission_veto" if veto else "solar_only_not_selected", veto)

    def _selected(self, observation: ThermalSourceInput, solar: SolarEligibilityAssessment, gate_applied: bool, gate_passed: bool, mode: ThermalOperatingMode, source: ThermalHeatSource, rpm: int, reason: str) -> ThermalOperatingAssessment:
        return ThermalOperatingAssessment(observation.evaluated_at, mode, source, rpm, solar, gate_applied, gate_passed, self._intent(observation, mode, source, rpm), reason)

    @staticmethod
    def _none(observation: ThermalSourceInput, solar: SolarEligibilityAssessment, gate_applied: bool, gate_passed: bool, reason: str, veto: str | None = None) -> ThermalOperatingAssessment:
        return ThermalOperatingAssessment(observation.evaluated_at, ThermalOperatingMode.NONE, ThermalHeatSource.NONE, None, solar, gate_applied, gate_passed, None, reason, veto)
