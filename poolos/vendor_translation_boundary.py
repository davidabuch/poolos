"""Deterministic, non-delivering vendor translation for dispatch requests.

Epic 10.16H converts one ready execution dispatch request into immutable,
ordered vendor-command translation evidence. It delegates each canonical
operation to the existing integration translation contract and performs no
transport selection, network operation, Home Assistant call, Pentair call,
delivery, acknowledgement, verification, or physical actuation.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from hashlib import sha256
import json
from types import MappingProxyType
from typing import Any, Callable, Mapping

from .execution_dispatch_boundary import (
    ExecutionDispatchBoundaryResult,
    ExecutionDispatchDisposition,
    ExecutionDispatchRequest,
)
from .integration import PoolOperation, TranslationResult, VendorCommand
from .integration.exceptions import IntegrationError

OperationTranslator = Callable[[PoolOperation], TranslationResult]


def _canonical_json(value: object) -> str:
    return json.dumps(
        value,
        ensure_ascii=True,
        separators=(",", ":"),
        sort_keys=True,
    )


def _derived_id(prefix: str, payload: Mapping[str, object]) -> str:
    canonical = _canonical_json(dict(sorted(payload.items())))
    return prefix + sha256(canonical.encode("utf-8")).hexdigest()[:24]


def _command_payload(command: VendorCommand) -> Mapping[str, object]:
    return {
        "vendor": command.vendor,
        "operation": command.operation,
        "target": command.target,
        "parameters": dict(command.parameters),
        "metadata": dict(command.metadata),
    }


class VendorTranslationDisposition(str, Enum):
    """Outcome of one dispatch-to-vendor translation evaluation."""

    TRANSLATED = "translated"
    REJECTED = "rejected"


class VendorTranslationReason(str, Enum):
    """Stable machine-readable translation-boundary outcome reasons."""

    DISPATCH_TRANSLATED = "dispatch_translated"
    DISPATCH_NOT_READY = "dispatch_not_ready"
    DISPATCH_EVIDENCE_INVALID = "dispatch_evidence_invalid"
    PLAN_IDENTITY_MISMATCH = "plan_identity_mismatch"
    OPERATION_TRANSLATION_FAILED = "operation_translation_failed"
    EMPTY_TRANSLATION_RESULT = "empty_translation_result"
    TRANSLATION_RESULT_INVALID = "translation_result_invalid"


@dataclass(frozen=True, slots=True)
class VendorTranslatedStep:
    """Immutable ordered translation evidence for one execution-plan step."""

    translation_id: str
    step_id: str
    sequence: int
    operation_id: str
    commands: tuple[VendorCommand, ...]
    warnings: tuple[str, ...] = ()
    metadata: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        for field_name, value in (
            ("translation_id", self.translation_id),
            ("step_id", self.step_id),
            ("operation_id", self.operation_id),
        ):
            if not value.strip():
                raise ValueError(f"{field_name} must not be empty")
        if self.sequence < 1:
            raise ValueError("sequence must be at least 1")
        commands = tuple(self.commands)
        if not commands:
            raise ValueError("translated step requires at least one command")
        if any(not isinstance(command, VendorCommand) for command in commands):
            raise TypeError("commands must contain VendorCommand instances")
        warnings = tuple(self.warnings)
        if any(not warning.strip() for warning in warnings):
            raise ValueError("warnings must not contain empty values")
        object.__setattr__(self, "commands", commands)
        object.__setattr__(self, "warnings", warnings)
        object.__setattr__(self, "metadata", MappingProxyType(dict(self.metadata)))


@dataclass(frozen=True, slots=True)
class VendorTranslationBoundaryResult:
    """Immutable evidence from one vendor-translation boundary evaluation."""

    result_id: str
    disposition: VendorTranslationDisposition
    reason: VendorTranslationReason
    dispatch_result: ExecutionDispatchBoundaryResult
    translated_steps: tuple[VendorTranslatedStep, ...] = ()
    failure_step_id: str | None = None
    failure_detail: str | None = None
    provenance: Mapping[str, str] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not self.result_id.strip():
            raise ValueError("result_id must not be empty")
        translated_steps = tuple(self.translated_steps)
        if self.disposition is VendorTranslationDisposition.TRANSLATED:
            if self.reason is not VendorTranslationReason.DISPATCH_TRANSLATED:
                raise ValueError("translated result requires dispatch-translated reason")
            if not translated_steps:
                raise ValueError("translated result requires translated steps")
            expected = list(range(1, len(translated_steps) + 1))
            actual = [step.sequence for step in translated_steps]
            if actual != expected:
                raise ValueError("translated step sequences must be contiguous and ordered")
            if self.failure_step_id is not None or self.failure_detail is not None:
                raise ValueError("translated result cannot contain failure evidence")
        elif translated_steps:
            raise ValueError("rejected result cannot contain translated steps")
        if self.failure_step_id is not None and not self.failure_step_id.strip():
            raise ValueError("failure_step_id must not be empty when provided")
        if self.failure_detail is not None and not self.failure_detail.strip():
            raise ValueError("failure_detail must not be empty when provided")
        object.__setattr__(self, "translated_steps", translated_steps)
        object.__setattr__(self, "provenance", MappingProxyType(dict(self.provenance)))

    @property
    def commands(self) -> tuple[VendorCommand, ...]:
        """Return all translated commands in deterministic plan-step order."""

        return tuple(
            command
            for translated_step in self.translated_steps
            for command in translated_step.commands
        )


@dataclass(frozen=True, slots=True)
class VendorTranslationBoundary:
    """Translate ready dispatch operations without delivering any command."""

    boundary_name: str = "poolos.vendor_translation_boundary"

    def __post_init__(self) -> None:
        if not self.boundary_name.strip():
            raise ValueError("boundary_name must not be empty")

    def translate(
        self,
        dispatch_result: ExecutionDispatchBoundaryResult,
        translator: OperationTranslator,
    ) -> VendorTranslationBoundaryResult:
        """Translate one ready dispatch request into ordered vendor commands."""

        if dispatch_result.disposition is not ExecutionDispatchDisposition.READY:
            return self._result(
                dispatch_result,
                reason=VendorTranslationReason.DISPATCH_NOT_READY,
            )

        dispatch_request = dispatch_result.dispatch_request
        if dispatch_request is None:
            return self._result(
                dispatch_result,
                reason=VendorTranslationReason.DISPATCH_EVIDENCE_INVALID,
            )

        if not self._valid_dispatch_evidence(dispatch_result, dispatch_request):
            return self._result(
                dispatch_result,
                reason=VendorTranslationReason.DISPATCH_EVIDENCE_INVALID,
            )

        plan = dispatch_request.plan
        if plan.plan_id != dispatch_request.provenance.get(
            "source_execution_plan_id", plan.plan_id
        ):
            return self._result(
                dispatch_result,
                reason=VendorTranslationReason.PLAN_IDENTITY_MISMATCH,
            )

        translated_steps: list[VendorTranslatedStep] = []
        for step in plan.steps:
            try:
                translation = translator(step.operation)
            except IntegrationError as exc:
                return self._result(
                    dispatch_result,
                    reason=VendorTranslationReason.OPERATION_TRANSLATION_FAILED,
                    failure_step_id=step.step_id,
                    failure_detail=f"{type(exc).__name__}:{exc}",
                )
            if not isinstance(translation, TranslationResult):
                return self._result(
                    dispatch_result,
                    reason=VendorTranslationReason.TRANSLATION_RESULT_INVALID,
                    failure_step_id=step.step_id,
                    failure_detail="translator_must_return_translation_result",
                )
            if not translation.commands:
                return self._result(
                    dispatch_result,
                    reason=VendorTranslationReason.EMPTY_TRANSLATION_RESULT,
                    failure_step_id=step.step_id,
                    failure_detail="translation_result_contains_no_commands",
                )
            translation_id = _derived_id(
                "vendor-step-translation-",
                {
                    "boundary_name": self.boundary_name,
                    "commands": [
                        _command_payload(command) for command in translation.commands
                    ],
                    "dispatch_request_id": dispatch_request.dispatch_request_id,
                    "operation_id": step.operation.operation_id,
                    "sequence": step.sequence,
                    "step_id": step.step_id,
                    "warnings": list(translation.warnings),
                },
            )
            translated_steps.append(
                VendorTranslatedStep(
                    translation_id=translation_id,
                    step_id=step.step_id,
                    sequence=step.sequence,
                    operation_id=step.operation.operation_id,
                    commands=translation.commands,
                    warnings=translation.warnings,
                    metadata={
                        **dict(translation.metadata),
                        "dispatch_request_id": dispatch_request.dispatch_request_id,
                        "plan_id": plan.plan_id,
                    },
                )
            )

        return self._result(
            dispatch_result,
            reason=VendorTranslationReason.DISPATCH_TRANSLATED,
            translated_steps=tuple(translated_steps),
        )

    @staticmethod
    def _valid_dispatch_evidence(
        dispatch_result: ExecutionDispatchBoundaryResult,
        dispatch_request: ExecutionDispatchRequest,
    ) -> bool:
        schedule_result = dispatch_result.schedule_result
        scheduled_plan = schedule_result.scheduled_plan
        return (
            scheduled_plan is not None
            and dispatch_request.plan is scheduled_plan.plan
            and dispatch_request.schedule_id == scheduled_plan.schedule_id
            and dispatch_request.authorization_id == scheduled_plan.authorization_id
            and dispatch_request.dispatch_request_id
            == dispatch_result.provenance.get(
                "execution_dispatch_request_id",
                dispatch_request.dispatch_request_id,
            )
        )

    def _result(
        self,
        dispatch_result: ExecutionDispatchBoundaryResult,
        *,
        reason: VendorTranslationReason,
        translated_steps: tuple[VendorTranslatedStep, ...] = (),
        failure_step_id: str | None = None,
        failure_detail: str | None = None,
    ) -> VendorTranslationBoundaryResult:
        disposition = (
            VendorTranslationDisposition.TRANSLATED
            if reason is VendorTranslationReason.DISPATCH_TRANSLATED
            else VendorTranslationDisposition.REJECTED
        )
        dispatch_request = dispatch_result.dispatch_request
        result_id = _derived_id(
            "vendor-translation-boundary-result-",
            {
                "boundary_name": self.boundary_name,
                "dispatch_result_id": dispatch_result.result_id,
                "dispatch_request_id": (
                    dispatch_request.dispatch_request_id
                    if dispatch_request is not None
                    else "none"
                ),
                "disposition": disposition.value,
                "failure_detail": failure_detail or "",
                "failure_step_id": failure_step_id or "",
                "reason": reason.value,
                "translation_ids": [step.translation_id for step in translated_steps],
            },
        )
        plan = dispatch_request.plan if dispatch_request is not None else None
        provenance = {
            **dict(dispatch_result.provenance),
            "vendor_translation_boundary": self.boundary_name,
            "vendor_translation_boundary_result_id": result_id,
            "vendor_translation_disposition": disposition.value,
            "vendor_translation_reason": reason.value,
            "source_execution_dispatch_result_id": dispatch_result.result_id,
            "source_execution_dispatch_request_id": (
                dispatch_request.dispatch_request_id
                if dispatch_request is not None
                else ""
            ),
            "source_execution_plan_id": plan.plan_id if plan is not None else "",
            "source_proposal_id": plan.proposal_id if plan is not None else "",
            "source_decision_id": plan.decision_id if plan is not None else "",
            "source_context_id": plan.context_id if plan is not None else "",
            "source_correlation_id": (
                dispatch_request.correlation_id or ""
                if dispatch_request is not None
                else ""
            ),
            "translated_step_count": str(len(translated_steps)),
            "translated_command_count": str(
                sum(len(step.commands) for step in translated_steps)
            ),
            "failure_step_id": failure_step_id or "",
            "failure_detail": failure_detail or "",
        }
        return VendorTranslationBoundaryResult(
            result_id=result_id,
            disposition=disposition,
            reason=reason,
            dispatch_result=dispatch_result,
            translated_steps=translated_steps,
            failure_step_id=failure_step_id,
            failure_detail=failure_detail,
            provenance=provenance,
        )
