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
from typing import Any, ClassVar, Mapping

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
from .thermal_execution_currentness import ThermalExecutionCurrentness
from .thermal_live_execution import (
    ThermalLiveAuthorizationEngine,
    ThermalLiveAuthorizationResult,
    ThermalLiveCommissioningScope,
    ThermalLiveExecutionContext,
    ThermalLiveExecutionPolicy,
    ThermalHydraulicSafetyEvidence,
    ThermalLiveSafetyEvidence,
)
from .thermal_source_policy import (
    HeatSourcePermissions,
    PoolHeatingMode,
    ThermalSourceInput,
    ThermalSourceSelector,
)
from .water_temperature_policy import (
    TemperatureSample,
    WaterTemperatureAssessment,
    WaterTemperatureDisposition,
    WaterTemperatureTracker,
)


class ThermalRequestedMode(StrEnum):
    OFF = "Off"
    SOLAR = "Solar"
    GAS = "Gas"
    SOLAR_PREFERRED = "Solar Preferred"


class PoolTemperatureProbePhase(StrEnum):
    """In-memory ownership lifecycle for one Pool water-temperature probe."""

    IDLE = "idle"
    PROBE_REQUIRED = "probe_required"
    PROBING = "probing"
    TRUSTED = "trusted"
    ACQUISITION_FAILED = "acquisition_failed"


@dataclass(slots=True)
class PoolTemperatureProbeRuntimeState:
    """Retain one bounded probe lifecycle without commanding circulation."""

    phase: PoolTemperatureProbePhase = PoolTemperatureProbePhase.IDLE
    requested_at: datetime | None = None
    started_at: datetime | None = None
    samples: tuple[TemperatureSample, ...] = ()
    last_assessment: WaterTemperatureAssessment | None = None
    sample_limit: ClassVar[int] = 64

    @property
    def owned(self) -> bool:
        return self.phase in {
            PoolTemperatureProbePhase.PROBE_REQUIRED,
            PoolTemperatureProbePhase.PROBING,
            PoolTemperatureProbePhase.ACQUISITION_FAILED,
        }

    @property
    def tracker_probe_active(self) -> bool:
        return self.phase in {
            PoolTemperatureProbePhase.PROBING,
            PoolTemperatureProbePhase.ACQUISITION_FAILED,
        }

    def require(self, at: datetime) -> None:
        if self.phase is PoolTemperatureProbePhase.ACQUISITION_FAILED:
            return
        if self.phase is not PoolTemperatureProbePhase.PROBE_REQUIRED:
            self.phase = PoolTemperatureProbePhase.PROBE_REQUIRED
            self.requested_at = at
            self.started_at = None
            self.samples = ()

    def begin_if_required(self, at: datetime, *, pool_circulating: bool) -> None:
        if (
            self.phase is PoolTemperatureProbePhase.PROBE_REQUIRED
            and pool_circulating
        ):
            self.phase = PoolTemperatureProbePhase.PROBING
            self.started_at = at

    def invalidate_if_probing(
        self,
        at: datetime,
        *,
        pool_circulating: bool,
    ) -> None:
        """Discard one interrupted acquisition epoch and require fresh proof."""

        if (
            self.phase is PoolTemperatureProbePhase.PROBING
            and not pool_circulating
        ):
            self.phase = PoolTemperatureProbePhase.PROBE_REQUIRED
            self.requested_at = at
            self.started_at = None
            self.samples = ()
            self.last_assessment = None

    def samples_with(
        self,
        sample: TemperatureSample | None,
    ) -> tuple[TemperatureSample, ...]:
        if not self.tracker_probe_active or sample is None:
            return self.samples
        if self.started_at is not None and sample.observed_at < self.started_at:
            return self.samples
        if self.samples and sample.observed_at <= self.samples[-1].observed_at:
            return self.samples
        return (*self.samples, sample)[-self.sample_limit :]

    def accept(
        self,
        assessment: WaterTemperatureAssessment,
        samples: tuple[TemperatureSample, ...],
    ) -> None:
        self.last_assessment = assessment
        self.samples = samples
        if (
            assessment.disposition is WaterTemperatureDisposition.TRUSTED
            and self.phase is PoolTemperatureProbePhase.PROBING
        ):
            self.phase = PoolTemperatureProbePhase.TRUSTED
        elif (
            assessment.disposition
            is WaterTemperatureDisposition.ACQUISITION_FAILED
        ):
            self.phase = PoolTemperatureProbePhase.ACQUISITION_FAILED
        elif (
            assessment.disposition is WaterTemperatureDisposition.NOT_REQUIRED
            and self.phase is PoolTemperatureProbePhase.PROBE_REQUIRED
        ):
            self.phase = PoolTemperatureProbePhase.IDLE
            self.requested_at = None
            self.started_at = None
            self.samples = ()

    def reset(self) -> None:
        self.phase = PoolTemperatureProbePhase.IDLE
        self.requested_at = None
        self.started_at = None
        self.samples = ()
        self.last_assessment = None


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
    native_observed_at: Mapping[str, datetime] = field(default_factory=dict)
    filtration_debt: timedelta | None = None
    pending_durable_incident_confirmation: bool = False
    durable_incident_confirmed: bool = False

    def __post_init__(self) -> None:
        _require_aware(self.evaluated_at)
        object.__setattr__(self, "native_values", MappingProxyType(dict(self.native_values)))
        observed_at = dict(self.native_observed_at)
        for timestamp in observed_at.values():
            _require_aware(timestamp)
        object.__setattr__(self, "native_observed_at", MappingProxyType(observed_at))
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
    live_safety_evidence: ThermalLiveSafetyEvidence | None = None

    @property
    def execution_currentness(self) -> ThermalExecutionCurrentness:
        """Return concrete audit identity plus stable execution purpose."""

        return ThermalExecutionCurrentness.from_assessment(
            self.plan,
            evaluation_id=self.evaluation_id,
        )

    @property
    def live_execution_context(self) -> ThermalLiveExecutionContext:
        """Return the typed current context consumed by the live engine."""

        return ThermalLiveExecutionContext(
            evaluation_id=self.evaluation_id,
            plan_id=self.plan.plan_id,
            execution_currentness=self.execution_currentness,
        )

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
                "execution_purpose_id": (
                    self.execution_currentness.purpose.purpose_id
                ),
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
    water_temperature_tracker: WaterTemperatureTracker = field(
        default_factory=WaterTemperatureTracker
    )
    pool_temperature_probe: PoolTemperatureProbeRuntimeState = field(
        default_factory=PoolTemperatureProbeRuntimeState
    )
    planner: ThermalExecutionPlanBuilder = field(default_factory=ThermalExecutionPlanBuilder)
    authorization: ThermalLiveAuthorizationEngine = field(
        default_factory=ThermalLiveAuthorizationEngine
    )
    _last_pool_temperature_evaluated_at: datetime | None = field(
        default=None,
        init=False,
        repr=False,
    )

    def evaluate(
        self,
        evidence: ThermalRuntimeEvidence,
        *,
        live_policy: ThermalLiveExecutionPolicy,
    ) -> ThermalRuntimeAssessment:
        if evidence.pool_requested_mode not in {
            ThermalRequestedMode.SOLAR,
            ThermalRequestedMode.SOLAR_PREFERRED,
        }:
            self.pool_temperature_probe.reset()
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

        water_temperature: WaterTemperatureAssessment | None = None
        if (
            body is ThermalBody.POOL
            and requested_mode
            in {
                ThermalRequestedMode.SOLAR,
                ThermalRequestedMode.SOLAR_PREFERRED,
            }
        ):
            if (
                self._last_pool_temperature_evaluated_at is not None
                and evidence.evaluated_at
                < self._last_pool_temperature_evaluated_at
            ):
                raise ValueError(
                    "solar eligibility observations must be chronological"
                )
            self._last_pool_temperature_evaluated_at = evidence.evaluated_at
            pool_temperature_usable = (
                "pool.temperature" not in missing
                and "pool.temperature" not in stale
            )
            collector_temperature_usable = (
                "solar.temperature" not in missing
                and "solar.temperature" not in stale
            )
            spa_active = _bool_or_none(values.get("spa.active"))
            probe_hydraulic_concepts = {
                "pool.active",
                "spa.active",
                "pump.rpm",
            }
            probe_hydraulic_evidence_usable = not (
                probe_hydraulic_concepts
                & (
                    set(evidence.missing_native_concepts)
                    | set(evidence.stale_native_concepts)
                )
            )
            pool_circulating = (
                probe_hydraulic_evidence_usable
                and active is True
                and spa_active is False
                and pump_rpm is not None
                and pump_rpm > 0
            )
            self.pool_temperature_probe.invalidate_if_probing(
                evidence.evaluated_at,
                pool_circulating=pool_circulating,
            )
            self.pool_temperature_probe.begin_if_required(
                evidence.evaluated_at,
                pool_circulating=pool_circulating,
            )
            sample: TemperatureSample | None = None
            observed_temperature = (
                _number(values.get("pool.temperature"))
                if pool_temperature_usable
                else None
            )
            if (
                self.pool_temperature_probe.tracker_probe_active
                and pool_circulating
                and observed_temperature is not None
            ):
                sample_observed_at = evidence.native_observed_at.get(
                    "pool.temperature"
                )
                if (
                    sample_observed_at is not None
                    and sample_observed_at <= evidence.evaluated_at
                ):
                    sample = TemperatureSample(
                        sample_observed_at,
                        observed_temperature,
                    )
            samples = self.pool_temperature_probe.samples_with(sample)
            try:
                water_temperature = self.water_temperature_tracker.evaluate(
                    evaluated_at=evidence.evaluated_at,
                    observed_temperature_f=observed_temperature,
                    pool_circulating=pool_circulating,
                    probe_active=(
                        self.pool_temperature_probe.tracker_probe_active
                    ),
                    probe_started_at=self.pool_temperature_probe.started_at,
                    samples=samples,
                    collector_temperature_f=(
                        _number(values.get("solar.temperature"))
                        if collector_temperature_usable
                        else None
                    ),
                    thermal_decision_requested=True,
                )
            except ValueError as exc:
                if str(exc) == "temperature evaluations must be chronological":
                    raise ValueError(
                        "solar eligibility observations must be chronological"
                    ) from exc
                raise

            self.pool_temperature_probe.accept(water_temperature, samples)
            if (
                water_temperature.disposition
                is WaterTemperatureDisposition.PROBE_REQUIRED
            ):
                self.pool_temperature_probe.require(evidence.evaluated_at)

            if (
                water_temperature.disposition
                in {
                    WaterTemperatureDisposition.PROBE_REQUIRED,
                    WaterTemperatureDisposition.PROBING,
                }
            ):
                missing = tuple(
                    item for item in missing if item != "pool.temperature"
                )
                stale = tuple(
                    item for item in stale if item != "pool.temperature"
                )

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
            water_temperature=water_temperature,
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
        execution_currentness = ThermalExecutionCurrentness.from_assessment(
            plan,
            evaluation_id=evaluation_id,
        )
        pool_active = _bool_or_none(values.get("pool.active"))
        spa_active = _bool_or_none(values.get("spa.active"))
        missing_native = set(evidence.missing_native_concepts)
        stale_native = set(evidence.stale_native_concepts)
        pool_activity_usable = (
            pool_active is not None and "pool.active" not in missing_native
        )
        spa_activity_usable = (
            spa_active is not None and "spa.active" not in missing_native
        )
        pool_activity_fresh = (
            pool_activity_usable and "pool.active" not in stale_native
        )
        spa_activity_fresh = (
            spa_activity_usable and "spa.active" not in stale_native
        )
        other_active = (
            spa_active if body is ThermalBody.POOL else pool_active
        )
        hydraulic_safe = (
            pool_activity_fresh
            and spa_activity_fresh
            and isinstance(active, bool)
            and other_active is False
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
            hydraulic=ThermalHydraulicSafetyEvidence(
                target_body=body,
                pool_active=pool_active,
                spa_active=spa_active,
                pool_activity_fresh=pool_activity_fresh,
                spa_activity_fresh=spa_activity_fresh,
                pool_activity_usable=pool_activity_usable,
                spa_activity_usable=spa_activity_usable,
            ),
            native_configuration=evidence.native_configuration,
            contradictory_evidence=(
                ("pool_and_hot_tub_active",)
                if values.get("pool.active") is True
                and values.get("spa.active") is True
                else ()
            ),
            interrupted_execution_present=False,
            metadata={"phase3_dry_run": "true"},
            execution_currentness=execution_currentness,
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
            live_safety_evidence=safety,
        )

    def _desired(
        self,
        evidence: ThermalRuntimeEvidence,
        *,
        body: ThermalBody,
        requested_mode: ThermalRequestedMode,
        evidence_usable: bool,
        blockers: tuple[str, ...],
        water_temperature: WaterTemperatureAssessment | None = None,
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
                trusted_pool_temperature_f=(
                    water_temperature.trusted_temperature_f
                    if (
                        water_temperature is not None
                        and water_temperature.disposition
                        in {
                            WaterTemperatureDisposition.TRUSTED,
                            WaterTemperatureDisposition.REUSED,
                        }
                    )
                    else (
                        _number(values.get("pool.temperature"))
                        if water_temperature is None
                        else None
                    )
                ),
                pool_target_f=_number(values.get("pool.target_temperature")),
                collector_temperature_f=_number(values.get("solar.temperature")),
                heating_mode=pool_mode,
                permissions=permissions,
                temperature_probe_required=(
                    water_temperature is not None
                    and water_temperature.disposition
                    in {
                        WaterTemperatureDisposition.PROBE_REQUIRED,
                        WaterTemperatureDisposition.PROBING,
                    }
                ),
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
