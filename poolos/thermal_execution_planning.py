"""Command-disabled coupled thermal-source and pump-RPM planning.

This boundary adapts existing pool and spa policy assessments into canonical
operations and existing execution-step specifications.  It performs no
authorization, translation, delivery, retry, polling, or equipment I/O.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from hashlib import sha256
import json
from types import MappingProxyType
from typing import Any, Mapping

from .execution_plans import ExecutionStepSpecification
from .integration import (
    PhysicalHeatMode,
    PoolOperation,
    SetBodyActive,
    SetHeatMode,
    SetPumpSpeed,
    ThermalBody,
)
from .pump_priming_policy import PumpPrimingPolicy
from .spa_thermal_policy import SpaHeatingMode, SpaPolicyAssessment, SpaPolicyInput
from .thermal_source_policy import (
    PoolHeatingMode,
    ThermalHeatSource,
    ThermalOperatingAssessment,
    ThermalOperatingMode,
    ThermalSourceInput,
)


_HEATER_ID_BY_MODE = {
    PhysicalHeatMode.OFF: "00000",
    PhysicalHeatMode.GAS: "H0001",
    PhysicalHeatMode.SOLAR: "H0002",
}
_HEATER_OBSERVATION_BY_BODY = {
    ThermalBody.POOL: "pool.raw_heater_id",
    ThermalBody.HOT_TUB: "spa.raw_heater_id",
}


class ThermalPlanDisposition(StrEnum):
    READY = "ready"
    ALREADY_CONVERGED = "already_converged"
    BLOCKED = "blocked"


@dataclass(frozen=True, slots=True)
class ThermalDesiredState:
    """Auditable coupled physical state selected by an existing policy."""

    evaluated_at: datetime
    body: ThermalBody
    requested_mode: str
    selected_source: PhysicalHeatMode
    required_pump_rpm: int | None
    reason_code: str
    rpm_reason_code: str | None
    rationale: tuple[str, ...]
    criteria: tuple[str, ...]
    evidence: Mapping[str, Any]
    fallback_reason: str | None = None
    evidence_usable: bool = True
    blockers: tuple[str, ...] = ()
    authority: str = "none"
    command_delivery_enabled: bool = False

    def __post_init__(self) -> None:
        if self.evaluated_at.tzinfo is None or self.evaluated_at.utcoffset() is None:
            raise ValueError("evaluated_at must be timezone-aware")
        if not self.requested_mode.strip() or not self.reason_code.strip():
            raise ValueError("requested_mode and reason_code must not be empty")
        if self.selected_source is PhysicalHeatMode.OFF:
            if self.required_pump_rpm is not None:
                if self.required_pump_rpm <= 0:
                    raise ValueError("required pump RPM must be positive")
                if self.reason_code != "pool_temperature_probe_required":
                    raise ValueError(
                        "off heat source may require pump RPM only for pool temperature probe"
                    )
        elif self.required_pump_rpm is None or self.required_pump_rpm <= 0:
            raise ValueError("selected heat source requires a positive pump RPM")
        if not self.rationale or any(not item.strip() for item in self.rationale):
            raise ValueError("rationale must contain non-empty evidence")
        if any(not item.strip() for item in self.criteria):
            raise ValueError("criteria must not contain empty values")
        if any(not item.strip() for item in self.blockers):
            raise ValueError("blockers must not contain empty values")
        if self.command_delivery_enabled or self.authority != "none":
            raise ValueError("thermal desired state must remain command-disabled")
        object.__setattr__(self, "rationale", tuple(self.rationale))
        object.__setattr__(self, "criteria", tuple(self.criteria))
        object.__setattr__(self, "blockers", tuple(self.blockers))
        object.__setattr__(self, "evidence", MappingProxyType(dict(self.evidence)))


@dataclass(frozen=True, slots=True)
class ThermalCurrentState:
    """Explicit native facts used to avoid unnecessary thermal commands."""

    observed_at: datetime
    body: ThermalBody
    selected_source: PhysicalHeatMode
    pump_rpm: int | None
    body_active: bool | None = None
    source_evidence_usable: bool = True
    pump_evidence_usable: bool = True
    blockers: tuple[str, ...] = ()
    htmode: str | None = None

    def __post_init__(self) -> None:
        if self.observed_at.tzinfo is None or self.observed_at.utcoffset() is None:
            raise ValueError("observed_at must be timezone-aware")
        if self.pump_rpm is not None and self.pump_rpm < 0:
            raise ValueError("pump_rpm must not be negative")
        if any(not blocker.strip() for blocker in self.blockers):
            raise ValueError("blockers must not contain empty values")
        object.__setattr__(self, "blockers", tuple(self.blockers))


@dataclass(frozen=True, slots=True)
class ThermalExecutionPlanAssessment:
    """Immutable proposal-ready operations; never execution authorization."""

    plan_id: str
    disposition: ThermalPlanDisposition
    desired: ThermalDesiredState
    current: ThermalCurrentState
    operations: tuple[PoolOperation, ...]
    step_specifications: tuple[ExecutionStepSpecification, ...]
    expected_final_state: Mapping[str, Any]
    change_reasons: tuple[str, ...]
    blocking_reasons: tuple[str, ...] = ()
    authority: str = "none"
    command_delivery_enabled: bool = False

    def __post_init__(self) -> None:
        if not self.plan_id.strip():
            raise ValueError("plan_id must not be empty")
        if len(self.operations) != len(self.step_specifications):
            raise ValueError("every operation requires one step specification")
        if tuple(item.operation_id for item in self.step_specifications) != tuple(
            item.operation_id for item in self.operations
        ):
            raise ValueError("step specifications must preserve operation order")
        if self.disposition is ThermalPlanDisposition.READY and not self.operations:
            raise ValueError("ready plan requires operations")
        if self.disposition is not ThermalPlanDisposition.READY and self.operations:
            raise ValueError("non-ready plan cannot contain operations")
        if self.disposition is ThermalPlanDisposition.BLOCKED and not self.blocking_reasons:
            raise ValueError("blocked plan requires blocking reasons")
        if self.command_delivery_enabled or self.authority != "none":
            raise ValueError("thermal plan must remain command-disabled")
        object.__setattr__(self, "operations", tuple(self.operations))
        object.__setattr__(self, "step_specifications", tuple(self.step_specifications))
        object.__setattr__(self, "change_reasons", tuple(self.change_reasons))
        object.__setattr__(self, "blocking_reasons", tuple(self.blocking_reasons))
        object.__setattr__(
            self,
            "expected_final_state",
            MappingProxyType(dict(self.expected_final_state)),
        )


def desired_pool_state(
    observation: ThermalSourceInput,
    assessment: ThermalOperatingAssessment,
    *,
    evidence_usable: bool = True,
    blockers: tuple[str, ...] = (),
) -> ThermalDesiredState:
    """Preserve one existing pool-policy result as coupled desired state."""

    selected_source = _physical_mode(assessment.heat_source)
    permission_blocked = assessment.reason_code in {
        "gas_permission_veto",
        "solar_permission_veto",
        "source_permission_veto",
    }
    pool_temperature_available = (
        observation.trusted_pool_temperature_f is not None
        and observation.pool_target_f is not None
    )
    probe_required = (
        assessment.mode is ThermalOperatingMode.POOL_TEMPERATURE_PROBE
    )
    required_available = probe_required or (
        pool_temperature_available
        and (
            selected_source is PhysicalHeatMode.OFF
            or (
                observation.heating_mode is PoolHeatingMode.GAS_ONLY
                or observation.collector_temperature_f is not None
            )
        )
    )
    effective_blockers = tuple(blockers)
    if not required_available:
        effective_blockers += ("required_pool_thermal_evidence_unavailable",)
    if permission_blocked:
        effective_blockers += ("heat_source_permission_veto",)
    rationale = (
        f"Pool policy selected {selected_source.value} for {observation.heating_mode.value}.",
        *assessment.solar_assessment.rationale,
    )
    criteria = (
        assessment.solar_assessment.reason_code,
        "forecast_gate_passed" if assessment.forecast_gate_passed else "forecast_gate_blocked",
        "gas_allowed" if observation.permissions.gas_allowed else "gas_vetoed",
        "solar_allowed" if observation.permissions.solar_allowed else "solar_vetoed",
    )
    evidence = {
        "pool_temperature_f": observation.trusted_pool_temperature_f,
        "pool_target_f": observation.pool_target_f,
        "collector_temperature_f": observation.collector_temperature_f,
        "collector_differential_f": assessment.solar_assessment.differential_f,
        "solar_eligible": assessment.solar_assessment.eligible,
        "solar_active": observation.solar_active,
        "pool_active": observation.pool_active,
        "spa_active": observation.spa_active,
        "forecast_gate_applied": assessment.forecast_gate_applied,
        "forecast_gate_passed": assessment.forecast_gate_passed,
    }
    return ThermalDesiredState(
        evaluated_at=assessment.evaluated_at,
        body=ThermalBody.POOL,
        requested_mode=observation.heating_mode.value,
        selected_source=selected_source,
        required_pump_rpm=assessment.recommended_pump_rpm,
        reason_code=assessment.reason_code,
        rpm_reason_code=_rpm_reason(assessment.mode.value, assessment.recommended_pump_rpm),
        rationale=rationale,
        criteria=criteria,
        evidence=evidence,
        fallback_reason=(
            assessment.reason_code if "fallback" in assessment.reason_code else None
        ),
        evidence_usable=evidence_usable and required_available and not permission_blocked,
        blockers=effective_blockers,
    )


def desired_spa_state(
    observation: SpaPolicyInput,
    assessment: SpaPolicyAssessment,
    *,
    evidence_usable: bool = True,
    blockers: tuple[str, ...] = (),
) -> ThermalDesiredState:
    """Preserve one existing spa-policy result as coupled desired state."""

    selected_source = _physical_mode(assessment.heat_source)
    permission_blocked = assessment.reason_code == "gas_permission_veto"
    spa_temperature_available = (
        observation.spa_temperature_f is not None
        and observation.spa_target_f is not None
    )
    required_available = spa_temperature_available and (
        selected_source is PhysicalHeatMode.OFF
        or (
            observation.heating_mode is SpaHeatingMode.GAS_ONLY
            or observation.collector_temperature_f is not None
        )
    )
    effective_blockers = tuple(blockers)
    if not required_available:
        effective_blockers += ("required_spa_thermal_evidence_unavailable",)
    if permission_blocked:
        effective_blockers += ("heat_source_permission_veto",)
    session_kind = "user_session" if assessment.spa_in_use else "opportunistic"
    criteria = (
        session_kind,
        assessment.state.value,
        "gas_fallback_allowed" if assessment.spa_in_use else "gas_fallback_forbidden",
        "solar_allowed" if observation.permissions.solar_allowed else "solar_vetoed",
    )
    return ThermalDesiredState(
        evaluated_at=assessment.evaluated_at,
        body=ThermalBody.HOT_TUB,
        requested_mode=observation.heating_mode.value,
        selected_source=selected_source,
        required_pump_rpm=assessment.recommended_pump_rpm,
        reason_code=assessment.reason_code,
        rpm_reason_code=_rpm_reason(assessment.state.value, assessment.recommended_pump_rpm),
        rationale=(
            f"Spa policy selected {selected_source.value} for {session_kind}.",
            f"Spa policy state is {assessment.state.value}.",
        ),
        criteria=criteria,
        evidence={
            "spa_temperature_f": observation.spa_temperature_f,
            "spa_target_f": observation.spa_target_f,
            "collector_temperature_f": observation.collector_temperature_f,
            "spa_active": observation.spa_active,
            "spa_in_use": assessment.spa_in_use,
            "pool_demand_satisfied": observation.pool_demand_satisfied,
            "filtration_debt_seconds": (
                None
                if observation.filtration_debt is None
                else observation.filtration_debt.total_seconds()
            ),
            "higher_priority_conflict": observation.higher_priority_conflict,
        },
        fallback_reason=(
            assessment.reason_code if assessment.heat_source is ThermalHeatSource.GAS else None
        ),
        evidence_usable=evidence_usable and required_available and not permission_blocked,
        blockers=effective_blockers,
    )


@dataclass(frozen=True, slots=True)
class ThermalExecutionPlanBuilder:
    """Create ordered canonical operations without authorizing or delivering them."""

    pump_equipment_id: str = "p0102"
    pump_rpm_tolerance: int = 25

    def __post_init__(self) -> None:
        if not self.pump_equipment_id.strip():
            raise ValueError("pump_equipment_id must not be empty")
        if self.pump_rpm_tolerance < 0:
            raise ValueError("pump_rpm_tolerance must not be negative")

    def build(
        self,
        desired: ThermalDesiredState,
        current: ThermalCurrentState,
    ) -> ThermalExecutionPlanAssessment:
        if current.body is not desired.body:
            return self._non_ready(desired, current, ("thermal_body_mismatch",))
        blockers = tuple(
            dict.fromkeys(
                (
                    *desired.blockers,
                    *current.blockers,
                    *(() if desired.evidence_usable else ("desired_evidence_unusable",)),
                    *(
                        ()
                        if current.source_evidence_usable
                        else ("source_observation_unusable",)
                    ),
                    *(
                        ()
                        if desired.selected_source is PhysicalHeatMode.OFF
                        or current.pump_evidence_usable
                        else ("pump_observation_unusable",)
                    ),
                    *(
                        ()
                        if desired.selected_source is PhysicalHeatMode.OFF
                        or current.pump_rpm is not None
                        else ("pump_observation_missing",)
                    ),
                )
            )
        )
        if blockers:
            return self._non_ready(desired, current, blockers)

        source_changed = current.selected_source is not desired.selected_source
        desired_rpm = desired.required_pump_rpm
        rpm_changed = desired_rpm is not None and not _rpm_converged(
            current.pump_rpm,
            desired_rpm,
            tolerance=self.pump_rpm_tolerance,
        )
        if not source_changed and not rpm_changed:
            return self._non_ready(desired, current, ())

        ordering: list[str] = []

        circulation_required = desired.required_pump_rpm is not None
        body_start_required = circulation_required and current.body_active is False

        priming = PumpPrimingPolicy().evaluate(
            circulation_requested=circulation_required,
            currently_circulating=(
                current.pump_rpm is not None and current.pump_rpm > 0
            ),
        )

        if body_start_required:
            ordering.append("body")

        if priming.priming_required:
            ordering.append("prime")

            if (
                desired.required_pump_rpm is not None
                and desired.required_pump_rpm != priming.priming_rpm
            ):
                ordering.append("rpm")

            if source_changed:
                ordering.append("source")
        elif desired.selected_source is PhysicalHeatMode.OFF:
            if source_changed:
                ordering.append("source")
            if rpm_changed:
                ordering.append("rpm")
        elif source_changed and rpm_changed:
            assert desired_rpm is not None
            assert current.pump_rpm is not None
            if (
                current.pump_rpm < desired_rpm
                or current.selected_source is PhysicalHeatMode.OFF
            ):
                ordering.extend(("rpm", "source"))
            else:
                ordering.extend(("source", "rpm"))
        elif source_changed:
            ordering.append("source")
        elif rpm_changed:
            ordering.append("rpm")

        plan_id = self._plan_id(desired, current, tuple(ordering))
        operations: list[PoolOperation] = []
        specifications: list[ExecutionStepSpecification] = []
        for sequence, kind in enumerate(ordering, start=1):
            operation_id = f"{plan_id}:operation:{sequence}:{kind}"
            expected: dict[str, Any]
            metadata: dict[str, str]
            operation: PoolOperation
            if kind == "body":
                operation = SetBodyActive(
                    equipment_id=desired.body.value,
                    active=True,
                    operation_id=operation_id,
                    metadata={
                        "reason_code": "thermal_body_activation_required",
                        "command_delivery_enabled": False,
                    },
                )
                expected = {
                    (
                        "pool.active"
                        if desired.body is ThermalBody.POOL
                        else "spa.active"
                    ): True
                }
                metadata = {
                    "verification_truth": "authoritative_native_body_active",
                }
            elif kind == "prime":
                assert priming.priming_rpm is not None
                assert priming.minimum_duration is not None

                operation = SetPumpSpeed(
                    equipment_id=self.pump_equipment_id,
                    rpm=priming.priming_rpm,
                    operation_id=operation_id,
                    metadata={
                        "reason_code": "cold_start_pump_priming",
                        "command_delivery_enabled": False,
                    },
                )
                expected = {"pump.rpm": priming.priming_rpm}
                metadata = {
                    "verification_truth": "authoritative_native_pump_rpm",
                    "numeric_tolerance:pump.rpm": str(self.pump_rpm_tolerance),
                    "priming_step": "true",
                    "minimum_verified_hold_seconds": str(
                        int(priming.minimum_duration.total_seconds())
                    ),
                }
            elif kind == "source":
                operation = SetHeatMode(
                    equipment_id=desired.body.value,
                    mode=desired.selected_source,
                    operation_id=operation_id,
                    metadata={
                        "reason_code": desired.reason_code,
                        "command_delivery_enabled": False,
                    },
                )
                expected = {
                    _HEATER_OBSERVATION_BY_BODY[desired.body]: _HEATER_ID_BY_MODE[
                        desired.selected_source
                    ]
                }
                metadata = {
                    "verification_truth": "HEATER",
                    "htmode_is_context_only": "true",
                }
            else:
                assert desired.required_pump_rpm is not None
                operation = SetPumpSpeed(
                    equipment_id=self.pump_equipment_id,
                    rpm=desired.required_pump_rpm,
                    operation_id=operation_id,
                    metadata={
                        "reason_code": desired.rpm_reason_code or "thermal_pump_baseline",
                        "command_delivery_enabled": False,
                    },
                )
                expected = {"pump.rpm": desired.required_pump_rpm}
                metadata = {
                    "verification_truth": "authoritative_native_pump_rpm",
                    "numeric_tolerance:pump.rpm": str(self.pump_rpm_tolerance),
                }
            operations.append(operation)
            specifications.append(
                ExecutionStepSpecification(
                    operation_id=operation_id,
                    preconditions={
                        "fresh_evidence_required": True,
                        "command_delivery_enabled": False,
                    },
                    expected_observations=expected,
                    metadata={
                        **metadata,
                        "hydraulic_continuity_required": "true",
                        "hydraulic_target_body": desired.body.value,
                    },
                )
            )

        expected_final_state: dict[str, Any] = {
            _HEATER_OBSERVATION_BY_BODY[desired.body]: _HEATER_ID_BY_MODE[
                desired.selected_source
            ]
        }
        if desired.required_pump_rpm is not None:
            expected_final_state["pump.rpm"] = desired.required_pump_rpm
        change_reasons = tuple(
            reason
            for changed, reason in (
                (body_start_required, "target_body_activation_required"),
                (priming.priming_required, "cold_start_priming_required"),
                (source_changed, "selected_heat_source_changed"),
                (rpm_changed, "thermal_pump_baseline_changed"),
            )
            if changed
        )
        return ThermalExecutionPlanAssessment(
            plan_id=plan_id,
            disposition=ThermalPlanDisposition.READY,
            desired=desired,
            current=current,
            operations=tuple(operations),
            step_specifications=tuple(specifications),
            expected_final_state=expected_final_state,
            change_reasons=change_reasons,
        )

    def _non_ready(
        self,
        desired: ThermalDesiredState,
        current: ThermalCurrentState,
        blockers: tuple[str, ...],
    ) -> ThermalExecutionPlanAssessment:
        disposition = (
            ThermalPlanDisposition.BLOCKED
            if blockers
            else ThermalPlanDisposition.ALREADY_CONVERGED
        )
        return ThermalExecutionPlanAssessment(
            plan_id=self._plan_id(desired, current, (disposition.value,)),
            disposition=disposition,
            desired=desired,
            current=current,
            operations=(),
            step_specifications=(),
            expected_final_state={},
            change_reasons=(),
            blocking_reasons=blockers,
        )

    def _plan_id(
        self,
        desired: ThermalDesiredState,
        current: ThermalCurrentState,
        ordering: tuple[str, ...],
    ) -> str:
        payload = {
            "body": desired.body.value,
            "current_rpm": current.pump_rpm,
            "current_source": current.selected_source.value,
            "evaluated_at": desired.evaluated_at.isoformat(),
            "ordering": ordering,
            "reason_code": desired.reason_code,
            "requested_mode": desired.requested_mode,
            "required_rpm": desired.required_pump_rpm,
            "selected_source": desired.selected_source.value,
        }
        canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"))
        return "thermal-plan-" + sha256(canonical.encode("utf-8")).hexdigest()[:24]


def _physical_mode(source: ThermalHeatSource) -> PhysicalHeatMode:
    return {
        ThermalHeatSource.NONE: PhysicalHeatMode.OFF,
        ThermalHeatSource.GAS: PhysicalHeatMode.GAS,
        ThermalHeatSource.SOLAR: PhysicalHeatMode.SOLAR,
    }[source]


def _rpm_reason(operating_mode: str, rpm: int | None) -> str | None:
    return None if rpm is None else f"operating_baseline:{operating_mode}:{rpm}_rpm"


def _rpm_converged(actual: int | None, desired: int, *, tolerance: int) -> bool:
    return actual is not None and abs(actual - desired) <= tolerance


__all__ = [
    "ThermalCurrentState",
    "ThermalDesiredState",
    "ThermalExecutionPlanAssessment",
    "ThermalExecutionPlanBuilder",
    "ThermalPlanDisposition",
    "desired_pool_state",
    "desired_spa_state",
]
