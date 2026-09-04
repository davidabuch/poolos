"""Canonical semantic currentness for thermal execution and ownership.

Evaluation and plan identifiers remain concrete audit identities.  This module
adds the separate, timestamp-independent execution purpose and proves whether a
new residual plan can be explained by accepted or verified PoolOS progress.
It performs no authorization, delivery, observation, or equipment I/O.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from hashlib import sha256
import json
from math import isfinite
from typing import Mapping

from .integration import (
    PhysicalHeatMode,
    PoolOperation,
    SetBodyActive,
    SetHeatMode,
    SetPumpSpeed,
    ThermalBody,
)
from .thermal_execution_planning import (
    ThermalExecutionPlanAssessment,
    ThermalPlanDisposition,
)


class ThermalExecutionPurposeKind(StrEnum):
    """Material class of one thermal objective."""

    THERMAL_CONTROL = "thermal_control"
    EXPLICIT_OFF = "explicit_off"
    POOL_TEMPERATURE_PROBE = "pool_temperature_probe"


@dataclass(frozen=True, slots=True)
class ThermalExecutionPurpose:
    """Stable bounded semantic objective, independent of observation time."""

    purpose_id: str
    body: ThermalBody
    requested_mode: str
    selected_source: PhysicalHeatMode
    required_pump_rpm: int | None
    target_temperature_f: float | None
    kind: ThermalExecutionPurposeKind
    schema_version: int = 1

    def __post_init__(self) -> None:
        if self.schema_version != 1:
            raise ValueError("unsupported thermal execution purpose schema")
        if not self.requested_mode.strip():
            raise ValueError("requested_mode must not be empty")
        if self.required_pump_rpm is not None and self.required_pump_rpm <= 0:
            raise ValueError("required_pump_rpm must be positive or None")
        object.__setattr__(self, "body", ThermalBody(self.body))
        object.__setattr__(self, "selected_source", PhysicalHeatMode(self.selected_source))
        object.__setattr__(self, "kind", ThermalExecutionPurposeKind(self.kind))
        if self.target_temperature_f is not None and not isfinite(
            self.target_temperature_f
        ):
            raise ValueError("target_temperature_f must be finite or None")
        expected_id = _purpose_id(
            body=self.body,
            requested_mode=self.requested_mode,
            selected_source=self.selected_source,
            required_pump_rpm=self.required_pump_rpm,
            target_temperature_f=self.target_temperature_f,
            kind=self.kind,
        )
        if self.purpose_id != expected_id:
            raise ValueError("malformed thermal execution purpose identity")


@dataclass(frozen=True, slots=True)
class ThermalOperationSignature:
    """Material structure of one residual thermal operation."""

    operation_type: str
    equipment_id: str
    requested_value: str
    role: str
    minimum_verified_hold_seconds: int | None = None

    def __post_init__(self) -> None:
        for name in ("operation_type", "equipment_id", "requested_value", "role"):
            if not getattr(self, name).strip():
                raise ValueError(f"{name} must not be empty")
        if (
            self.minimum_verified_hold_seconds is not None
            and self.minimum_verified_hold_seconds <= 0
        ):
            raise ValueError("minimum verified hold must be positive or None")


@dataclass(frozen=True, slots=True)
class ThermalResidualPlan:
    """One concrete planner result represented without epoch-sensitive IDs."""

    disposition: ThermalPlanDisposition
    operations: tuple[ThermalOperationSignature, ...]

    def __post_init__(self) -> None:
        disposition = ThermalPlanDisposition(self.disposition)
        if disposition is ThermalPlanDisposition.READY and not self.operations:
            raise ValueError("ready residual plan requires operations")
        if disposition is not ThermalPlanDisposition.READY and self.operations:
            raise ValueError("non-ready residual plan cannot contain operations")
        object.__setattr__(self, "disposition", disposition)
        object.__setattr__(self, "operations", tuple(self.operations))


@dataclass(frozen=True, slots=True)
class ThermalExecutionCurrentness:
    """Concrete epoch/plan audit identity plus stable semantic currentness."""

    evaluation_id: str
    plan_id: str
    purpose: ThermalExecutionPurpose
    residual_plan: ThermalResidualPlan

    def __post_init__(self) -> None:
        if not self.evaluation_id.strip() or not self.plan_id.strip():
            raise ValueError("evaluation_id and plan_id must not be empty")

    @classmethod
    def from_assessment(
        cls,
        assessment: ThermalExecutionPlanAssessment,
        *,
        evaluation_id: str,
    ) -> ThermalExecutionCurrentness:
        """Build the canonical identities for one current planner assessment."""

        purpose = purpose_from_assessment(assessment)
        return cls(
            evaluation_id=evaluation_id,
            plan_id=assessment.plan_id,
            purpose=purpose,
            residual_plan=residual_plan_from_assessment(assessment),
        )


@dataclass(frozen=True, slots=True)
class ThermalExecutionProgress:
    """PoolOS-proven progress through one originating operation sequence."""

    verified_prefix: tuple[ThermalOperationSignature, ...] = ()
    accepted_current: ThermalOperationSignature | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "verified_prefix", tuple(self.verified_prefix))


class ThermalExecutionCompatibilityDisposition(StrEnum):
    """Typed relationship between originating and current runtime truth."""

    SAME_PURPOSE = "same_purpose"
    PROGRESS_COMPATIBLE = "progress_compatible"
    CONVERGED = "converged"
    SUPERSEDED = "superseded"
    UNKNOWN = "unknown"


@dataclass(frozen=True, slots=True)
class ThermalExecutionCompatibilityDecision:
    """Non-authorizing semantic/progress compatibility result."""

    disposition: ThermalExecutionCompatibilityDisposition
    reason_code: str
    originating_evaluation_id: str
    originating_plan_id: str
    current_evaluation_id: str
    current_plan_id: str
    execution_purpose_id: str | None
    command_delivery_enabled: bool = False

    def __post_init__(self) -> None:
        if not self.reason_code.strip():
            raise ValueError("compatibility reason_code must not be empty")
        for name in (
            "originating_evaluation_id",
            "originating_plan_id",
            "current_evaluation_id",
            "current_plan_id",
        ):
            if not getattr(self, name).strip():
                raise ValueError(f"{name} must not be empty")
        if self.command_delivery_enabled:
            raise ValueError("currentness compatibility cannot authorize delivery")

    @property
    def continuation_allowed(self) -> bool:
        return self.disposition in {
            ThermalExecutionCompatibilityDisposition.SAME_PURPOSE,
            ThermalExecutionCompatibilityDisposition.PROGRESS_COMPATIBLE,
            ThermalExecutionCompatibilityDisposition.CONVERGED,
        }


def purpose_from_assessment(
    assessment: ThermalExecutionPlanAssessment,
) -> ThermalExecutionPurpose:
    """Derive stable purpose from material desired thermal semantics."""

    desired = assessment.desired
    kind = (
        ThermalExecutionPurposeKind.POOL_TEMPERATURE_PROBE
        if desired.reason_code == "pool_temperature_probe_required"
        else (
            ThermalExecutionPurposeKind.EXPLICIT_OFF
            if desired.requested_mode == "off"
            else ThermalExecutionPurposeKind.THERMAL_CONTROL
        )
    )
    target_key = (
        "pool_target_f" if desired.body is ThermalBody.POOL else "spa_target_f"
    )
    target_raw = desired.evidence.get(target_key)
    target = (
        float(target_raw)
        if isinstance(target_raw, (int, float)) and not isinstance(target_raw, bool)
        else None
    )
    purpose_id = _purpose_id(
        body=desired.body,
        requested_mode=desired.requested_mode,
        selected_source=desired.selected_source,
        required_pump_rpm=desired.required_pump_rpm,
        target_temperature_f=target,
        kind=kind,
    )
    return ThermalExecutionPurpose(
        purpose_id=purpose_id,
        body=desired.body,
        requested_mode=desired.requested_mode,
        selected_source=desired.selected_source,
        required_pump_rpm=desired.required_pump_rpm,
        target_temperature_f=target,
        kind=kind,
    )


def _purpose_id(
    *,
    body: ThermalBody,
    requested_mode: str,
    selected_source: PhysicalHeatMode,
    required_pump_rpm: int | None,
    target_temperature_f: float | None,
    kind: ThermalExecutionPurposeKind,
) -> str:
    material = {
        "schema_version": 1,
        "body": body.value,
        "requested_mode": requested_mode,
        "selected_source": selected_source.value,
        "required_pump_rpm": required_pump_rpm,
        "target_temperature_f": target_temperature_f,
        "kind": kind.value,
    }
    canonical = json.dumps(material, sort_keys=True, separators=(",", ":"))
    return "thermal-execution-purpose-v1-" + sha256(
        canonical.encode("utf-8")
    ).hexdigest()[:24]


def residual_plan_from_assessment(
    assessment: ThermalExecutionPlanAssessment,
) -> ThermalResidualPlan:
    """Return the bounded material operation sequence for one plan instance."""

    signatures = tuple(
        operation_signature(operation, specification.metadata)
        for operation, specification in zip(
            assessment.operations,
            assessment.step_specifications,
            strict=True,
        )
    )
    return ThermalResidualPlan(assessment.disposition, signatures)


def operation_signature(
    operation: PoolOperation,
    metadata: Mapping[str, object],
) -> ThermalOperationSignature:
    """Normalize one canonical thermal operation and its safety-relevant role."""

    values = dict(metadata)
    if isinstance(operation, SetBodyActive):
        requested_value = "true" if operation.active else "false"
        role = "body_activation" if operation.active else "body_deactivation"
    elif isinstance(operation, SetPumpSpeed):
        requested_value = str(operation.rpm)
        role = (
            "priming"
            if values.get("priming_step") == "true"
            else (
                "pool_temperature_probe"
                if operation.metadata.get("reason_code")
                == "pool_temperature_probe_required"
                else "thermal_pump_target"
            )
        )
    elif isinstance(operation, SetHeatMode):
        requested_value = operation.mode.value
        role = "heat_source"
    else:
        raise ValueError("unsupported operation in thermal residual plan")
    hold_raw = values.get("minimum_verified_hold_seconds")
    if hold_raw is None:
        hold = None
    elif isinstance(hold_raw, int) and not isinstance(hold_raw, bool):
        hold = hold_raw
    elif isinstance(hold_raw, str) and hold_raw.isdecimal():
        hold = int(hold_raw)
    else:
        raise ValueError("invalid minimum verified hold metadata")
    return ThermalOperationSignature(
        operation_type=type(operation).__name__,
        equipment_id=operation.equipment_id,
        requested_value=requested_value,
        role=role,
        minimum_verified_hold_seconds=hold,
    )


def assess_execution_compatibility(
    originating: ThermalExecutionCurrentness,
    current: ThermalExecutionCurrentness,
    *,
    progress: ThermalExecutionProgress = ThermalExecutionProgress(),
) -> ThermalExecutionCompatibilityDecision:
    """Prove semantic continuation from PoolOS-attributed progress only."""

    def result(
        disposition: ThermalExecutionCompatibilityDisposition,
        reason: str,
    ) -> ThermalExecutionCompatibilityDecision:
        return ThermalExecutionCompatibilityDecision(
            disposition=disposition,
            reason_code=reason,
            originating_evaluation_id=originating.evaluation_id,
            originating_plan_id=originating.plan_id,
            current_evaluation_id=current.evaluation_id,
            current_plan_id=current.plan_id,
            execution_purpose_id=(
                originating.purpose.purpose_id
                if originating.purpose.purpose_id == current.purpose.purpose_id
                else None
            ),
        )

    if originating.purpose != current.purpose:
        return result(
            ThermalExecutionCompatibilityDisposition.SUPERSEDED,
            "thermal_execution_purpose_superseded",
        )

    if (
        originating.evaluation_id == current.evaluation_id
        and originating.plan_id == current.plan_id
    ):
        return result(
            ThermalExecutionCompatibilityDisposition.SAME_PURPOSE,
            "thermal_execution_same_plan_instance",
        )

    original = originating.residual_plan.operations
    verified = progress.verified_prefix
    if len(verified) > len(original) or original[: len(verified)] != verified:
        return result(
            ThermalExecutionCompatibilityDisposition.UNKNOWN,
            "thermal_execution_progress_unprovable",
        )
    accepted = progress.accepted_current
    maximum_removed = len(verified)
    if accepted is not None:
        if maximum_removed >= len(original) or original[maximum_removed] != accepted:
            return result(
                ThermalExecutionCompatibilityDisposition.UNKNOWN,
                "thermal_execution_accepted_operation_not_next",
            )
        maximum_removed += 1

    if current.residual_plan.disposition is ThermalPlanDisposition.BLOCKED:
        return result(
            ThermalExecutionCompatibilityDisposition.UNKNOWN,
            "thermal_execution_current_plan_blocked",
        )

    residual = current.residual_plan.operations
    if (
        current.residual_plan.disposition
        is ThermalPlanDisposition.ALREADY_CONVERGED
        and not residual
    ):
        if len(verified) == len(original):
            return result(
                ThermalExecutionCompatibilityDisposition.CONVERGED,
                "thermal_execution_purpose_converged",
            )
        if accepted is not None and maximum_removed == len(original):
            return result(
                ThermalExecutionCompatibilityDisposition.PROGRESS_COMPATIBLE,
                "thermal_execution_convergence_pending_step_verification",
            )
        return result(
            ThermalExecutionCompatibilityDisposition.UNKNOWN,
            "thermal_execution_convergence_not_attributed",
        )

    matching_offsets = tuple(
        offset
        for offset in range(len(verified), maximum_removed + 1)
        if original[offset:] == residual
    )
    if matching_offsets:
        removed = max(matching_offsets)
        disposition = (
            ThermalExecutionCompatibilityDisposition.SAME_PURPOSE
            if removed == 0
            else ThermalExecutionCompatibilityDisposition.PROGRESS_COMPATIBLE
        )
        return result(
            disposition,
            (
                "thermal_execution_same_purpose_new_epoch"
                if disposition is ThermalExecutionCompatibilityDisposition.SAME_PURPOSE
                else "thermal_execution_residual_progress_compatible"
            ),
        )

    return result(
        ThermalExecutionCompatibilityDisposition.UNKNOWN,
        "thermal_execution_residual_plan_incompatible",
    )


__all__ = [
    "ThermalExecutionCompatibilityDecision",
    "ThermalExecutionCompatibilityDisposition",
    "ThermalExecutionCurrentness",
    "ThermalExecutionProgress",
    "ThermalExecutionPurpose",
    "ThermalExecutionPurposeKind",
    "ThermalOperationSignature",
    "ThermalResidualPlan",
    "assess_execution_compatibility",
    "operation_signature",
    "purpose_from_assessment",
    "residual_plan_from_assessment",
]
