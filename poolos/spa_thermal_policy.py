"""Unified command-free HA/ICP/OCP spa session and opportunistic policy."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from enum import Enum
from zoneinfo import ZoneInfo

from .operating_baselines import PumpOperatingBaselines, command_disabled_criterion, pump_baseline_criterion
from .operational_intent import IntentCriterion, OperationalIntent, OperationalIntentPriority, OperationalIntentSource, OperationalIntentType
from .thermal_source_policy import HeatSourcePermissions, ThermalHeatSource


class SpaUserSource(str, Enum):
    HOME_ASSISTANT = "home_assistant"
    ICP = "icp"
    OCP = "ocp"
    NATIVE = "native"


class SpaHeatingMode(str, Enum):
    SOLAR_PREFERRED = "solar_preferred"
    GAS_ONLY = "gas_only"


class SpaPolicyState(str, Enum):
    IDLE = "idle"
    SPA_IN_USE_HEAT_UP = "spa_in_use_heat_up"
    SPA_IN_USE_MAINTENANCE = "spa_in_use_maintenance"
    OPPORTUNISTIC_QUALIFYING = "opportunistic_qualifying"
    OPPORTUNISTIC_ACTIVE = "opportunistic_active"
    OPPORTUNISTIC_HOLD = "opportunistic_hold"
    PRESERVE_UNTIL_10PM = "preserve_until_10pm"
    RELEASE_TO_POOL = "release_to_pool"


@dataclass(frozen=True, slots=True)
class SpaPolicyConfig:
    timezone_name: str = "America/Los_Angeles"
    heat_up_solar_roof_f: float = 130.0
    maintenance_solar_roof_f: float = 120.0
    qualification_hold: timedelta = timedelta(minutes=2)
    maintenance_deficit_f: float = 2.0
    opportunity_start_hour: int = 13
    opportunity_end_hour: int = 18
    preserve_end_hour: int = 22
    baselines: PumpOperatingBaselines = PumpOperatingBaselines()


@dataclass(frozen=True, slots=True)
class SpaPolicyInput:
    evaluated_at: datetime
    spa_active: bool
    transition_source: SpaUserSource | None
    spa_temperature_f: float | None
    spa_target_f: float | None
    collector_temperature_f: float | None
    heating_mode: SpaHeatingMode = SpaHeatingMode.SOLAR_PREFERRED
    permissions: HeatSourcePermissions = HeatSourcePermissions()
    opportunistic_allowed: bool = True
    pool_demand_satisfied: bool = False
    filtration_debt: timedelta | None = timedelta(0)
    higher_priority_conflict: bool = False


@dataclass(frozen=True, slots=True)
class SpaPolicyAssessment:
    evaluated_at: datetime
    state: SpaPolicyState
    heat_source: ThermalHeatSource
    recommended_pump_rpm: int | None
    spa_in_use: bool
    preserve_spa_mode: bool
    pool_reprobe_allowed: bool
    intent: OperationalIntent | None
    reason_code: str
    authority: str = "none"
    command_delivery_enabled: bool = False


class SpaThermalPolicyTracker:
    """Track one physical spa session regardless of its human command source."""

    def __init__(self, policy: SpaPolicyConfig = SpaPolicyConfig()) -> None:
        self._policy = policy
        self._state = SpaPolicyState.IDLE
        self._spa_in_use = False
        self._maintenance_latched = False
        self._above_130_since: datetime | None = None
        self._below_130_since: datetime | None = None
        self._below_120_since: datetime | None = None
        self._last_evaluated_at: datetime | None = None
        self._last_source = ThermalHeatSource.NONE

    def recover(self, *, evaluated_at: datetime, actual_spa_active: bool, persisted_session_active: bool) -> SpaPolicyAssessment:
        del persisted_session_active
        observation = SpaPolicyInput(
            evaluated_at=evaluated_at,
            spa_active=actual_spa_active,
            transition_source=SpaUserSource.NATIVE if actual_spa_active else None,
            spa_temperature_f=None,
            spa_target_f=None,
            collector_temperature_f=None,
            opportunistic_allowed=False,
        )
        self._spa_in_use = actual_spa_active
        self._maintenance_latched = False
        self._state = SpaPolicyState.SPA_IN_USE_HEAT_UP if actual_spa_active else SpaPolicyState.IDLE
        return self._evaluate_user_session(observation) if actual_spa_active else self._result(observation, SpaPolicyState.IDLE, ThermalHeatSource.NONE, None, "actual_spa_off_after_restart")

    def evaluate(self, observation: SpaPolicyInput) -> SpaPolicyAssessment:
        if observation.evaluated_at.tzinfo is None or observation.evaluated_at.utcoffset() is None:
            raise ValueError("evaluated_at must be timezone-aware")
        if self._last_evaluated_at is not None and observation.evaluated_at < self._last_evaluated_at:
            raise ValueError("spa policy observations must be chronological")
        self._last_evaluated_at = observation.evaluated_at

        if observation.spa_active:
            if not self._spa_in_use:
                self._maintenance_latched = False
                self._above_130_since = None
                self._below_130_since = None
                self._last_source = ThermalHeatSource.NONE
            self._spa_in_use = True
            return self._evaluate_user_session(observation)
        if self._spa_in_use:
            self._spa_in_use = False
            self._maintenance_latched = False
            self._state = SpaPolicyState.IDLE
            self._above_130_since = None
            self._below_130_since = None

        return self._evaluate_opportunistic(observation)

    def _evaluate_user_session(self, observation: SpaPolicyInput) -> SpaPolicyAssessment:
        target_reached = observation.spa_temperature_f is not None and observation.spa_target_f is not None and observation.spa_temperature_f >= observation.spa_target_f
        if target_reached:
            self._maintenance_latched = True
        self._state = SpaPolicyState.SPA_IN_USE_MAINTENANCE if self._maintenance_latched else SpaPolicyState.SPA_IN_USE_HEAT_UP
        if observation.heating_mode is SpaHeatingMode.GAS_ONLY:
            return self._gas_or_none(observation, "spa_gas_only")
        roof = observation.collector_temperature_f
        if self._maintenance_latched:
            deficit = None if observation.spa_temperature_f is None or observation.spa_target_f is None else observation.spa_target_f - observation.spa_temperature_f
            solar = roof is not None and (roof >= self._policy.heat_up_solar_roof_f or (roof >= self._policy.maintenance_solar_roof_f and (deficit is None or deficit <= self._policy.maintenance_deficit_f)))
            if solar and observation.permissions.solar_allowed:
                return self._solar(observation, "spa_maintenance_solar")
            return self._gas_or_none(observation, "spa_maintenance_gas")

        if roof is not None and roof >= self._policy.heat_up_solar_roof_f:
            if self._above_130_since is None:
                self._above_130_since = observation.evaluated_at
            self._below_130_since = None
        else:
            self._above_130_since = None
            if self._below_130_since is None:
                self._below_130_since = observation.evaluated_at
        qualified = self._above_130_since is not None and observation.evaluated_at - self._above_130_since >= self._policy.qualification_hold
        currently_solar = self._state is SpaPolicyState.SPA_IN_USE_HEAT_UP and self._last_source is ThermalHeatSource.SOLAR
        lost = self._below_130_since is not None and observation.evaluated_at - self._below_130_since >= self._policy.qualification_hold
        if observation.permissions.solar_allowed and (qualified or (currently_solar and not lost)):
            return self._solar(observation, "spa_heat_up_solar")
        return self._gas_or_none(observation, "spa_heat_up_gas")

    def _evaluate_opportunistic(self, observation: SpaPolicyInput) -> SpaPolicyAssessment:
        local = observation.evaluated_at.astimezone(ZoneInfo(self._policy.timezone_name))
        roof = observation.collector_temperature_f
        if local.hour >= self._policy.preserve_end_hour:
            self._state = SpaPolicyState.RELEASE_TO_POOL
            return self._result(observation, self._state, ThermalHeatSource.NONE, None, "ten_pm_release", preserve=False)
        if local.hour >= self._policy.opportunity_end_hour:
            self._state = SpaPolicyState.PRESERVE_UNTIL_10PM
            return self._result(observation, self._state, ThermalHeatSource.NONE, None, "six_pm_preserve", preserve=True)

        eligible = (
            local.hour >= self._policy.opportunity_start_hour
            and observation.opportunistic_allowed
            and observation.heating_mode is not SpaHeatingMode.GAS_ONLY
            and observation.permissions.solar_allowed
            and observation.pool_demand_satisfied
            and observation.filtration_debt is not None
            and observation.filtration_debt <= timedelta(0)
            and not observation.higher_priority_conflict
        )
        if not eligible:
            self._state = SpaPolicyState.IDLE
            return self._result(observation, self._state, ThermalHeatSource.NONE, None, "opportunistic_ineligible")

        if self._state is SpaPolicyState.OPPORTUNISTIC_ACTIVE:
            if (
                observation.spa_temperature_f is not None
                and observation.spa_target_f is not None
                and observation.spa_temperature_f >= observation.spa_target_f
            ):
                self._state = SpaPolicyState.OPPORTUNISTIC_HOLD
                return self._result(
                    observation,
                    self._state,
                    ThermalHeatSource.NONE,
                    None,
                    "opportunistic_target_cap_reached",
                    preserve=True,
                )
            if roof is not None and roof < self._policy.maintenance_solar_roof_f:
                if self._below_120_since is None:
                    self._below_120_since = observation.evaluated_at
            else:
                self._below_120_since = None
            if self._below_120_since is not None and observation.evaluated_at - self._below_120_since >= self._policy.qualification_hold:
                self._state = SpaPolicyState.OPPORTUNISTIC_HOLD
                return self._result(observation, self._state, ThermalHeatSource.NONE, None, "opportunistic_roof_low_hold", preserve=True)
            return self._solar(observation, "opportunistic_active", opportunistic=True)

        if roof is not None and roof >= self._policy.heat_up_solar_roof_f:
            if self._above_130_since is None:
                self._above_130_since = observation.evaluated_at
        else:
            self._above_130_since = None
        qualified = self._above_130_since is not None and observation.evaluated_at - self._above_130_since >= self._policy.qualification_hold
        if qualified:
            self._state = SpaPolicyState.OPPORTUNISTIC_ACTIVE
            self._below_120_since = None
            return self._solar(observation, "opportunistic_started_or_resumed", opportunistic=True)
        self._state = SpaPolicyState.OPPORTUNISTIC_HOLD if self._state is SpaPolicyState.OPPORTUNISTIC_HOLD else SpaPolicyState.OPPORTUNISTIC_QUALIFYING
        return self._result(observation, self._state, ThermalHeatSource.NONE, None, "opportunistic_waiting_for_roof", preserve=self._state is SpaPolicyState.OPPORTUNISTIC_HOLD)

    def _solar(self, observation: SpaPolicyInput, reason: str, *, opportunistic: bool = False) -> SpaPolicyAssessment:
        self._last_source = ThermalHeatSource.SOLAR
        state = SpaPolicyState.OPPORTUNISTIC_ACTIVE if opportunistic else self._state
        return self._result(observation, state, ThermalHeatSource.SOLAR, self._policy.baselines.solar_heating_rpm, reason, preserve=opportunistic)

    def _gas_or_none(self, observation: SpaPolicyInput, reason: str) -> SpaPolicyAssessment:
        if observation.permissions.gas_allowed:
            self._last_source = ThermalHeatSource.GAS
            return self._result(observation, self._state, ThermalHeatSource.GAS, self._policy.baselines.gas_heating_rpm, reason)
        self._last_source = ThermalHeatSource.NONE
        return self._result(observation, self._state, ThermalHeatSource.NONE, None, "gas_permission_veto")

    def _result(self, observation: SpaPolicyInput, state: SpaPolicyState, source: ThermalHeatSource, rpm: int | None, reason: str, *, preserve: bool = False) -> SpaPolicyAssessment:
        intent = None
        if rpm is not None:
            intent = OperationalIntent(
                intent_type=OperationalIntentType.HEAT_SPA,
                source=OperationalIntentSource.OPERATOR if self._spa_in_use else OperationalIntentSource.EQUIPMENT,
                priority=OperationalIntentPriority.HIGH if self._spa_in_use else OperationalIntentPriority.LOW,
                description=f"Recommend {source.value} spa heating",
                requested_at=observation.evaluated_at,
                source_reference=f"spa-policy:{state.value}",
                constraints=(
                    pump_baseline_criterion(rpm=rpm, operating_mode=state.value),
                    command_disabled_criterion(),
                    IntentCriterion("gas_fallback_forbidden", "Opportunistic spa never uses gas", {"forbidden": not self._spa_in_use}),
                ),
            )
        return SpaPolicyAssessment(observation.evaluated_at, state, source, rpm, self._spa_in_use, preserve, False, intent, reason)
