"""Side-effect-free current thermal planning and authorization diagnostics.

This module assembles Phase 1 plans and evaluates Phase 2 authorization gates.
It deliberately imports no execution engine or delivery port and cannot issue
commands.
"""

from __future__ import annotations

from dataclasses import dataclass, field, replace
from datetime import datetime, timedelta
from enum import StrEnum
from hashlib import sha256
import json
from types import MappingProxyType
from typing import Any, ClassVar, Mapping

from .integration import PhysicalHeatMode, ThermalBody
from .intellicenter_readonly import (
    POOL_PUMP_CIRCUIT_CONFIGURED_SPEED_CONCEPT,
    SPA_PUMP_CIRCUIT_CONFIGURED_SPEED_CONCEPT,
)
from .native_configuration_policy import NativeConfigurationAssessment
from .operating_baselines import PumpOperatingBaselines
from .pool_temperature_probe_execution import (
    PoolTemperatureProbeContinuityEvidence,
    PoolTemperatureProbeExecutionEvidence,
    PoolTemperatureProbeExecutionPhase,
)
from .spa_thermal_policy import (
    SpaHeatingMode,
    SpaPolicyInput,
    SpaSessionKind,
    SpaThermalPolicyTracker,
    SpaUserSource,
)
from .spa_temperature_policy import (
    SpaTemperatureDisposition,
    SpaTemperatureEvidence,
    current_spa_temperature_evidence,
)
from .thermal_operating_purpose import (
    ThermalOperatingPurposeEvidence,
    assess_thermal_operating_purpose,
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
    ThermalHeatSource,
    ThermalSourceInput,
    ThermalSourceSelector,
)
from .water_temperature_policy import (
    TemperatureSample,
    WaterTemperatureAssessment,
    WaterTemperatureDisposition,
    WaterTemperatureTracker,
)

_PUMP_BASELINES = PumpOperatingBaselines()
_ACTUAL_PUMP_RPM_TOLERANCE = 25


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
    execution_purpose_id: str | None = None
    ownership_generation: int | None = None
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

    def synchronize_execution(
        self,
        execution: PoolTemperatureProbeExecutionEvidence | None,
        *,
        at: datetime,
    ) -> None:
        """Start acquisition only from verified PoolOS execution provenance."""

        if execution is None:
            if self.phase is PoolTemperatureProbePhase.PROBING:
                self.phase = PoolTemperatureProbePhase.PROBE_REQUIRED
                self.requested_at = at
                self.started_at = None
                self.samples = ()
                self.last_assessment = None
            self.execution_purpose_id = None
            self.ownership_generation = None
            return
        if self.execution_purpose_id is None:
            return
        if execution.execution_purpose_id != self.execution_purpose_id:
            self._invalidate_execution_epoch(at)
            return
        if execution.phase is PoolTemperatureProbeExecutionPhase.PREPARING:
            if self.phase is PoolTemperatureProbePhase.PROBING:
                self.phase = PoolTemperatureProbePhase.PROBE_REQUIRED
                self.started_at = None
                self.samples = ()
                self.last_assessment = None
            self.execution_purpose_id = execution.execution_purpose_id
            self.ownership_generation = execution.ownership_generation
            return
        assert execution.acquisition_started_at is not None
        if (
            self.execution_purpose_id != execution.execution_purpose_id
            or self.ownership_generation != execution.ownership_generation
            or self.started_at != execution.acquisition_started_at
        ):
            self.phase = PoolTemperatureProbePhase.PROBING
            self.started_at = execution.acquisition_started_at
            self.samples = ()
            self.last_assessment = None
        self.execution_purpose_id = execution.execution_purpose_id
        self.ownership_generation = execution.ownership_generation

    def _invalidate_execution_epoch(self, at: datetime) -> None:
        """Discard acquisition state that cannot cross a provenance boundary."""

        if self.phase in {
            PoolTemperatureProbePhase.PROBE_REQUIRED,
            PoolTemperatureProbePhase.PROBING,
        }:
            self.phase = PoolTemperatureProbePhase.PROBE_REQUIRED
            self.requested_at = at
        else:
            self.phase = PoolTemperatureProbePhase.IDLE
            self.requested_at = None
        self.started_at = None
        self.samples = ()
        self.last_assessment = None
        self.execution_purpose_id = None
        self.ownership_generation = None

    def bind_required_purpose(self, purpose_id: str) -> None:
        """Bind a recommendation to its canonical semantic probe purpose."""

        if not purpose_id.strip():
            raise ValueError("probe execution purpose must not be empty")
        if self.phase is PoolTemperatureProbePhase.PROBE_REQUIRED:
            self.execution_purpose_id = purpose_id

    def diagnostics(
        self,
        *,
        evaluated_at: datetime,
        maximum_duration: timedelta,
    ) -> Mapping[str, object]:
        """Return a bounded, observational snapshot of acquisition state."""

        _require_aware(evaluated_at)
        latest = None if not self.samples else self.samples[-1]
        oldest = None if not self.samples else self.samples[0]
        started_at = self.started_at
        return MappingProxyType(
            {
                "probe_required": self.phase is PoolTemperatureProbePhase.PROBE_REQUIRED,
                "probe_lifecycle_state": self.phase.value,
                "probe_execution_purpose_id": self.execution_purpose_id,
                "probe_ownership_generation": self.ownership_generation,
                "probe_acquisition_started_at": (
                    None if started_at is None else started_at.isoformat()
                ),
                "probe_acquisition_elapsed_seconds": (
                    None
                    if started_at is None
                    else max(0.0, (evaluated_at - started_at).total_seconds())
                ),
                "probe_acquisition_deadline": (
                    None
                    if started_at is None
                    else (started_at + maximum_duration).isoformat()
                ),
                "probe_rpm_target": _PUMP_BASELINES.temperature_probe_rpm,
                "probe_rpm_requirement": (
                    "authoritative_configured_and_actual_pool_acquisition_rpm"
                ),
                "probe_sample_count": len(self.samples),
                "probe_oldest_sample_at": (
                    None if oldest is None else oldest.observed_at.isoformat()
                ),
                "probe_latest_sample_at": (
                    None if latest is None else latest.observed_at.isoformat()
                ),
                "probe_latest_sample_f": None if latest is None else latest.temperature_f,
                "probe_stability_disposition": (
                    None if self.last_assessment is None else self.last_assessment.reason_code
                ),
            }
        )

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
        if self.started_at is not None and sample.observed_at <= self.started_at:
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
        if assessment.disposition is WaterTemperatureDisposition.TRUSTED:
            if self.phase is PoolTemperatureProbePhase.PROBING:
                self.phase = PoolTemperatureProbePhase.TRUSTED
            elif self.phase is PoolTemperatureProbePhase.PROBE_REQUIRED:
                # Independently established ordinary circulation may supersede
                # the need for acquisition, but it is not probe success.
                self.phase = PoolTemperatureProbePhase.IDLE
                self.requested_at = None
                self.started_at = None
                self.samples = ()
                self.execution_purpose_id = None
                self.ownership_generation = None
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
        self.execution_purpose_id = None
        self.ownership_generation = None


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
    pool_pump_circuit_id: str | None = None
    spa_pump_circuit_id: str | None = None
    native_observed_at: Mapping[str, datetime] = field(default_factory=dict)
    filtration_debt: timedelta | None = None
    pending_durable_incident_confirmation: bool = False
    durable_incident_confirmed: bool = False
    pool_temperature_probe_execution: PoolTemperatureProbeExecutionEvidence | None = None
    pool_temperature_probe_continuity: PoolTemperatureProbeContinuityEvidence | None = None
    spa_temperature_evidence: SpaTemperatureEvidence | None = None
    spa_session_kind: SpaSessionKind | None = None

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
    pump_circuit_id: str | None = None
    configured_pump_speed_concept: str | None = None
    live_safety_evidence: ThermalLiveSafetyEvidence | None = None
    water_temperature: WaterTemperatureAssessment | None = None
    spa_temperature: SpaTemperatureEvidence | None = None
    pool_temperature_probe_diagnostics: Mapping[str, object] = field(
        default_factory=lambda: MappingProxyType({})
    )

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "pool_temperature_probe_diagnostics",
            MappingProxyType(dict(self.pool_temperature_probe_diagnostics)),
        )

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
        attributes: dict[str, Any] = {
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
                "pump_circuit_id": self.pump_circuit_id,
                "configured_pump_speed_concept": self.configured_pump_speed_concept,
                "actual_authorized": self.actual_authorization.authorized,
                "actual_blockers": list(
                    self.actual_authorization.blocking_reasons[:blocker_limit]
                ),
                "technical_preflight_ready": self.technical_preflight.ready,
                "technical_blockers": list(
                    self.technical_preflight.blocking_reasons[:blocker_limit]
                ),
                "evidence_blockers": list(self.evidence_blockers[:blocker_limit]),
                "water_temperature_disposition": (
                    None if self.water_temperature is None else self.water_temperature.disposition.value
                ),
                "trusted_pool_temperature_f": (
                    None if self.water_temperature is None else self.water_temperature.trusted_temperature_f
                ),
                "trusted_pool_temperature_at": (
                    None
                    if self.water_temperature is None or self.water_temperature.trusted_at is None
                    else self.water_temperature.trusted_at.isoformat()
                ),
                "spa_temperature_disposition": (
                    None
                    if self.spa_temperature is None
                    else self.spa_temperature.disposition.value
                ),
                "trusted_spa_temperature_f": (
                    None
                    if self.spa_temperature is None
                    else self.spa_temperature.trusted_temperature_f
                ),
                "authority": "none",
                "automatic_execution_driver_enabled": False,
                "command_delivery_performed": False,
            }
        attributes.update(self.pool_temperature_probe_diagnostics)
        return MappingProxyType(attributes)


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
    pool_pump_circuit_id: str | None = None
    spa_pump_circuit_id: str | None = None

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
                "pool_pump_circuit_id": self.pool_pump_circuit_id,
                "spa_pump_circuit_id": self.spa_pump_circuit_id,
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
    _spa_circulation_started_at: datetime | None = field(
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
            pool_pump_circuit_id=evidence.pool_pump_circuit_id,
            spa_pump_circuit_id=evidence.spa_pump_circuit_id,
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
        pump_circuit_id = (
            evidence.pool_pump_circuit_id
            if body is ThermalBody.POOL
            else evidence.spa_pump_circuit_id
        )
        configured_speed_concept = (
            POOL_PUMP_CIRCUIT_CONFIGURED_SPEED_CONCEPT
            if body is ThermalBody.POOL
            else SPA_PUMP_CIRCUIT_CONFIGURED_SPEED_CONCEPT
        )
        relevant = {
            f"{prefix}.active",
            f"{prefix}.temperature",
            f"{prefix}.target_temperature",
            f"{prefix}.raw_heater_id",
            "pump.rpm",
            "solar.temperature",
            "solar.active",
        }
        if body is ThermalBody.HOT_TUB:
            relevant.update(
                {
                    "heater.active",
                    "spa.heating_demand_active",
                }
            )
        missing = tuple(sorted(relevant & set(evidence.missing_native_concepts)))
        stale = tuple(sorted(relevant & set(evidence.stale_native_concepts)))

        water_temperature: WaterTemperatureAssessment | None = None
        spa_temperature: SpaTemperatureEvidence | None = None
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
            if spa_active is True or (active is True and spa_active is True):
                self.water_temperature_tracker.invalidate_retained_reference()
            probe_hydraulic_concepts = {
                "pool.active",
                "spa.active",
                "pump.rpm",
                POOL_PUMP_CIRCUIT_CONFIGURED_SPEED_CONCEPT,
            }
            execution_claim = evidence.pool_temperature_probe_execution
            execution = execution_claim
            continuity = evidence.pool_temperature_probe_continuity
            if (
                execution is not None
                and execution.phase is PoolTemperatureProbeExecutionPhase.ACQUIRING
                and (
                    continuity is None
                    or continuity.evaluated_at != evidence.evaluated_at
                    or not continuity.valid
                )
            ):
                execution = None
            if (
                execution_claim is not None
                and execution_claim.phase
                is PoolTemperatureProbeExecutionPhase.ACQUIRING
                and continuity is not None
            ):
                pool_temperature_usable = (
                    pool_temperature_usable
                    and continuity.temperature_sample_usable
                )
            probe_hydraulic_evidence_usable = not (
                probe_hydraulic_concepts
                & (
                    set(evidence.missing_native_concepts)
                    | set(evidence.stale_native_concepts)
                )
            )
            ordinary_pool_circulating = (
                probe_hydraulic_evidence_usable
                and active is True
                and spa_active is False
                and pump_rpm is not None
                and pump_rpm > 0
            )
            probe_circulating = (
                ordinary_pool_circulating
                and pump_rpm is not None
                and abs(pump_rpm - _PUMP_BASELINES.temperature_probe_rpm)
                <= _ACTUAL_PUMP_RPM_TOLERANCE
                and _int_or_none(
                    values.get(POOL_PUMP_CIRCUIT_CONFIGURED_SPEED_CONCEPT)
                )
                == _PUMP_BASELINES.temperature_probe_rpm
            )
            self.pool_temperature_probe.synchronize_execution(
                execution,
                at=evidence.evaluated_at,
            )
            self.pool_temperature_probe.invalidate_if_probing(
                evidence.evaluated_at,
                pool_circulating=probe_circulating,
            )
            sample: TemperatureSample | None = None
            observed_temperature = (
                _number(values.get("pool.temperature"))
                if pool_temperature_usable
                else None
            )
            if (
                self.pool_temperature_probe.tracker_probe_active
                and probe_circulating
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
                    pool_circulating=(
                        probe_circulating
                        if self.pool_temperature_probe.tracker_probe_active
                        else ordinary_pool_circulating
                    ),
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
                    existing_circulation_trust_allowed=execution_claim is None,
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

        if body is ThermalBody.HOT_TUB:
            supplied_spa_temperature = evidence.spa_temperature_evidence
            spa_temperature_observed_at = evidence.native_observed_at.get(
                "spa.temperature"
            )
            spa_circulation_proven = (
                active is True
                and _bool_or_none(values.get("pool.active")) is False
                and pump_rpm is not None
                and pump_rpm > 0
            )
            if not spa_circulation_proven:
                self._spa_circulation_started_at = None
            elif self._spa_circulation_started_at is None:
                self._spa_circulation_started_at = evidence.evaluated_at
            spa_temperature = (
                supplied_spa_temperature
                if supplied_spa_temperature is not None
                and supplied_spa_temperature.evaluated_at == evidence.evaluated_at
                else current_spa_temperature_evidence(
                    evaluated_at=evidence.evaluated_at,
                    spa_active=active,
                    pool_active=_bool_or_none(values.get("pool.active")),
                    pump_rpm=pump_rpm,
                    observed_temperature_f=_number(values.get("spa.temperature")),
                    temperature_observed_at=spa_temperature_observed_at,
                    observation_usable=(
                        not bool(
                            {"pool.active", "spa.active", "spa.temperature", "pump.rpm"}
                            & (set(missing) | set(stale))
                        )
                        and _number(values.get("spa.temperature")) is not None
                        and self._spa_circulation_started_at is not None
                        and spa_temperature_observed_at is not None
                        and spa_temperature_observed_at
                        > self._spa_circulation_started_at
                    ),
                )
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
            spa_temperature=spa_temperature,
        )
        if desired.required_pump_rpm is not None:
            if (
                configured_speed_concept
                in evidence.missing_native_concepts
                or values.get(configured_speed_concept) is None
            ):
                blockers = tuple(
                    dict.fromkeys(
                        (*blockers, f"missing_native:{configured_speed_concept}")
                    )
                )
            if (
                configured_speed_concept
                in evidence.stale_native_concepts
            ):
                blockers = tuple(
                    dict.fromkeys(
                        (*blockers, f"stale_native:{configured_speed_concept}")
                    )
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
        planner = replace(
            self.planner,
            pump_equipment_id=pump_circuit_id,
            configured_speed_concept=configured_speed_concept,
        )
        plan = planner.build(desired, current)
        execution_currentness = ThermalExecutionCurrentness.from_assessment(
            plan,
            evaluation_id=evaluation_id,
        )
        if (
            body is ThermalBody.POOL
            and plan.desired.reason_code == "pool_temperature_probe_required"
        ):
            self.pool_temperature_probe.bind_required_purpose(
                execution_currentness.purpose.purpose_id
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
            pool_pump_circuit_id=evidence.pool_pump_circuit_id,
            target_pump_circuit_id=pump_circuit_id,
            configured_pump_speed_concept=configured_speed_concept,
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
            pump_circuit_id=pump_circuit_id,
            configured_pump_speed_concept=configured_speed_concept,
            live_safety_evidence=safety,
            water_temperature=water_temperature,
            spa_temperature=spa_temperature,
            pool_temperature_probe_diagnostics=(
                self.pool_temperature_probe.diagnostics(
                    evaluated_at=evidence.evaluated_at,
                    maximum_duration=(
                        self.water_temperature_tracker.policy.maximum_probe_duration
                    ),
                )
                if body is ThermalBody.POOL
                else MappingProxyType({})
            ),
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
        spa_temperature: SpaTemperatureEvidence | None = None,
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
                            WaterTemperatureDisposition.RETAINED,
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
                solar_configured=(
                    _string_or_none(values.get("pool.raw_heater_id")) == "H0002"
                ),
                retained_water_reference=(
                    water_temperature is not None
                    and water_temperature.disposition
                    is WaterTemperatureDisposition.RETAINED
                ),
            )
            desired = desired_pool_state(
                source_input,
                self.pool_selector.evaluate(source_input),
                evidence_usable=evidence_usable,
                blockers=blockers,
            )
            pool_active = _bool_or_none(values.get("pool.active"))
            spa_active = _bool_or_none(values.get("spa.active"))
            if pool_active is not True:
                return desired
            purpose_evidence_usable = (
                spa_active is False
                and isinstance(values.get("solar.active"), bool)
                and isinstance(values.get("heater.active"), bool)
                and _string_or_none(values.get("pool.raw_heater_id"))
                in {"00000", "H0001", "H0002"}
                and not bool(
                    {
                        "pool.active",
                        "spa.active",
                        "pool.raw_heater_id",
                        "solar.active",
                        "heater.active",
                    }
                    & (
                        set(evidence.missing_native_concepts)
                        | set(evidence.stale_native_concepts)
                    )
                )
            )
            active_purpose = assess_thermal_operating_purpose(
                ThermalOperatingPurposeEvidence(
                    body=ThermalBody.POOL,
                    body_active=pool_active,
                    other_body_active=spa_active,
                    selected_source=_physical_source(
                        _string_or_none(values.get("pool.raw_heater_id"))
                    ),
                    solar_active=_bool_or_none(values.get("solar.active")),
                    heater_active=_bool_or_none(values.get("heater.active")),
                    body_heating_demand_active=_bool_or_none(
                        values.get("heater.active")
                    ),
                    evidence_usable=purpose_evidence_usable,
                    temperature_acquisition_owned=(
                        evidence.pool_temperature_probe_execution is not None
                        and evidence.pool_temperature_probe_execution.phase
                        is PoolTemperatureProbeExecutionPhase.ACQUIRING
                        and water_temperature is not None
                        and water_temperature.disposition
                        is WaterTemperatureDisposition.PROBING
                    ),
                )
            )
            purpose_blockers = desired.blockers
            if not active_purpose.evidence_usable:
                purpose_blockers = tuple(
                    dict.fromkeys(
                        (*purpose_blockers, "pool_active_source_evidence_unusable")
                    )
                )
            required_rpm = desired.required_pump_rpm
            if (
                desired.selected_source is PhysicalHeatMode.OFF
                and desired.required_pump_rpm is None
                and evidence.pool_temperature_probe_execution is None
                and active_purpose.required_pump_rpm is not None
            ):
                required_rpm = active_purpose.required_pump_rpm
            planned_purpose = (
                active_purpose.purpose.value
                if desired.selected_source is PhysicalHeatMode.OFF
                else (
                    "solar_heating"
                    if desired.selected_source is PhysicalHeatMode.SOLAR
                    else "gas_heating"
                )
            )
            return replace(
                desired,
                reason_code=(
                    "active_pool_session_operating_purpose"
                    if desired.selected_source is PhysicalHeatMode.OFF
                    and required_rpm is not None
                    and desired.reason_code != "pool_temperature_probe_required"
                    and evidence.pool_temperature_probe_execution is None
                    else desired.reason_code
                ),
                required_pump_rpm=required_rpm,
                rpm_reason_code=(
                    desired.rpm_reason_code
                    if required_rpm == desired.required_pump_rpm
                    else (
                        "operating_purpose:"
                        f"{active_purpose.purpose.value}:{required_rpm}_rpm"
                    )
                ),
                evidence={
                    **dict(desired.evidence),
                    "active_operating_purpose": planned_purpose,
                    "current_operating_purpose": active_purpose.purpose.value,
                    "active_operating_purpose_reason": active_purpose.reason_code,
                },
                evidence_usable=desired.evidence_usable
                and active_purpose.evidence_usable,
                blockers=purpose_blockers,
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
        spa_active = values.get("spa.active") is True
        spa_session_kind = (
            evidence.spa_session_kind
            if spa_active
            and evidence.spa_session_kind is SpaSessionKind.POOLOS_OPPORTUNISTIC
            else (
                SpaSessionKind.EXTERNAL_USER
                if spa_active
                else SpaSessionKind.INACTIVE
            )
        )
        active_purpose = assess_thermal_operating_purpose(
            ThermalOperatingPurposeEvidence(
                body=ThermalBody.HOT_TUB,
                body_active=_bool_or_none(values.get("spa.active")),
                other_body_active=_bool_or_none(values.get("pool.active")),
                selected_source=_physical_source(
                    _string_or_none(values.get("spa.raw_heater_id"))
                ),
                solar_active=_bool_or_none(values.get("solar.active")),
                heater_active=_bool_or_none(values.get("heater.active")),
                body_heating_demand_active=_bool_or_none(
                    values.get("spa.heating_demand_active")
                ),
                evidence_usable=(
                    not bool(
                        {
                            "pool.active",
                            "spa.active",
                            "spa.raw_heater_id",
                            "solar.active",
                            "heater.active",
                            "spa.heating_demand_active",
                        }
                        & (
                            set(evidence.missing_native_concepts)
                            | set(evidence.stale_native_concepts)
                        )
                    )
                    and all(
                        isinstance(values.get(concept), bool)
                        for concept in (
                            "pool.active",
                            "spa.active",
                            "solar.active",
                            "heater.active",
                            "spa.heating_demand_active",
                        )
                    )
                    and _string_or_none(values.get("spa.raw_heater_id"))
                    in {"00000", "H0001", "H0002"}
                ),
            )
        )
        active_heat_source = {
            PhysicalHeatMode.SOLAR: ThermalHeatSource.SOLAR,
            PhysicalHeatMode.GAS: ThermalHeatSource.GAS,
        }.get(
            active_purpose.active_source
            if active_purpose.active_source is not None
            else PhysicalHeatMode.OFF,
            ThermalHeatSource.NONE,
        )
        spa_temperature_trusted = bool(
            spa_temperature is not None
            and spa_temperature.disposition is SpaTemperatureDisposition.TRUSTED
        )
        trusted_spa_temperature = (
            None
            if not spa_temperature_trusted or spa_temperature is None
            else spa_temperature.trusted_temperature_f
        )
        if spa_active and (
            not active_purpose.evidence_usable
            or (
                spa_session_kind is SpaSessionKind.EXTERNAL_USER
                and not spa_temperature_trusted
            )
        ):
            active_blockers = tuple(blockers)
            if not active_purpose.evidence_usable:
                active_blockers = tuple(
                    dict.fromkeys(
                        (*active_blockers, "spa_active_source_evidence_unusable")
                    )
                )
            if active_purpose.required_pump_rpm is None:
                active_blockers = tuple(
                    dict.fromkeys(
                        (*active_blockers, "spa_operating_purpose_unresolved")
                    )
                )
            return ThermalDesiredState(
                evaluated_at=evidence.evaluated_at,
                body=ThermalBody.HOT_TUB,
                requested_mode=requested_mode.value,
                selected_source=(
                    _physical_source(_string_or_none(values.get("spa.raw_heater_id")))
                    if active_purpose.required_pump_rpm is not None
                    else PhysicalHeatMode.OFF
                ),
                required_pump_rpm=active_purpose.required_pump_rpm,
                reason_code="external_spa_session_operating_purpose",
                rpm_reason_code=(
                    None
                    if active_purpose.required_pump_rpm is None
                    else (
                        "operating_purpose:"
                        f"{active_purpose.purpose.value}:"
                        f"{active_purpose.required_pump_rpm}_rpm"
                    )
                ),
                rationale=(
                    "External Spa body ownership remains external.",
                    "Pump governance follows authoritative active heat delivery.",
                ),
                criteria=(
                    "external_spa_session",
                    active_purpose.reason_code,
                    "spa_temperature_pending_current_circulation",
                    "source_selection_retained",
                ),
                evidence={
                    "session_kind": spa_session_kind.value,
                    "active_operating_purpose": active_purpose.purpose.value,
                    "selected_source": _physical_source(
                        _string_or_none(values.get("spa.raw_heater_id"))
                    ).value,
                    "spa_temperature_disposition": (
                        None
                        if spa_temperature is None
                        else spa_temperature.disposition.value
                    ),
                    "body_activation_owned": False,
                },
                evidence_usable=not active_blockers,
                blockers=active_blockers,
            )
        spa_input = SpaPolicyInput(
            evaluated_at=evidence.evaluated_at,
            spa_active=spa_active,
            transition_source=(
                SpaUserSource.NATIVE if values.get("spa.active") is True else None
            ),
            spa_temperature_f=trusted_spa_temperature,
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
            session_kind=spa_session_kind,
            spa_temperature_trusted=spa_temperature_trusted,
            active_heat_source=active_heat_source,
            active_heat_source_usable=active_purpose.evidence_usable,
        )
        spa_desired = desired_spa_state(
            spa_input,
            self.spa_tracker.evaluate(spa_input),
            evidence_usable=evidence_usable,
            blockers=blockers,
        )
        if not spa_active or not spa_temperature_trusted:
            return spa_desired

        target = _number(values.get("spa.target_temperature"))
        below_target = (
            trusted_spa_temperature is not None
            and target is not None
            and trusted_spa_temperature < target
        )
        selected_source = _physical_source(
            _string_or_none(values.get("spa.raw_heater_id"))
        )
        required_rpm = spa_desired.required_pump_rpm
        planned_purpose = active_purpose.purpose.value
        if (
            below_target
            and spa_desired.selected_source is PhysicalHeatMode.GAS
        ):
            required_rpm = _PUMP_BASELINES.gas_heating_rpm
            planned_purpose = "gas_heating"
        elif (
            below_target
            and spa_desired.selected_source is PhysicalHeatMode.SOLAR
        ):
            required_rpm = _PUMP_BASELINES.solar_heating_rpm
            planned_purpose = "solar_heating"
        elif not below_target and active_heat_source is ThermalHeatSource.NONE:
            required_rpm = _PUMP_BASELINES.filtration_rpm
            planned_purpose = "ordinary_circulation"
            spa_desired = replace(spa_desired, selected_source=selected_source)
        return replace(
            spa_desired,
            required_pump_rpm=required_rpm,
            rpm_reason_code=(
                None
                if required_rpm is None
                else f"operating_purpose:{planned_purpose}:{required_rpm}_rpm"
            ),
            evidence={
                **dict(spa_desired.evidence),
                "active_operating_purpose": planned_purpose,
                "current_operating_purpose": active_purpose.purpose.value,
            },
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
        "pool_pump_circuit_id": evidence.pool_pump_circuit_id,
        "spa_pump_circuit_id": evidence.spa_pump_circuit_id,
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
